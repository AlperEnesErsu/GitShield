import { useState } from "react";
import { Link } from "react-router-dom";
import { api, BatchResult, CiState, Dependency, PullSummary, Risk } from "../api";
import { Badge, ErrorBox } from "./ui";

const LEVEL: Record<Risk["level"], [string, string]> = {
  low: ["success", "Düşük"],
  medium: ["medium", "Orta"],
  high: ["critical", "Yüksek"],
};

export function RiskBadge({ risk }: { risk: Risk | null | undefined }) {
  if (!risk) return null;
  const [tone, label] = LEVEL[risk.level];
  const why = risk.factors.map((f) => `+${f.points} ${f.label}`).join("\n") || "Risk faktörü yok";
  return (
    <Badge tone={tone} title={`Risk ${risk.score}/100 · ${label}\n${why}`}>
      <span className="risk-meter" aria-hidden><span style={{ width: `${risk.score}%` }} /></span>
      Risk {risk.score}
    </Badge>
  );
}

const CI: Record<CiState, [string, string, string]> = {
  success: ["success", "✓", "CI başarılı"],
  failure: ["critical", "✕", "CI başarısız"],
  pending: ["info", "◌", "CI sürüyor"],
  none: ["muted", "–", "CI yok"],
};

const CLEARED: Record<string, string> = { environment: "ortam", base: "hedef dal", outdated: "eski dal" };

export function CiBadge({ ci, compact, blame }: { ci: CiState | undefined; compact?: boolean; blame?: string | null }) {
  if (!ci || (compact && ci === "none")) return null;
  if (ci === "failure" && blame && CLEARED[blame]) {
    // Diagnosed: failing because of the environment or the base branch, not this PR.
    return <Badge tone="info" title={`CI kırık ama teşhis: PR'ın suçu değil (${CLEARED[blame]})`}>! CI · {CLEARED[blame]}</Badge>;
  }
  const [tone, icon, label] = CI[ci];
  return <Badge tone={tone} title={label}>{icon} {compact ? "CI" : label}</Badge>;
}

const CHANGE: Record<Dependency["change"], [string, string]> = {
  major: ["high", "major"],
  minor: ["info", "minor"],
  patch: ["success", "patch"],
  unknown: ["muted", "?"],
};

export function ChangeBadge({ dep }: { dep: Dependency | null | undefined }) {
  if (!dep) return null;
  const [tone, label] = CHANGE[dep.change];
  return <Badge tone={tone} title="Sürüm atlaması türü">{label}</Badge>;
}

/** Score + factor breakdown for the PR page. */
export function RiskPanel({ risk, ci }: { risk: Risk | null; ci: CiState }) {
  if (!risk) return null;
  const [tone, label] = LEVEL[risk.level];
  const max = Math.max(1, ...risk.factors.map((f) => f.points));
  return (
    <section className={`risk-panel risk-${risk.level}`}>
      <div className="risk-score">
        <svg viewBox="0 0 36 36" className="risk-ring" aria-hidden>
          <circle cx="18" cy="18" r="15.9" className="ring-bg" />
          <circle cx="18" cy="18" r="15.9" className="ring-fg" strokeDasharray={`${risk.score} 100`} />
        </svg>
        <div className="risk-number">
          <strong>{risk.score}</strong>
          <span>{label} risk</span>
        </div>
      </div>
      <div className="risk-factors">
        <div className="risk-factors-head">
          <h3>Neden bu skor?</h3>
          <CiBadge ci={ci} />
          <Badge tone={tone}>{label}</Badge>
        </div>
        {risk.factors.length === 0 ? (
          <p className="muted small">Belirgin bir risk faktörü yok.</p>
        ) : (
          <ul>
            {risk.factors.map((f) => (
              <li key={f.label}>
                <span className="factor-label">{f.label}</span>
                <span className="factor-bar"><span style={{ width: `${(f.points / max) * 100}%` }} /></span>
                <span className="factor-points">+{f.points}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function eligible(p: PullSummary) {
  return p.ci === "success" && (p.dependency?.change === "minor" || p.dependency?.change === "patch")
    && p.review?.status !== "submitted";
}

/** Dependency updates with safe defaults for one-click batch approval. */
export function DependencyPanel({ repo, pulls, onDone }: {
  repo: string;
  pulls: PullSummary[];
  onDone: () => void;
}) {
  const deps = pulls.filter((p) => p.dependency);
  const [selected, setSelected] = useState<Set<number>>(() => new Set(deps.filter(eligible).map((p) => p.number)));
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<BatchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!deps.length) return null;

  const chosen = deps.filter((p) => selected.has(p.number));
  const hasMajor = chosen.some((p) => p.dependency?.change === "major");
  const toggle = (n: number) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await api.dependencyBatch(repo, chosen.map((p) => p.number), hasMajor);
      setResults(res.results);
      setConfirming(false);
      setSelected(new Set());
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const resultFor = (n: number) => results?.find((r) => r.number === n);

  return (
    <section className="dep-panel">
      <header className="dep-head">
        <div>
          <h2>Bağımlılık güncellemeleri <span className="count">{deps.length}</span></h2>
          <p className="muted small">
            CI'ı yeşil minor/patch güncellemeler varsayılan olarak seçili. Her biri önce statik taramadan geçer;
            bulgu çıkarsa onaylanmaz.
          </p>
        </div>
      </header>
      <div className="dep-list">
        {deps.map((p) => {
          const r = resultFor(p.number);
          const blocked = p.ci !== "success" || p.review?.status === "submitted";
          return (
            <label key={p.number} className={`dep-row ${blocked ? "blocked" : ""}`}>
              <input type="checkbox" checked={selected.has(p.number)} disabled={blocked || running}
                     onChange={() => toggle(p.number)} />
              <div className="dep-main">
                <div className="dep-title">
                  <strong>{p.dependency!.package}</strong>
                  {p.dependency!.from && <span className="mono muted">{p.dependency!.from} → {p.dependency!.to}</span>}
                </div>
                <Link to={`/r/${repo}/pull/${p.number}`} className="muted small" onClick={(e) => e.stopPropagation()}>
                  #{p.number} {p.title}
                </Link>
              </div>
              <div className="dep-badges">
                <ChangeBadge dep={p.dependency} />
                <CiBadge ci={p.ci} />
                {p.review?.status === "submitted" && <Badge tone="success">gönderildi</Badge>}
                {r && (
                  <Badge tone={r.status === "approved" ? "success" : r.status === "failed" ? "critical" : "medium"}
                         title={r.reason}>
                    {r.status === "approved" ? "✓ onaylandı" : r.reason}
                  </Badge>
                )}
              </div>
            </label>
          );
        })}
      </div>
      {error && <ErrorBox error={error} />}
      <div className={`dep-bar ${confirming ? "confirm" : ""}`}>
        {confirming ? (
          <>
            <span>
              <strong>{chosen.length}</strong> PR taranıp temizse senin hesabından <Badge tone="success">Onay</Badge>{" "}
              olarak gönderilecek{hasMajor && <> — <strong>major güncelleme içeriyor</strong></>}. Emin misin?
            </span>
            <div className="spacer" />
            <button className="btn btn-ghost" onClick={() => setConfirming(false)} disabled={running}>Vazgeç</button>
            <button className="btn btn-primary" onClick={run} disabled={running}>
              {running ? <><span className="spinner" /> İşleniyor…</> : "Evet, onayla"}
            </button>
          </>
        ) : (
          <>
            <span className="muted small">{chosen.length} seçili</span>
            <div className="spacer" />
            <button className="btn btn-primary" disabled={!chosen.length} onClick={() => setConfirming(true)}>
              Seçilenleri toplu onayla…
            </button>
          </>
        )}
      </div>
    </section>
  );
}
