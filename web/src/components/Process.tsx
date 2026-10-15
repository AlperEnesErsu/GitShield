import type { ProgressStep, Review, StepStatus } from "../api";

const DESCRIPTIONS: Record<ProgressStep["key"], string> = {
  fetch: "PR'ın diff'i GitHub'dan çekilir",
  scan: "Secret, OWASP kuralları ve entropi analizi",
  ai_review: "LLM kodu okur ve yorum yazar",
  verify: "İkinci geçiş her yorumu diff'e karşı doğrular",
  approve: "Yorumları seç, düzenle, kararı belirle",
  submit: "Onaylanan review PR'a yorum olarak gider",
};

const DEFAULT_STEPS: ProgressStep[] = (
  [
    ["fetch", "PR alındı"],
    ["scan", "Statik tarama"],
    ["ai_review", "AI review"],
    ["verify", "Doğrulama"],
    ["approve", "Senin onayın"],
    ["submit", "GitHub'a gönderim"],
  ] as const
).map(([key, label]) => ({ key, label, status: "pending", detail: "", started_at: null, finished_at: null }));

function duration(step: ProgressStep): string | null {
  if (!step.started_at || !step.finished_at || step.key === "approve") return null;
  const ms = new Date(step.finished_at).getTime() - new Date(step.started_at).getTime();
  if (ms < 1000) return "<1 sn";
  if (ms < 60000) return `${Math.round(ms / 1000)} sn`;
  return `${Math.floor(ms / 60000)} dk ${Math.round((ms % 60000) / 1000)} sn`;
}

function StepIcon({ status, index }: { status: StepStatus; index: number }) {
  switch (status) {
    case "done":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
      );
    case "running":
      return <span className="spinner" aria-hidden />;
    case "failed":
      return <span aria-hidden>!</span>;
    case "skipped":
      return <span aria-hidden>–</span>;
    default:
      return <span aria-hidden>{index + 1}</span>;
  }
}

const STATUS_LABEL: Record<StepStatus, string> = {
  pending: "bekliyor",
  running: "sürüyor",
  done: "tamamlandı",
  skipped: "atlandı",
  failed: "hata",
};

/** Reviews created before step tracking existed have no progress; reconstruct it from their status. */
function stepsFor(review: Review | null | undefined): ProgressStep[] {
  if (!review) return DEFAULT_STEPS;
  if (review.progress?.length) return review.progress;
  const llm = review.provider !== "none";
  const after = review.status === "ready" || review.status === "submitted";
  const status: Record<ProgressStep["key"], StepStatus> = {
    fetch: after ? "done" : "pending",
    scan: after ? "done" : "pending",
    ai_review: after ? (llm ? "done" : "skipped") : "pending",
    verify: after ? (llm ? "done" : "skipped") : "pending",
    approve: review.status === "submitted" ? "done" : review.status === "ready" ? "running" : "pending",
    submit: review.status === "submitted" ? "done" : "pending",
  };
  if (review.status === "failed") status.fetch = "failed";
  return DEFAULT_STEPS.map((s) => ({ ...s, status: status[s.key] }));
}

/** Six-step horizontal pipeline for a review; an all-pending template when there is no review yet. */
export function ProcessStepper({ review }: { review?: Review | null }) {
  const list = stepsFor(review);
  const done = list.filter((s) => s.status === "done" || s.status === "skipped").length;

  return (
    <div className="process">
      <div className="process-bar" role="progressbar" aria-valuemin={0} aria-valuemax={list.length}
           aria-valuenow={done} aria-label="Süreç ilerlemesi">
        <span style={{ width: `${(done / list.length) * 100}%` }} />
      </div>
      <ol className="stepper">
        {list.map((step, i) => {
          const d = duration(step);
          const human = step.key === "approve" || step.key === "submit";
          return (
            <li key={step.key} className={`step step-${step.status} ${human ? "step-human" : ""}`}
                aria-label={`${step.label}: ${STATUS_LABEL[step.status]}`}>
              <div className="step-node"><StepIcon status={step.status} index={i} /></div>
              <div className="step-text">
                <div className="step-title">
                  {step.label}
                  {human && <span className="step-tag">sen</span>}
                </div>
                <div className="step-detail">{step.detail || DESCRIPTIONS[step.key]}</div>
                {d && <div className="step-time">{d}</div>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
