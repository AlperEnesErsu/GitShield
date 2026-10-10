import { useEffect, useState } from "react";
import { api, CiBlame, CiDiagnosis, CiJob } from "../api";
import { timeAgo } from "../hooks";
import { Badge, ErrorBox, Loading } from "./ui";

const BLAME_TONE: Record<CiBlame | "none", string> = {
  pr: "critical",
  environment: "info",
  base: "medium",
  flaky: "medium",
  unknown: "muted",
  none: "success",
};

function JobRow({ job, repo, onRerun }: { job: CiJob; repo: string; onRerun: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  // Rerunning only helps when the failure is not deterministic (a broken PR or base fails again).
  const canRerun = job.is_actions && (job.blame === "environment" || job.blame === "flaky" || job.blame === "unknown");

  const rerun = async () => {
    setState("busy");
    setError(null);
    try {
      await api.rerunJob(repo, job.id);
      setState("done");
      onRerun();
    } catch (e) {
      setError((e as Error).message);
      setState("idle");
    } finally {
      setConfirm(false);
    }
  };

  return (
    <li className={`ci-job blame-${job.blame}`}>
      <div className="ci-job-head">
        <span className="mono ci-job-name">{job.name}</span>
        <Badge tone={BLAME_TONE[job.blame]}>{job.blame_label}</Badge>
        <strong className="ci-job-title">{job.title}</strong>
        <div className="spacer" />
        {job.url && <a className="small" href={job.url} target="_blank" rel="noreferrer">Günlük ↗</a>}
      </div>
      <p className="ci-job-text">{job.explanation}</p>
      {job.evidence && <code className="ci-evidence">{job.evidence}</code>}
      <p className="ci-job-fix"><span className="muted">Öneri:</span> {job.suggestion}</p>
      {job.base?.conclusion && (
        <p className="small muted">
          Hedef daldaki aynı iş: <strong>{job.base.conclusion === "success" ? "başarılı" : job.base.conclusion}</strong>
          {job.base.at && ` (${timeAgo(job.base.at)})`}
          {job.base.run_url && <> · <a href={job.base.run_url} target="_blank" rel="noreferrer">çalışma ↗</a></>}
        </p>
      )}
      {job.audit && job.audit.packages.length > 0 && (
        <p className="small muted">
          Açık bulunan paketler: <span className="mono">{job.audit.packages.join(", ")}</span>
          {" · "}PR'ın değiştirdikleri: <strong>{job.audit.touched_by_pr.length ? job.audit.touched_by_pr.join(", ") : "hiçbiri"}</strong>
        </p>
      )}
      {job.excerpt && (
        <details className="ci-excerpt">
          <summary>Günlük özeti</summary>
          <pre className="pre">{job.excerpt}</pre>
        </details>
      )}
      {error && <ErrorBox error={error} />}
      {canRerun && (
        <div className="ci-job-actions">
          {state === "done" ? (
            <span className="small" style={{ color: "var(--success)" }}>✓ Yeniden çalıştırma başlatıldı</span>
          ) : confirm ? (
            <>
              <span className="small">Bu iş GitHub'da yeniden çalıştırılsın mı?</span>
              <button className="btn btn-sm btn-ghost" onClick={() => setConfirm(false)}>Vazgeç</button>
              <button className="btn btn-sm btn-primary" onClick={rerun} disabled={state === "busy"}>
                {state === "busy" ? <span className="spinner" /> : "Evet, çalıştır"}
              </button>
            </>
          ) : (
            <button className="btn btn-sm" onClick={() => setConfirm(true)}>↻ Yeniden çalıştır</button>
          )}
        </div>
      )}
    </li>
  );
}

/** "Why did CI fail?" for a PR: known patterns, base-branch comparison, blame and fixes. */
export function CiDiagnosisCard({ repo, number, headSha }: { repo: string; number: number; headSha: string }) {
  const [data, setData] = useState<CiDiagnosis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<"base" | "ai" | null>("base");

  const load = async (opts: { refresh?: boolean; ai?: boolean } = {}) => {
    setLoading(opts.ai ? "ai" : "base");
    setError(null);
    try {
      setData(await api.ciDiagnosis(repo, number, opts));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(null);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repo, number, headSha]);

  return (
    <section className="ci-card">
      <header className="ci-card-head">
        <div>
          <h2>CI neden kırıldı?</h2>
          <p className="muted small">Kırık işlerin günlükleri okunur, hedef dalla karşılaştırılır; suçun PR'da mı ortamda mı olduğu söylenir.</p>
        </div>
        <div className="head-actions">
          <button className="btn btn-sm" onClick={() => load({ refresh: true })} disabled={loading !== null}>↻ Tekrar kontrol et</button>
          {data && !data.ai && data.jobs.length > 0 && (
            <button className="btn btn-sm btn-primary" onClick={() => load({ ai: true })} disabled={loading !== null}
                    title="Günlükleri ve PR'ı LLM'e yorumlatır (LLM kotası kullanır)">
              {loading === "ai" ? <span className="spinner" /> : "AI ile derinleştir"}
            </button>
          )}
        </div>
      </header>

      {error && <ErrorBox error={error} onRetry={() => load({ refresh: true })} />}
      {loading === "base" && !data && <Loading label="CI günlükleri okunuyor" />}

      {data && (
        <>
          <div className={`next-action ci-verdict verdict-${data.verdict.blame}`}>
            <div className="next-text">
              <div className="next-title">{data.verdict.text}</div>
              <div className="next-body">
                {data.failed} kırık · {data.passing} geçti{data.pending > 0 && ` · ${data.pending} sürüyor`} ·
                hedef dal <span className="mono">{data.base}</span>
                {data.cached_at && ` · ${timeAgo(data.cached_at)} kontrol edildi`}
              </div>
            </div>
          </div>

          {data.ai && (
            <div className="ci-ai">
              <div className="ci-ai-head">
                <strong>AI yorumu</strong>
                <Badge tone={BLAME_TONE[data.ai.blame]}>{data.ai.blame}</Badge>
                <Badge tone="muted">güven: {data.ai.confidence}</Badge>
              </div>
              <p>{data.ai.summary}</p>
              <p className="small"><span className="muted">Neden:</span> {data.ai.cause}</p>
              <ol className="ci-steps">{data.ai.fix_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
            </div>
          )}

          {data.jobs.length > 0 && (
            <ul className="ci-jobs">
              {data.jobs.map((j) => (
                <JobRow key={j.id} job={j} repo={repo} onRerun={() => setTimeout(() => load({ refresh: true }), 4000)} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
