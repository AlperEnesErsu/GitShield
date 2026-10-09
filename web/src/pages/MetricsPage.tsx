import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ChartCard, ColumnChart, formatNumber, Kpi, Series, StackedBarList } from "../components/charts";
import { Column, DataTable } from "../components/DataTable";
import { DraftIcon, MergeIcon, PulseIcon, PullIcon, ShieldIcon } from "../components/icons";
import { ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../hooks";
import type { Metrics, StalePull } from "../api";

const HOURS: Series[] = [{ key: "h", label: "Medyan süre", color: "var(--series-1)" }];
const COUNT: Series[] = [{ key: "n", label: "PR", color: "var(--series-2)" }];

export function formatHours(h: number | null | undefined): string {
  if (h === null || h === undefined) return "—";
  if (h < 1) return `${Math.round(h * 60)} dk`;
  if (h < 48) return `${h < 10 ? h.toFixed(1) : Math.round(h)} sa`;
  return `${(h / 24).toFixed(1)} gün`;
}

function formatSeconds(s: number | null): string {
  if (s === null) return "—";
  return s < 90 ? `${Math.round(s)} sn` : `${(s / 60).toFixed(1)} dk`;
}

function Segmented<T extends number>({ value, options, onChange, label }: {
  value: T;
  options: [T, string][];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="view-toggle" role="radiogroup" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} role="radio" aria-checked={value === v} className={value === v ? "on" : ""}
                onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  );
}

const STALE_COLUMNS: Column<StalePull>[] = [
  { key: "age", header: "Bekliyor", sortValue: (r) => r.age_days, width: "110px",
    render: (r) => <span className={`num strong ${r.age_days > 14 ? "del" : ""}`}>{r.age_days.toFixed(1)} gün</span> },
  { key: "title", header: "PR", sortValue: (r) => r.title.toLowerCase(),
    render: (r) => (
      <div className="cell-main">
        <div className="cell-sub">{r.repo} <span className="mono">#{r.number}</span> · {r.author}</div>
        <Link to={`/r/${r.repo}/pull/${r.number}`} onClick={(e) => e.stopPropagation()}>{r.title}</Link>
      </div>
    ) },
];

export function MetricsPage() {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [sla, setSla] = useState<1 | 3 | 7>(3);
  const metrics = useAsync<Metrics>(() => api.metrics(days, sla), [days, sla]);
  const m = metrics.data;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Metrikler</p>
          <h1>Bekleme süreleri</h1>
          <p className="muted">PR'lar ne kadar bekliyor, ne kadar sürede birleşiyor ve GitShield ne kadar hızlı.</p>
        </div>
        <div className="head-actions">
          <Segmented label="Dönem" value={days} onChange={setDays}
                     options={[[7, "7 gün"], [30, "30 gün"], [90, "90 gün"]]} />
          <Segmented label="SLA" value={sla} onChange={setSla}
                     options={[[1, "SLA 1g"], [3, "SLA 3g"], [7, "SLA 7g"]]} />
        </div>
      </div>

      {metrics.error ? <ErrorBox error={metrics.error} onRetry={metrics.reload} />
        : !m ? <Loading label={`${days} günlük veri toplanıyor`} />
        : (
          <>
            <div className="kpis kpis-6">
              <Kpi icon={<MergeIcon />} label="Medyan merge süresi" value={formatHours(m.merge.median_hours)} tone="accent"
                   sub={`${m.merge.count} merge · p75 ${formatHours(m.merge.p75_hours)}`} />
              <Kpi icon={<PullIcon />} label="Açık PR medyan yaşı"
                   value={m.open.median_age_days === null ? "—" : `${m.open.median_age_days.toFixed(1)} gün`}
                   sub={`${m.open.count} açık PR (taslaklar hariç)`} />
              <Kpi icon={<DraftIcon />} label={`SLA'yı aşan (> ${sla} gün)`} value={m.open.over_sla.length}
                   tone={m.open.over_sla.length ? "warn" : undefined} sub="aşağıda listelendi" />
              <Kpi icon={<PulseIcon />} label="AI inceleme süresi" value={formatSeconds(m.gitshield.median_ai_seconds)}
                   sub="medyan · tarama + review + doğrulama" />
              <Kpi icon={<ShieldIcon />} label="Senin onay gecikmen"
                   value={m.gitshield.median_approval_minutes === null ? "—" : formatHours(m.gitshield.median_approval_minutes / 60)}
                   sub={`${m.gitshield.submitted} gönderildi · ${m.gitshield.awaiting} bekliyor`} />
              <Kpi label="GitShield review" value={m.gitshield.reviews}
                   sub={m.gitshield.failed ? `${m.gitshield.failed} hata` : "hata yok"} />
            </div>

            <div className="chart-grid">
              <ChartCard title="Haftalık merge" subtitle={`Son ${days} gün · birleştirilen PR sayısı`} className="span-2">
                {m.merge.weekly.length ? (
                  <ColumnChart unit="merge" color="var(--series-2)"
                               points={m.merge.weekly.map((w) => ({ date: new Date(w.week), value: w.merged }))} />
                ) : <div className="viz-empty">Bu dönemde merge yok.</div>}
              </ChartCard>
              <ChartCard title="Repo bazında merge süresi" subtitle="Medyan açılış → merge, en yavaş üstte" className="span-2">
                <StackedBarList series={HOURS} empty="Bu dönemde merge yok." format={formatHours}
                                rows={m.merge.by_repo.slice(0, 8).map((r) => ({
                                  key: r.repo, tipTitle: `${r.repo} · ${r.count} merge`,
                                  label: r.repo.split("/")[1], values: { h: r.median_hours ?? 0 },
                                }))} />
              </ChartCard>
              <ChartCard title="Açık PR yaşları" subtitle="Taslaklar hariç" className="span-2">
                <StackedBarList series={COUNT} rows={m.open.buckets.map((b) => ({
                  key: b.label, label: b.label, values: { n: b.count },
                }))} />
              </ChartCard>
              <ChartCard title="Haftalık GitShield review" subtitle={`Son ${days} gün`} className="span-2">
                {m.gitshield.weekly.length ? (
                  <ColumnChart unit="review"
                               points={m.gitshield.weekly.map((w) => ({ date: new Date(w.week), value: w.reviews }))} />
                ) : <div className="viz-empty">Bu dönemde review yok.</div>}
              </ChartCard>
            </div>

            <div className="section-head">
              <h2>SLA'yı aşan PR'lar <span className="count">{m.open.over_sla.length}</span></h2>
              <span className="muted small">{sla} günden uzun bekleyen, taslak olmayan açık PR'lar</span>
            </div>
            <DataTable rows={m.open.over_sla} columns={STALE_COLUMNS} rowKey={(r) => `${r.repo}#${r.number}`}
                       initialSort={{ key: "age", dir: "desc" }} empty={`${sla} günden uzun bekleyen PR yok. 🎉`} />
            <p className="small muted">
              {m.repos_checked} aktif repo incelendi (en fazla 12, son push'a göre){m.errors.length > 0 &&
                ` · okunamayan: ${m.errors.map((e) => e.repo).join(", ")}`} · {formatNumber(m.merge.count)} merge
            </p>
          </>
        )}
    </div>
  );
}
