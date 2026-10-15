import { Followup } from "../../api";
import { ChartCard, CompositionBar } from "../../components/charts";
import { Badge, SeverityBadge } from "../../components/ui";

const FOLLOWUP: Record<Followup["status"], [string, string, string]> = {
  fixed: ["success", "✓", "Düzeltildi"],
  still_open: ["high", "●", "Hâlâ açık"],
  unclear: ["medium", "?", "Belirsiz"],
};

export function FollowupsCard({ followups }: { followups: Followup[] }) {
  const count = (k: Followup["status"]) => followups.filter((f) => f.status === k).length;
  return (
    <ChartCard title="Önceki review'daki yorumlar"
               subtitle="Yeni commit'ler önceki yorumları çözdü mü? Dokunulmayan satırlar kesin olarak açık sayılır.">
      <CompositionBar parts={(["fixed", "unclear", "still_open"] as const).map((k, i) => ({
        key: k, label: FOLLOWUP[k][2], value: count(k), color: `var(--series-${[3, 1, 2][i]})`,
      }))} unit={(v) => `${v} yorum`} />
      <ul className="followups">
        {followups.map((f) => {
          const [tone, icon, label] = FOLLOWUP[f.status];
          return (
            <li key={f.id}>
              <Badge tone={tone}>{icon} {label}</Badge>
              <div className="followup-main">
                <div><SeverityBadge severity={f.severity} /> <strong>{f.title}</strong></div>
                <div className="muted small">
                  <span className="mono">{f.path}:{f.new_line ?? f.old_line}</span> · {f.note}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </ChartCard>
  );
}
