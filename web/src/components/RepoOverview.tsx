import { useMemo } from "react";
import { PullSummary, RepoOverview } from "../api";
import { formatBytes, langColor } from "../pages/ReposPage";
import {
  BarRow,
  ChartCard,
  ColumnChart,
  CompositionBar,
  formatNumber,
  Kpi,
  Series,
  StackedBarList,
} from "./charts";
import { CommitIcon, DraftIcon, ForkIcon, IssueIcon, MergeIcon, PulseIcon, PullIcon, StarIcon } from "./icons";
import { ErrorBox } from "./ui";

const AGE_SERIES: Series[] = [
  { key: "ready", label: "Hazır", color: "var(--series-1)" },
  { key: "draft", label: "Taslak", color: "var(--series-2)" },
];
const AGE_BUCKETS: [string, number][] = [
  ["< 1 gün", 1],
  ["1–7 gün", 7],
  ["1–4 hafta", 28],
  ["1–3 ay", 90],
  ["3 ay +", Infinity],
];

export function RepoOverviewSection({ overview, error, pulls, onRetry }: {
  overview: RepoOverview | undefined;
  error: string | null;
  pulls: PullSummary[] | undefined;
  onRetry: () => void;
}) {
  const weeks = useMemo(() => {
    const data = overview?.participation?.all;
    if (!data) return null;
    const now = new Date();
    // GitHub's last element is the current week; walk back one week per element.
    return data.map((value, i) => ({
      value,
      date: new Date(now.getTime() - (data.length - 1 - i) * 7 * 86400000),
    }));
  }, [overview]);

  const ages: BarRow[] = useMemo(() => {
    const rows = AGE_BUCKETS.map(([label]) => ({ key: label, label, values: { ready: 0, draft: 0 } }));
    const now = Date.now();
    for (const p of pulls ?? []) {
      const days = (now - new Date(p.created_at).getTime()) / 86400000;
      const i = AGE_BUCKETS.findIndex(([, limit]) => days <= limit);
      rows[i].values[p.draft ? "draft" : "ready"]++;
    }
    return rows;
  }, [pulls]);

  if (error) return <ErrorBox error={error} onRetry={onRetry} />;
  if (!overview) return <div className="skeleton-grid"><div /><div /><div /><div /></div>;

  const o = overview;
  const recent = weeks ? weeks.slice(-4).reduce((n, w) => n + w.value, 0) : null;
  const yearTotal = weeks ? weeks.reduce((n, w) => n + w.value, 0) : null;

  return (
    <>
      <div className="kpis kpis-6">
        <Kpi icon={<CommitIcon />} label="Commit" value={o.commits !== null ? formatNumber(o.commits) : "—"}
             sub={o.default_branch ? `${o.default_branch} dalında` : undefined} />
        <Kpi icon={<PulseIcon />} label="Son 4 hafta" value={recent ?? "—"} tone="accent"
             sub={yearTotal !== null ? `yılda ${formatNumber(yearTotal)} commit` : "hesaplanıyor"} />
        <Kpi icon={<PullIcon />} label="Açık PR" value={o.pulls.open} sub={`${formatNumber(o.pulls.merged)} merge`} />
        <Kpi icon={<IssueIcon />} label="Açık issue" value={o.issues.open} sub={`${formatNumber(o.issues.closed)} kapandı`} />
        <Kpi icon={<DraftIcon />} label="Taslak issue" value={o.gitshield.draft_issues}
             tone={o.gitshield.draft_issues ? "warn" : undefined} sub={`${o.gitshield.reviews} review`} />
        <Kpi icon={<StarIcon />} label="Yıldız" value={formatNumber(o.stars)}
             sub={<><ForkIcon size={12} /> {o.forks} fork · {formatBytes(o.disk_kb * 1024)}</>} />
      </div>

      <div className="chart-grid">
        <ChartCard title="Commit aktivitesi" subtitle="Son 52 hafta · varsayılan dal" className="span-2">
          {weeks ? (
            <ColumnChart points={weeks} />
          ) : (
            <div className="viz-empty">GitHub istatistikleri hazırlıyor; birkaç saniye sonra yenileyin.</div>
          )}
        </ChartCard>
        <ChartCard title="Diller" subtitle={`${o.languages.length} dil`}>
          <CompositionBar
            parts={o.languages.map((l) => ({ key: l.name, label: l.name, value: l.bytes, color: langColor(l) }))}
            unit={formatBytes}
          />
        </ChartCard>
        <ChartCard title="Pull request durumu" subtitle={`Toplam ${formatNumber(o.pulls.open + o.pulls.merged + o.pulls.closed)} PR`}>
          <CompositionBar parts={[
            { key: "merged", label: "Merge edildi", value: o.pulls.merged, color: "var(--series-1)" },
            { key: "open", label: "Açık", value: o.pulls.open, color: "var(--series-2)" },
            { key: "closed", label: "Kapatıldı", value: o.pulls.closed, color: "var(--series-3)" },
          ]} unit={(v) => `${formatNumber(v)} PR`} />
          <div className="mini-meta">
            <MergeIcon size={14} />
            Merge oranı{" "}
            <strong>
              {o.pulls.merged + o.pulls.closed
                ? `${Math.round((o.pulls.merged / (o.pulls.merged + o.pulls.closed)) * 100)}%`
                : "—"}
            </strong>
          </div>
        </ChartCard>
        <ChartCard title="Açık PR yaşı" subtitle="Açılış tarihinden bu yana" className="span-2">
          <StackedBarList rows={ages} series={AGE_SERIES} />
        </ChartCard>
        <ChartCard title="Issue durumu" subtitle={`Toplam ${formatNumber(o.issues.open + o.issues.closed)} issue`}>
          <CompositionBar parts={[
            { key: "closed", label: "Kapandı", value: o.issues.closed, color: "var(--series-1)" },
            { key: "open", label: "Açık", value: o.issues.open, color: "var(--series-2)" },
          ]} unit={(v) => `${formatNumber(v)} issue`} />
          <div className="mini-meta">
            <IssueIcon size={14} />
            Kapanma oranı{" "}
            <strong>
              {o.issues.open + o.issues.closed
                ? `${Math.round((o.issues.closed / (o.issues.open + o.issues.closed)) * 100)}%`
                : "—"}
            </strong>
          </div>
        </ChartCard>
        <ChartCard title="GitShield" subtitle="Bu repodaki inceleme geçmişi">
          <div className="mini-stats">
            <div><strong>{o.gitshield.reviews}</strong><span>review</span></div>
            <div className="ok"><strong>{o.gitshield.submitted}</strong><span>GitHub'a gönderildi</span></div>
            <div><strong>{o.gitshield.draft_issues}</strong><span>taslak issue</span></div>
            <div><strong>{pulls ? pulls.filter((p) => p.review).length : "—"}</strong><span>incelenen açık PR</span></div>
          </div>
        </ChartCard>
      </div>
    </>
  );
}
