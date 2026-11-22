import { Review } from "../../api";
import { ChartCard, Series, StackedBarList } from "../../components/charts";

const FUNNEL_SERIES: Series[] = [{ key: "n", label: "Yorum", color: "var(--series-1)" }];

/** How many comments were produced, survived verification and will be sent. */
export function FunnelCard({ review }: { review: Review }) {
  const comments = review.comments;
  const included = comments.filter((c) => c.included);
  // Findings the repo's own .gitshieldignore / baseline accepted; they never became comments.
  const accepted = (review.stats.ignored_findings ?? 0) + (review.stats.baselined_findings ?? 0);
  return (
    <ChartCard title="Yorum hunisi"
               subtitle={`${review.stats.scanner_findings ?? 0} tarayıcı bulgusu · ${review.stats.llm_comments ?? 0} AI yorumu`
                         + (accepted ? ` · ${accepted} repo ayarıyla atlandı` : "")}>
      <StackedBarList series={FUNNEL_SERIES} empty="Hiç yorum üretilmedi — PR temiz görünüyor." rows={
        comments.length ? [
          { key: "Üretilen", label: "Üretilen", values: { n: comments.length } },
          { key: "Doğrulamayı geçen", label: "Doğrulamayı geçen",
            values: { n: comments.filter((c) => c.verification !== "rejected").length } },
          { key: "Gönderilecek", label: "Gönderilecek", values: { n: included.length } },
          { key: "Satır içi", label: "Satır içi", values: { n: included.filter((c) => c.in_diff).length } },
        ] : []} />
      {review.verifier_notes && <p className="small verifier-note">{review.verifier_notes}</p>}
    </ChartCard>
  );
}
