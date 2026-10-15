import { useMemo, useState } from "react";
import { api, PullDetail, Review, ReviewComment, Verdict, Verification } from "../../api";
import { ErrorBox, VerdictBadge, verdictLabel } from "../../components/ui";
import { timeAgo } from "../../hooks";
import { CommentCard } from "./CommentCard";
import { FollowupsCard } from "./FollowupsCard";

type Filter = "all" | Verification | "included";

const FILTER_LABEL: Record<Filter, string> = {
  all: "Tümü",
  confirmed: "Doğrulanan",
  uncertain: "Belirsiz",
  rejected: "Reddedilen",
  unverified: "Doğrulanmamış",
  included: "Gönderilecek",
};

export function ReviewEditor({ review, pr, setReview, setComment, onSubmitted }: {
  review: Review;
  pr: PullDetail;
  setReview: (r: Review) => void;
  setComment: (c: ReviewComment) => void;
  onSubmitted: () => void;
}) {
  const locked = review.status !== "ready";
  const [summary, setSummary] = useState(review.summary);
  const [verdict, setVerdict] = useState<Verdict>(review.verdict);
  const [filter, setFilter] = useState<Filter>("all");
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const comments = review.comments;
  const included = comments.filter((c) => c.included);
  const inline = included.filter((c) => c.in_diff);
  const outdated = review.head_sha !== pr.head_sha;

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: comments.length, included: included.length };
    for (const c of comments) out[c.verification] = (out[c.verification] ?? 0) + 1;
    return out;
  }, [comments, included.length]);

  const visible = comments.filter((c) =>
    filter === "all" ? true : filter === "included" ? c.included : c.verification === filter,
  );

  const saveMeta = async () => {
    if (summary === review.summary && verdict === review.verdict) return;
    try {
      setReview(await api.patchReview(review.id, { summary, verdict }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await saveMeta();
      const res = await api.submitReview(review.id, verdict);
      setReview(res.review);
      setConfirming(false);
      onSubmitted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="review">
      {outdated && (
        <div className="banner banner-warn">
          Bu review <span className="mono">{review.head_sha.slice(0, 7)}</span> commit'i için yapıldı; PR'a
          sonradan yeni commit geldi. Satır yorumları GitHub'da "outdated" görünebilir. Yeniden incelemen önerilir.
        </div>
      )}
      {review.skipped_files.length > 0 && (
        <div className="banner banner-warn">
          <strong>{review.skipped_files.length} dosya LLM'e gönderilmedi:</strong>{" "}
          {review.skipped_files.map((s) => `${s.path} (${s.reason})`).join(", ")}
        </div>
      )}

      <div className="filters">
        {(["all", "confirmed", "uncertain", "rejected", "unverified", "included"] as Filter[])
          .filter((f) => f === "all" || f === "included" || counts[f])
          .map((f) => (
            <button key={f} className={`chip ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>
              {FILTER_LABEL[f]} <span className="count">{counts[f] ?? 0}</span>
            </button>
          ))}
      </div>

      {visible.length === 0 ? (
        <div className="empty">{comments.length ? "Bu filtrede yorum yok." : "Hiç bulgu yok — temiz görünüyor. ✨"}</div>
      ) : (
        <div className="comment-list">
          {visible.map((c) => (
            <CommentCard key={c.id} comment={c} onChange={setComment} locked={locked} />
          ))}
        </div>
      )}

      {review.followups.length > 0 && <FollowupsCard followups={review.followups} />}

      <div className="card">
        <div className="card-head">
          <h3>GitHub'a gidecek özet ve karar</h3>
          <span className="muted small">{review.provider} {review.model} · {timeAgo(review.created_at)}</span>
        </div>
        <textarea className="input textarea" rows={5} value={summary} disabled={locked}
                  onChange={(e) => setSummary(e.target.value)} onBlur={saveMeta} />
        <div className="verdict-row">
          <label className="small muted" htmlFor="verdict">Karar</label>
          <select id="verdict" className="input select" value={verdict} disabled={locked}
                  onChange={(e) => setVerdict(e.target.value as Verdict)} onBlur={saveMeta}>
            {(["REQUEST_CHANGES", "COMMENT", "APPROVE"] as Verdict[]).map((v) => (
              <option key={v} value={v}>{verdictLabel(v)}</option>
            ))}
          </select>
          {review.recommended_verdict && review.recommended_verdict !== verdict && (
            <span className="small">
              Doğrulayıcı önerisi: <VerdictBadge verdict={review.recommended_verdict} />
            </span>
          )}
        </div>
      </div>

      {error && <ErrorBox error={error} />}

      <div className={`submit-bar ${review.status === "submitted" ? "is-done" : ""}`}>
        {review.status === "submitted" ? (
          <>
            <span>✓ GitHub'a gönderildi · {timeAgo(review.submitted_at)}</span>
            {review.github_review_url && (
              <a className="btn" href={review.github_review_url} target="_blank" rel="noreferrer">Review'u gör ↗</a>
            )}
          </>
        ) : confirming ? (
          <>
            <span>
              <strong>{included.length}</strong> yorum ({inline.length} satır içi, {included.length - inline.length} özet
              içinde) <VerdictBadge verdict={verdict} /> kararıyla <strong>{pr.author}</strong>'in PR'ına gönderilecek.
            </span>
            <div className="spacer" />
            <button className="btn btn-ghost" onClick={() => setConfirming(false)} disabled={submitting}>Vazgeç</button>
            <button className="btn btn-primary" onClick={submit} disabled={submitting}>
              {submitting ? <span className="spinner" /> : "Evet, gönder"}
            </button>
          </>
        ) : (
          <>
            <span className="muted">
              {included.length} / {comments.length} yorum seçili · reddedilenler varsayılan olarak hariç
            </span>
            <div className="spacer" />
            <button className="btn btn-primary" onClick={() => setConfirming(true)}>GitHub'a gönder…</button>
          </>
        )}
      </div>
    </div>
  );
}
