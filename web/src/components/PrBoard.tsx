import { Link } from "react-router-dom";
import type { PullSummary } from "../api";
import { timeAgo } from "../hooks";
import { Badge, VerdictBadge } from "./ui";

type Stage = "todo" | "running" | "approve" | "done" | "failed";

const STAGES: { key: Stage; title: string; hint: string; color: string }[] = [
  { key: "todo", title: "İnceleme bekliyor", hint: "Henüz incelenmedi ya da yeni commit geldi", color: "var(--text-faint)" },
  { key: "running", title: "İnceleniyor", hint: "Tarama, AI review ve doğrulama", color: "var(--series-1)" },
  { key: "approve", title: "Onayını bekliyor", hint: "Yorumları gözden geçir ve gönder", color: "var(--accent)" },
  { key: "done", title: "Gönderildi", hint: "Review PR'da yayında", color: "var(--success)" },
  { key: "failed", title: "Hata", hint: "Yeniden denemek gerekiyor", color: "var(--critical)" },
];

// How many of the six pipeline steps each stage has completed (for the mini progress dashes).
const STEPS_DONE: Record<Stage, number> = { todo: 0, running: 2, approve: 4, done: 6, failed: 1 };

export function stageOf(p: PullSummary): Stage {
  const r = p.review;
  if (!r) return "todo";
  if (r.status === "running") return "running";
  if (r.status === "failed") return "failed";
  if (r.outdated) return "todo";
  return r.status === "submitted" ? "done" : "approve";
}

export function MiniSteps({ stage }: { stage: Stage }) {
  const n = STEPS_DONE[stage];
  return (
    <span className="mini-steps" aria-label={`6 adımdan ${n} tamamlandı`}>
      {Array.from({ length: 6 }, (_, i) => (
        <span key={i} className={i < n ? (stage === "done" ? "ok" : "on") : ""} />
      ))}
    </span>
  );
}

export function PrBoard({ pulls, repo, onStart, starting }: {
  pulls: PullSummary[];
  repo: string;
  onStart: (p: PullSummary) => void;
  starting: number | null;
}) {
  const groups = new Map<Stage, PullSummary[]>(STAGES.map((s) => [s.key, []]));
  for (const p of pulls) groups.get(stageOf(p))!.push(p);
  const visible = STAGES.filter((s) => s.key !== "failed" || groups.get("failed")!.length);

  return (
    <div className="board">
      {visible.map((stage) => {
        const items = groups.get(stage.key)!;
        return (
          <section key={stage.key} className="board-col" aria-label={stage.title}>
            <header className="board-col-head">
              <span className="dot" style={{ background: stage.color }} />
              {stage.title}
              <span className="count">{items.length}</span>
            </header>
            <div className="board-col-hint">{stage.hint}</div>
            {items.length === 0 && <div className="board-empty">—</div>}
            {items.map((p) => (
              <Link key={p.number} to={`/r/${repo}/pull/${p.number}`} className="board-card">
                <div className="board-card-meta">
                  <span className="mono">#{p.number}</span>
                  <img src={p.author_avatar} alt="" width={16} height={16} />
                  <span>{p.author}</span>
                  <span>· {timeAgo(p.updated_at)}</span>
                </div>
                <div className="board-card-title">{p.title}</div>
                <div className="board-card-foot">
                  <MiniSteps stage={stage.key} />
                  {p.draft && <Badge tone="muted">taslak</Badge>}
                  {p.review?.outdated && stage.key === "todo" && <Badge tone="medium">yeni commit</Badge>}
                  {(stage.key === "approve" || stage.key === "done") && p.review && (
                    <>
                      <VerdictBadge verdict={p.review.verdict} />
                      {p.review.open_comments > 0 && <span className="muted small">{p.review.open_comments} yorum</span>}
                    </>
                  )}
                  {(stage.key === "todo" || stage.key === "failed") && (
                    <button className="btn btn-sm" style={{ marginLeft: "auto" }} disabled={starting !== null}
                            onClick={(e) => { e.preventDefault(); onStart(p); }}>
                      {starting === p.number ? <span className="spinner" /> : "İncele"}
                    </button>
                  )}
                </div>
              </Link>
            ))}
          </section>
        );
      })}
    </div>
  );
}
