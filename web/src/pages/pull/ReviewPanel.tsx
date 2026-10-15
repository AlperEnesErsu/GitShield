import { PullDetail, Review, ReviewComment } from "../../api";
import { Loading } from "../../components/ui";
import { ReviewEditor } from "./ReviewEditor";
import { DiffView } from "./DiffView";

export function ReviewPanel({ review: r, loading, pr, tab, setReview, onSubmitted }: {
  review: Review | null;
  loading: boolean;
  pr: PullDetail;
  tab: "review" | "diff";
  setReview: (r: Review) => void;
  onSubmitted: () => void;
}) {
  if (loading) return <Loading />;

  const setComment = (c: ReviewComment) =>
    r && setReview({ ...r, comments: r.comments.map((x) => (x.id === c.id ? c : x)) });

  if (tab === "diff") {
    return <DiffView pr={pr} comments={r?.comments ?? []} onChange={setComment} locked={r?.status !== "ready"} />;
  }
  if (!r) {
    return (
      <div className="empty big">
        Review sonuçları burada görünecek. Yukarıdan <strong>İncelemeyi başlat</strong>.
      </div>
    );
  }
  if (r.status === "running") {
    return <div className="empty big">Yorumlar adımlar tamamlanınca burada listelenecek.</div>;
  }
  if (r.status === "failed") return null;

  return <ReviewEditor key={r.id} review={r} pr={pr} setReview={setReview}
                       setComment={setComment} onSubmitted={onSubmitted} />;
}
