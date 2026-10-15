import { ReactNode } from "react";
import { PullDetail, Review, ReviewComment, Severity } from "../../api";
import { ProcessStepper } from "../../components/Process";
import { RiskWord } from "../../components/insights";
import { SeverityBadge, VerdictBadge } from "../../components/ui";
import { timeAgo } from "../../hooks";

const SEVERITY_ORDER: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

const SEVERITY_WORD: Record<Severity, string> = {
  CRITICAL: "kritik", HIGH: "yüksek", MEDIUM: "orta", LOW: "düşük", INFO: "bilgi",
};

const CI_WORD: Record<PullDetail["ci"], string | null> = {
  success: "CI geçti", failure: "CI başarısız", pending: "CI sürüyor", none: null,
};

/** The top of the PR page: what GitShield found, and the one thing to do next. */
export function ResultCard({ pr, review, findings, starting, onStart, onShowFindings }: {
  pr: PullDetail;
  review: Review | null;
  findings: ReviewComment[];
  starting: boolean;
  onStart: () => void;
  onShowFindings: () => void;
}) {
  const sorted = [...findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  );
  const serious = findings.filter((c) => c.severity === "CRITICAL" || c.severity === "HIGH").length;
  const bySeverity = SEVERITY_ORDER.map((s) => [s, findings.filter((c) => c.severity === s).length] as const)
    .filter(([, n]) => n > 0);
  const outdated = !!review && review.head_sha !== pr.head_sha && pr.state === "open";
  const busyButton = (label: string, primary = true) => (
    <button className={`btn ${primary ? "btn-primary" : ""}`} onClick={onStart} disabled={starting}>
      {starting ? <span className="spinner" /> : label}
    </button>
  );

  let tone = "neutral";
  let headline: string;
  let todo: string;
  let action: ReactNode = null;

  if (!review) {
    headline = "Bu PR henüz incelenmedi";
    todo = "İncelemeyi başlat. Güvenlik taraması, AI review ve doğrulama kendiliğinden çalışır; bitince sonuç burada görünür.";
    action = pr.state === "open" ? busyButton("İncelemeyi başlat") : null;
  } else if (review.status === "running") {
    tone = "info";
    const step = review.progress?.find((s) => s.status === "running");
    headline = step ? `İnceleniyor: ${step.label}` : "İnceleniyor";
    todo = "Beklemen yeterli; sayfa kendiliğinden güncellenir.";
  } else if (review.status === "failed") {
    tone = "critical";
    headline = "İnceleme tamamlanamadı";
    todo = review.error ?? "Bilinmeyen bir hata oluştu.";
    action = busyButton("Yeniden dene", false);
  } else {
    tone = findings.length === 0 ? "success" : serious ? "critical" : "medium";
    headline = findings.length === 0
      ? "Sorun bulunmadı"
      : `${findings.length} sorun bulundu${serious ? ` — ${serious} tanesi yüksek önemde` : ""}`;
    if (outdated) {
      todo = "Bu sonuç eski bir commit için. PR'a yeni commit geldi; yeniden incelemek gerekiyor.";
      action = busyButton("Yeniden incele");
    } else if (review.status === "submitted") {
      todo = `Yapacak bir şey yok: review ${timeAgo(review.submitted_at)} GitHub'a gönderildi.`;
      action = review.github_review_url ? (
        <a className="btn" href={review.github_review_url} target="_blank" rel="noreferrer">GitHub'da gör ↗</a>
      ) : null;
    } else if (findings.length === 0) {
      todo = "Kısa özeti kontrol et ve onayı GitHub'a gönder.";
      action = <button className="btn btn-primary" onClick={onShowFindings}>Gönderime git ↓</button>;
    } else {
      todo = "Bulgulara göz at; gereksiz olanların işaretini kaldır, sonra review'u GitHub'a gönder.";
      action = <button className="btn btn-primary" onClick={onShowFindings}>Bulguları incele ↓</button>;
    }
  }

  const ci = CI_WORD[pr.ci];
  return (
    <section className={`result-card result-${tone}`}>
      <div className="result-main">
        <p className="result-label">GitShield sonucu</p>
        <h2 className="result-headline">{headline}</h2>
        {bySeverity.length > 0 && (
          <div className="result-counts">
            {bySeverity.map(([s, n]) => (
              <span key={s} className={`result-count sev-${s.toLowerCase()}`}>{n} {SEVERITY_WORD[s]}</span>
            ))}
          </div>
        )}
        {sorted.length > 0 && (
          <ul className="result-findings">
            {sorted.slice(0, 3).map((c) => (
              <li key={c.id}>
                <SeverityBadge severity={c.severity} />
                <a href={`#comment-${c.id}`} onClick={onShowFindings}>{c.title}</a>
                <span className="mono small muted">{c.path}{c.line !== null ? `:${c.line}` : ""}</span>
              </li>
            ))}
            {sorted.length > 3 && <li className="muted small">ve {sorted.length - 3} bulgu daha</li>}
          </ul>
        )}
        {review?.status === "running" && <ProcessStepper review={review} />}
        <div className="result-facts">
          <RiskWord risk={pr.risk} />
          {ci && <span className={pr.ci === "failure" ? "fact-bad" : ""}>{ci}</span>}
          {review && (review.status === "ready" || review.status === "submitted") && (
            <span>Önerilen karar: <VerdictBadge verdict={review.verdict} /></span>
          )}
        </div>
      </div>
      <div className={`result-todo ${review?.status === "failed" ? "todo-alert" : ""}`}>
        <p className="result-label">Ne yapmalısın?</p>
        <p>{todo}</p>
        {action}
      </div>
    </section>
  );
}
