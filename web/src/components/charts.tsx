import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";

/* ------------------------------------------------------------------ */
/* Tooltip                                                             */
/* ------------------------------------------------------------------ */

interface TipState {
  x: number;
  y: number;
  content: ReactNode;
}

function useTooltip() {
  const [tip, setTip] = useState<TipState | null>(null);
  const show = (e: { clientX: number; clientY: number }, content: ReactNode) =>
    setTip({ x: e.clientX, y: e.clientY, content });
  const hide = () => setTip(null);
  const node = tip && <Tooltip {...tip} />;
  return { show, hide, node };
}

function Tooltip({ x, y, content }: TipState) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x + 14, top: y + 14 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const left = x + 14 + width > window.innerWidth - 8 ? x - width - 14 : x + 14;
    const top = y + 14 + height > window.innerHeight - 8 ? y - height - 14 : y + 14;
    setPos({ left: Math.max(8, left), top: Math.max(8, top) });
  }, [x, y]);
  return (
    <div ref={ref} className="viz-tooltip" style={pos} role="tooltip">
      {content}
    </div>
  );
}

export function TipRow({ color, label, value }: { color?: string; label: ReactNode; value: ReactNode }) {
  return (
    <div className="tip-row">
      {color && <span className="swatch" style={{ background: color }} />}
      <span className="tip-label">{label}</span>
      <span className="tip-value">{value}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Legend                                                              */
/* ------------------------------------------------------------------ */

export interface Series {
  key: string;
  label: string;
  color: string; // CSS color or var(--series-n)
}

export function Legend({ series }: { series: Series[] }) {
  return (
    <ul className="viz-legend">
      {series.map((s) => (
        <li key={s.key}>
          <span className="swatch" style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

const fmt = new Intl.NumberFormat("tr-TR");
export const formatNumber = (n: number) => fmt.format(n);
export function formatPercent(share: number) {
  if (share === 0) return "0%";
  if (share < 0.001) return "<0.1%";
  return `${share >= 0.1 ? Math.round(share * 100) : (share * 100).toFixed(1)}%`;
}

/* ------------------------------------------------------------------ */
/* Stacked horizontal bar list (ranking with composition)              */
/* ------------------------------------------------------------------ */

export interface BarRow {
  key: string;
  label: ReactNode;
  tipTitle?: string;
  values: Record<string, number>;
  onClick?: () => void;
}

export function StackedBarList({ rows, series, empty, format = formatNumber }: {
  rows: BarRow[];
  series: Series[];
  empty?: string;
  /** Formats the value column and tooltip values (defaults to a localized integer). */
  format?: (v: number) => string;
}) {
  const tip = useTooltip();
  const total = (r: BarRow) => series.reduce((n, s) => n + (r.values[s.key] ?? 0), 0);
  const max = Math.max(1, ...rows.map(total));
  if (!rows.length) return <div className="viz-empty">{empty ?? "Veri yok"}</div>;

  return (
    <div className="viz">
      {series.length > 1 && <Legend series={series} />}
      <div className="barlist">
        {rows.map((r) => {
          const t = total(r);
          const content = (
            <>
              <div className="tip-title">{r.tipTitle ?? r.key}</div>
              {series.map((s) => (
                <TipRow key={s.key} color={s.color} label={s.label} value={format(r.values[s.key] ?? 0)} />
              ))}
            </>
          );
          return (
            <div key={r.key} className={`barlist-row ${r.onClick ? "clickable" : ""}`} onClick={r.onClick}
                 onMouseMove={(e) => tip.show(e, content)} onMouseLeave={tip.hide}>
              <div className="barlist-label">{r.label}</div>
              <div className="barlist-track">
                <div className="barlist-bar" style={{ width: `${(t / max) * 100}%` }}>
                  {series.map((s) => {
                    const v = r.values[s.key] ?? 0;
                    return v > 0 ? (
                      <span key={s.key} className="seg" style={{ flexGrow: v, background: s.color }} />
                    ) : null;
                  })}
                </div>
              </div>
              <div className="barlist-value">{format(t)}</div>
            </div>
          );
        })}
      </div>
      {tip.node}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Composition bar (part-to-whole) with legend                         */
/* ------------------------------------------------------------------ */

export interface Part {
  key: string;
  label: string;
  value: number;
  color: string;
}

export function CompositionBar({ parts, unit, size = "md", legend = true }: {
  parts: Part[];
  unit?: (v: number) => string;
  size?: "sm" | "md";
  legend?: boolean;
}) {
  const tip = useTooltip();
  const total = parts.reduce((n, p) => n + p.value, 0);
  if (!total) return <div className="viz-empty">Veri yok</div>;
  const visible = parts.filter((p) => p.value > 0);

  return (
    <div className="viz">
      <div className={`composition composition-${size}`}>
        {visible.map((p) => (
          <span key={p.key} className="seg" style={{ flexGrow: p.value, background: p.color }}
                onMouseMove={(e) =>
                  tip.show(e, <TipRow color={p.color} label={p.label}
                                      value={`${formatPercent(p.value / total)}${unit ? ` · ${unit(p.value)}` : ""}`} />)}
                onMouseLeave={tip.hide} />
        ))}
      </div>
      {legend && (
        <ul className="viz-legend viz-legend-values">
          {visible.map((p) => (
            <li key={p.key}>
              <span className="swatch" style={{ background: p.color }} />
              <span>{p.label}</span>
              <span className="legend-value">{formatPercent(p.value / total)}</span>
            </li>
          ))}
        </ul>
      )}
      {tip.node}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Column chart (time series, single series)                           */
/* ------------------------------------------------------------------ */

export interface Point {
  date: Date;
  value: number;
}

const monthFmt = new Intl.DateTimeFormat("tr-TR", { month: "short" });
const dayFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", year: "numeric" });

function niceMax(v: number) {
  if (v <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * pow * 4 >= v) ?? 10;
  return step * pow * 4;
}

export function ColumnChart({ points, height = 180, unit = "commit", color = "var(--series-1)" }: {
  points: Point[];
  height?: number;
  unit?: string;
  color?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [active, setActive] = useState<number | null>(null);
  const tip = useTooltip();

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pad = { top: 8, right: 4, bottom: 22, left: 32 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(0, ...points.map((p) => p.value)));
  const ticks = [0, max / 2, max];
  const slot = innerW / Math.max(1, points.length);
  const barW = Math.min(36, Math.max(2, slot - 2)); // 2px surface gap; capped so sparse series stay readable
  const y = (v: number) => pad.top + innerH - (v / max) * innerH;

  const monthTicks = points
    .map((p, i) => ({ i, p }))
    .filter(({ i, p }) => i > 0 && p.date.getMonth() !== points[i - 1].date.getMonth())
    .filter((_, k, arr) => arr.length <= 8 || k % 2 === 0);

  return (
    <div className="viz" ref={wrap}>
      <svg width={width} height={height} className="column-chart" onMouseLeave={() => { setActive(null); tip.hide(); }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)}
                  className={t === 0 ? "axis-line" : "grid-line"} />
            <text x={pad.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="axis-text">
              {formatNumber(t)}
            </text>
          </g>
        ))}
        {points.map((p, i) => {
          const h = Math.max(p.value > 0 ? 2 : 0, innerH - (y(p.value) - pad.top));
          const x = pad.left + i * slot + (slot - barW) / 2;
          const r = Math.min(3, barW / 2, h);
          return (
            <g key={i}>
              {h > 0 && (
                <path
                  d={`M${x},${pad.top + innerH} v${-(h - r)} q0,${-r} ${r},${-r} h${barW - 2 * r} q${r},0 ${r},${r} v${h - r} z`}
                  fill={color}
                  opacity={active === null || active === i ? 1 : 0.45}
                />
              )}
              <rect x={pad.left + i * slot} y={pad.top} width={slot} height={innerH} fill="transparent"
                    onMouseMove={(e) => {
                      setActive(i);
                      tip.show(e, (
                        <>
                          <div className="tip-title">{dayFmt.format(p.date)} haftası</div>
                          <TipRow color={color} label={unit} value={formatNumber(p.value)} />
                        </>
                      ));
                    }} />
            </g>
          );
        })}
        {monthTicks.map(({ i, p }) => (
          <text key={i} x={pad.left + i * slot} y={height - 6} className="axis-text">
            {monthFmt.format(p.date)}
          </text>
        ))}
      </svg>
      {tip.node}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* KPI tile                                                            */
/* ------------------------------------------------------------------ */

export function Kpi({ icon, label, value, sub, tone }: {
  icon?: ReactNode;
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "accent" | "warn";
}) {
  return (
    <div className={`kpi ${tone ? `kpi-${tone}` : ""}`}>
      <div className="kpi-head">
        {icon && <span className="kpi-icon">{icon}</span>}
        <span className="kpi-label">{label}</span>
      </div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function ChartCard({ title, subtitle, action, children, className }: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`chart-card ${className ?? ""}`}>
      <header className="chart-card-head">
        <div>
          <h3>{title}</h3>
          {subtitle && <p className="chart-card-sub">{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}
