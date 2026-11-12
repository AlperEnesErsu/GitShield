import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, ActivityDay, api } from "../api";
import { useAsync } from "../hooks";
import {
  BarRow,
  ChartCard,
  ColumnChart,
  CompositionBar,
  formatNumber,
  Kpi,
  Series,
  StackedBarList,
  TipRow,
  useTooltip,
} from "./charts";
import { CommitIcon, MergeIcon, PullIcon, PulseIcon } from "./icons";
import { ErrorBox } from "./ui";

const KINDS: Series[] = [
  { key: "commits", label: "Commit", color: "var(--series-1)" },
  { key: "prs", label: "Pull request", color: "var(--series-2)" },
  { key: "reviews", label: "Review", color: "var(--series-3)" },
  { key: "issues", label: "Issue", color: "var(--series-4)" },
];
const WEEKDAY_SERIES: Series[] = [{ key: "n", label: "Katkı", color: "var(--series-1)" }];
const WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"];
const WEEKDAY_TICKS = ["Pzt", "", "Çar", "", "Cum", "", ""];

const monthFmt = new Intl.DateTimeFormat("tr-TR", { month: "short" });
const dayFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", weekday: "long" });
const shortFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", year: "numeric" });
/** Calendar dates from the API carry no time zone; read them as local days. */
const localDate = (iso: string) => new Date(`${iso}T00:00:00`);

/** Year calendar: one column per week (Monday first), darker = more contributions that day. */
function ContributionCalendar({ days }: { days: ActivityDay[] }) {
  const tip = useTooltip();

  const weeks = useMemo(() => {
    const out: (ActivityDay | null)[][] = [];
    const pad = (localDate(days[0].date).getDay() + 6) % 7; // Monday = 0
    let week: (ActivityDay | null)[] = Array(pad).fill(null);
    for (const d of days) {
      week.push(d);
      if (week.length === 7) {
        out.push(week);
        week = [];
      }
    }
    if (week.length) out.push([...week, ...Array(7 - week.length).fill(null)]);
    return out;
  }, [days]);

  // Quartiles of the active days, so one unusually busy day does not flatten the rest.
  const cuts = useMemo(() => {
    const active = days.map((d) => d.count).filter((n) => n > 0).sort((a, b) => a - b);
    const at = (q: number) => active[Math.min(active.length - 1, Math.floor(active.length * q))] ?? 1;
    return [at(0.25), at(0.5), at(0.75)];
  }, [days]);
  const level = (n: number) => (n === 0 ? 0 : n <= cuts[0] ? 1 : n <= cuts[1] ? 2 : n <= cuts[2] ? 3 : 4);

  return (
    <div className="viz">
      <div className="cal" role="img"
           aria-label={`Son bir yılın katkı takvimi: ${days.filter((d) => d.count).length} aktif gün`}>
        <div className="cal-inner" style={{ ["--weeks" as string]: weeks.length }}>
          <span />
          <div className="cal-months" aria-hidden>
            {weeks.map((w, i) => {
              const first = w.find(Boolean);
              const show = first && i > 0 && localDate(first.date).getDate() <= 7;
              return <span key={i}>{show ? monthFmt.format(localDate(first.date)) : ""}</span>;
            })}
          </div>
          <div className="cal-days" aria-hidden>
            {WEEKDAY_TICKS.map((t, i) => <span key={i}>{t}</span>)}
          </div>
          <div className="cal-grid" onMouseLeave={tip.hide}>
            {weeks.map((w, i) => (
              <div key={i} className="cal-week">
                {w.map((d, j) => d ? (
                  <span key={j} className={`cal-cell cal-${level(d.count)}`}
                        onMouseMove={(e) => tip.show(e, (
                          <>
                            <div className="tip-title">{dayFmt.format(localDate(d.date))}</div>
                            <TipRow color="var(--series-1)" label="Katkı" value={formatNumber(d.count)} />
                          </>
                        ))} />
                ) : <span key={j} className="cal-cell cal-none" />)}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="cal-legend" aria-hidden>
        <span>az</span>
        {[0, 1, 2, 3, 4].map((l) => <span key={l} className={`cal-cell cal-${l}`} />)}
        <span>çok</span>
      </div>
      {tip.node}
    </div>
  );
}

/** The signed-in user's own GitHub activity across every repository, for the last year. */
export function ActivityPanel() {
  const navigate = useNavigate();
  const activity = useAsync<Activity>(() => api.activity(), [], "activity");
  const a = activity.data;

  const repoRows: BarRow[] = useMemo(() => (a?.repos ?? []).map((r) => {
    const [owner, name] = r.repo.split("/");
    return {
      key: r.repo,
      tipTitle: r.repo,
      label: <><span className="muted">{owner}/</span>{name}</>,
      values: { commits: r.commits, prs: r.prs, reviews: r.reviews, issues: r.issues },
      onClick: () => navigate(`/r/${r.repo}`),
    };
  }), [a, navigate]);

  if (activity.error && !a) return <ErrorBox error={activity.error} onRetry={activity.reload} />;
  if (!a) return <div className="skeleton-grid"><div /><div /><div /><div /></div>;
  if (!a.days.length) return null;

  const share = Math.round((a.active_days / a.days.length) * 100);

  return (
    <>
      <div className="section-head">
        <div>
          <h2>GitHub aktiviten</h2>
          <p className="muted small">
            Tüm repolardaki commit, PR, review ve issue katkıların · {shortFmt.format(localDate(a.from!))} –{" "}
            {shortFmt.format(localDate(a.to!))}
          </p>
        </div>
      </div>

      <div className="kpis">
        <Kpi icon={<PulseIcon />} label="Toplam katkı" value={formatNumber(a.total)} tone="accent"
             sub={`${a.repo_count} repoda`} />
        <Kpi icon={<CommitIcon />} label="Güncel seri" value={`${a.streak.current} gün`}
             sub={`en uzun ${a.streak.longest} gün`} />
        <Kpi icon={<MergeIcon />} label="Aktif gün" value={a.active_days}
             sub={`${a.days.length} günde · %${share}`} />
        <Kpi icon={<PullIcon />} label="En yoğun gün" value={a.best_day ? formatNumber(a.best_day.count) : "—"}
             sub={a.best_day ? shortFmt.format(localDate(a.best_day.date)) : "katkı yok"} />
      </div>

      <div className="chart-grid">
        <ChartCard title="Katkı takvimi" subtitle="Günlük katkı sayısı · son bir yıl" className="span-all">
          <ContributionCalendar days={a.days} />
        </ChartCard>
        <ChartCard title="Haftalık aktivite" subtitle="Hafta başına toplam katkı" className="span-all">
          <ColumnChart unit="katkı"
                       points={a.weeks.map((w) => ({ date: localDate(w.week), value: w.count }))} />
        </ChartCard>
        <ChartCard title="Katkı türleri" subtitle="Son bir yıl" className="span-2">
          <CompositionBar unit={formatNumber} parts={KINDS.map((k) => ({
            key: k.key, label: k.label, color: k.color, value: a.counts[k.key as keyof Activity["counts"]],
          }))} />
          {a.counts.restricted > 0 && (
            <p className="small muted">
              {formatNumber(a.counts.restricted)} katkı bu token'ın göremediği repolarda.
            </p>
          )}
        </ChartCard>
        <ChartCard title="Haftanın günleri" subtitle="Güne göre toplam katkı" className="span-2">
          <StackedBarList series={WEEKDAY_SERIES} rows={a.by_weekday.map((n, i) => ({
            key: WEEKDAYS[i], label: WEEKDAYS[i], values: { n },
          }))} />
        </ChartCard>
        <ChartCard title="En çok katkı verdiğin repolar" className="span-all"
                   subtitle={`Türe göre katkı · ${a.repo_count} repodan ilk ${a.repos.length}`}>
          <StackedBarList rows={repoRows} series={KINDS} empty="Bu dönemde katkı yok." />
        </ChartCard>
      </div>
    </>
  );
}
