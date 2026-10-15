import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Review } from "../api";
import { ExternalIcon } from "../components/icons";
import { ProcessStepper } from "../components/Process";
import { RiskPanel } from "../components/insights";
import { CiDiagnosisCard } from "../components/CiDiagnosis";
import { Badge, Collapsible, ErrorBox, Loading } from "../components/ui";
import { timeAgo, useAsync } from "../hooks";
import { ResultCard } from "./pull/ResultCard";
import { ReviewPanel } from "./pull/ReviewPanel";
import { FunnelCard } from "./pull/FunnelCard";

const POLL_MS = 2000;

export function PullPage() {
  const { owner, repo, number } = useParams();
  const fullName = `${owner}/${repo}`;
  const prNumber = Number(number);
  const pr = useAsync(() => api.pull(fullName, prNumber), [fullName, prNumber]);
  const [reviewId, setReviewId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [tab, setTab] = useState<"review" | "diff">("review");

  useEffect(() => {
    if (pr.data && reviewId === null) setReviewId(pr.data.latest_review?.id ?? null);
  }, [pr.data, reviewId]);

  const review = useAsync<Review | null>(
    () => (reviewId === null ? Promise.resolve(null) : api.review(reviewId)),
    [reviewId],
  );
  const r = review.data;

  // Poll while the background pipeline is running so the stepper moves live.
  useEffect(() => {
    if (r?.status !== "running") return;
    const t = setTimeout(review.reload, POLL_MS);
    return () => clearTimeout(t);
  }, [r, review.reload]);

  // Refresh the PR (review list, counts) once a run finishes.
  const finished = r && r.status !== "running";
  useEffect(() => {
    if (finished) pr.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);

  const start = async (full = false) => {
    setStarting(true);
    setStartError(null);
    try {
      const { id } = await api.startReview(fullName, prNumber, full);
      setReviewId(id);
      setTab("review");
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  if (pr.error) return <div className="page"><ErrorBox error={pr.error} onRetry={pr.reload} /></div>;
  if (!pr.data) return <div className="page"><Loading label="PR getiriliyor" /></div>;
  const p = pr.data;
  const current = reviewId === null ? null : r;
  const canRerun = p.state === "open" && current?.status !== "running";

  const findings = current?.comments.filter((c) => c.verification !== "rejected") ?? [];
  const showFindings = () => {
    setTab("review");
    requestAnimationFrame(() => document.getElementById("findings")?.scrollIntoView({ behavior: "smooth" }));
  };

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/">Genel bakış</Link> <span className="sep">/</span>{" "}
        <Link to={`/r/${fullName}`}>{fullName}</Link> <span className="sep">/</span> <span>#{p.number}</span>
      </nav>
      <div className="page-head">
        <div>
          <h1>{p.title}</h1>
          <div className="meta-row">
            <span>{p.author} · #{p.number}</span>
            {p.draft && <Badge tone="muted">taslak</Badge>}
            <span>{p.changed_files} dosya değişti</span>
          </div>
        </div>
        <div className="head-actions">
          <a className="btn btn-ghost" href={p.url} target="_blank" rel="noreferrer">GitHub'da aç <ExternalIcon size={14} /></a>
        </div>
      </div>
      {startError && <ErrorBox error={startError} />}

      <ResultCard pr={p} review={current ?? null} findings={findings} starting={starting}
                  onStart={() => start()} onShowFindings={showFindings} />

      {p.ci === "failure" && <CiDiagnosisCard repo={fullName} number={p.number} headSha={p.head_sha} />}

      {review.error && <ErrorBox error={review.error} onRetry={review.reload} />}

      <div className="tabs" role="tablist" id="findings">
        <button role="tab" aria-selected={tab === "review"} className={tab === "review" ? "active" : ""}
                onClick={() => setTab("review")}>Bulgular{current ? ` (${findings.length})` : ""}</button>
        <button role="tab" aria-selected={tab === "diff"} className={tab === "diff" ? "active" : ""}
                onClick={() => setTab("diff")}>Kod değişiklikleri ({p.files.length})</button>
      </div>

      <ReviewPanel review={current ?? null} loading={reviewId !== null && !r} pr={p} tab={tab}
                   setReview={(next) => review.setData(() => next)} onSubmitted={pr.reload} />

      <Collapsible title="Ayrıntılar" hint="İnceleme adımları, risk puanının dökümü, yorum hunisi, önceki review'lar">
        <div className="details-actions">
          {p.reviews.length > 1 && (
            <select className="input select" value={reviewId ?? ""} aria-label="Review seç"
                    onChange={(e) => setReviewId(Number(e.target.value))}>
              {p.reviews.map((x) => (
                <option key={x.id} value={x.id}>
                  Review #{x.id} · {timeAgo(x.created_at)} · {x.status}
                </option>
              ))}
            </select>
          )}
          {current?.mode === "incremental" && current.base_sha && (
            <Badge tone="info" title="Yalnızca son incelenen commit'ten sonraki değişiklikler incelendi">
              Artımlı · {current.base_sha.slice(0, 7)} → {current.head_sha.slice(0, 7)}
            </Badge>
          )}
          <span className="mono small muted">{p.head_ref} → {p.base_ref} · +{p.additions} −{p.deletions}</span>
          {current && (
            <button className="btn btn-sm" onClick={() => start(true)} disabled={starting || !canRerun}
                    title="Önceki review'ları yok sayıp tüm PR diff'ini baştan incele">
              Baştan incele
            </button>
          )}
        </div>
        <ProcessStepper review={current} />
        <RiskPanel risk={p.risk} ci={p.ci} />
        {(current?.status === "ready" || current?.status === "submitted") && <FunnelCard review={current} />}
      </Collapsible>
    </div>
  );
}
