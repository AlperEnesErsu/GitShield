import { ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Badge } from "../api";
import { ErrorBox, Loading } from "../components/ui";
import { useGamification } from "../gamification";

const dayFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", weekday: "long" });
const monthFmt = new Intl.DateTimeFormat("tr-TR", { month: "short" });
const earnedFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", year: "numeric" });

function Ring({ value, size = 132, stroke = 10, children, tone = "accent" }: {
  value: number;
  size?: number;
  stroke?: number;
  children: ReactNode;
  tone?: "accent" | "flame";
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className={`ring ring-${tone}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} className="ring-track" />
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} className="ring-value"
                strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(1, value))} />
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  );
}

function Heatmap({ cells, goal }: { cells: { date: string; count: number }[]; goal: number }) {
  // Columns are weeks (Mon→Sun), like GitHub's contribution graph.
  const weeks = useMemo(() => {
    const out: ({ date: string; count: number } | null)[][] = [];
    const first = new Date(cells[0].date);
    const pad = (first.getDay() + 6) % 7; // Monday = 0
    let week: ({ date: string; count: number } | null)[] = Array(pad).fill(null);
    for (const c of cells) {
      week.push(c);
      if (week.length === 7) {
        out.push(week);
        week = [];
      }
    }
    if (week.length) out.push([...week, ...Array(7 - week.length).fill(null)]);
    return out;
  }, [cells]);

  const level = (n: number) => (n === 0 ? 0 : n >= goal ? 4 : Math.min(3, Math.ceil((n / goal) * 3)));

  return (
    <div className="heatmap" role="img" aria-label="Son 26 haftanın review takvimi">
      <div className="heatmap-months" aria-hidden>
        {weeks.map((w, i) => {
          const firstDay = w.find(Boolean);
          const show = firstDay && (i === 0 || new Date(firstDay.date).getDate() <= 7);
          return <span key={i}>{show ? monthFmt.format(new Date(firstDay!.date)) : ""}</span>;
        })}
      </div>
      <div className="heatmap-grid">
        {weeks.map((w, i) => (
          <div key={i} className="heatmap-week">
            {w.map((c, j) => c ? (
              <span key={j} className={`hm hm-${level(c.count)}`}
                    title={`${dayFmt.format(new Date(c.date))}: ${c.count} review`} />
            ) : <span key={j} className="hm hm-empty" />)}
          </div>
        ))}
      </div>
      <div className="heatmap-legend" aria-hidden>
        <span>az</span>{[0, 1, 2, 3, 4].map((l) => <span key={l} className={`hm hm-${l}`} />)}<span>hedef</span>
      </div>
    </div>
  );
}

function BadgeCard({ badge }: { badge: Badge }) {
  const pct = Math.round((badge.value / badge.target) * 100);
  return (
    <div className={`badge-card tier-${badge.tier} ${badge.earned ? "earned" : "locked"}`}>
      <div className="badge-medal" aria-hidden>{badge.icon}</div>
      <div className="badge-name">{badge.name}</div>
      <div className="badge-desc">{badge.description}</div>
      {badge.earned ? (
        <div className="badge-meta">✓ {badge.earned_at ? earnedFmt.format(new Date(badge.earned_at)) : "kazanıldı"}</div>
      ) : (
        <div className="badge-progress" title={`${badge.value} / ${badge.target}`}>
          <span style={{ width: `${pct}%` }} />
          <em>{badge.value}/{badge.target}</em>
        </div>
      )}
    </div>
  );
}

export function AchievementsPage() {
  const { data, setData } = useGamification();
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "earned" | "locked">("all");

  if (!data) return <div className="page"><Loading label="İlerleme yükleniyor" /></div>;
  const { streak } = data;
  const earned = data.badges.filter((b) => b.earned).length;
  const badges = data.badges
    .filter((b) => filter === "all" || (filter === "earned" ? b.earned : !b.earned))
    // Earned first; among locked ones the closest to completion first.
    .sort((a, b) => Number(b.earned) - Number(a.earned) || b.value / b.target - a.value / a.target);

  const changeGoal = async (delta: number) => {
    setError(null);
    try {
      setData(await api.setDailyGoal(Math.max(1, Math.min(30, streak.goal + delta))));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const goalPct = streak.today / streak.goal;
  const xpInLevel = data.xp - data.level_floor;
  const xpNeeded = data.next_level_xp - data.level_floor;

  return (
    <div className="page achievements">
      <div className="page-head">
        <div>
          <p className="eyebrow">Başarılar</p>
          <h1>{data.title} · Seviye {data.level}</h1>
          <p className="muted">Her gönderilen review, yakalanan sorun ve açılan düzeltme seni bir adım ileri taşır.</p>
        </div>
        <Link to="/inbox" className="btn btn-primary">Bekleyenlere git →</Link>
      </div>
      {error && <ErrorBox error={error} />}

      <div className="hero-grid">
        <section className="hero-card level-card">
          <Ring value={data.progress}>
            <span className="ring-big">{data.level}</span>
            <span className="ring-small">seviye</span>
          </Ring>
          <div className="hero-text">
            <div className="hero-title">{data.title}</div>
            <div className="xp-bar" role="progressbar" aria-valuemin={0} aria-valuemax={xpNeeded} aria-valuenow={xpInLevel}>
              <span style={{ width: `${data.progress * 100}%` }} />
            </div>
            <div className="muted small">{data.xp} XP · sonraki seviyeye {data.next_level_xp - data.xp} XP</div>
            <ul className="xp-rules small muted">
              <li>Review gönder <strong>+10</strong></li>
              <li>Yakalanan her sorun <strong>+5</strong> (en fazla +25)</li>
              <li>Kritik / yüksek bulgu <strong>+20 / +10</strong></li>
              <li>1 saat içinde onay <strong>+5</strong> · düzeltme PR'ı <strong>+15</strong></li>
            </ul>
          </div>
        </section>

        <section className={`hero-card streak-card ${streak.at_risk ? "at-risk" : ""}`}>
          <Ring value={goalPct} tone="flame">
            <span className="ring-big">{streak.today}<small>/{streak.goal}</small></span>
            <span className="ring-small">bugün</span>
          </Ring>
          <div className="hero-text">
            <div className="streak-number"><span aria-hidden>🔥</span> {streak.current} gün</div>
            <div className="muted small">En uzun seri: {streak.best} gün</div>
            <div className={`streak-hint ${streak.at_risk ? "warn" : goalPct >= 1 ? "ok" : ""}`}>
              {streak.at_risk ? "Serin tehlikede: bugün bir review gönder!"
                : goalPct >= 1 ? "Günlük hedef tamam 🎯"
                : streak.current ? `Hedefe ${streak.goal - streak.today} review kaldı.`
                : "İlk review'unla seriyi başlat."}
            </div>
            <div className="goal-stepper">
              <span className="small muted">Günlük hedef</span>
              <button className="btn btn-sm" onClick={() => changeGoal(-1)} disabled={streak.goal <= 1} aria-label="Hedefi azalt">−</button>
              <strong>{streak.goal}</strong>
              <button className="btn btn-sm" onClick={() => changeGoal(1)} disabled={streak.goal >= 30} aria-label="Hedefi artır">+</button>
            </div>
          </div>
        </section>
      </div>

      <section className="hero-card">
        <div className="chart-card-head">
          <div>
            <h3>Review takvimi</h3>
            <p className="chart-card-sub">Son 26 hafta · koyu kare = günlük hedefe ulaşılan gün</p>
          </div>
        </div>
        <div className="calendar-row">
          <Heatmap cells={data.heatmap} goal={streak.goal} />
          <dl className="calendar-stats">
            <div><dt>Toplam review</dt><dd>{data.stats.reviews}</dd></div>
            <div><dt>Aktif gün</dt><dd>{data.heatmap.filter((c) => c.count > 0).length}</dd></div>
            <div><dt>Hedefe ulaşılan gün</dt><dd>{data.heatmap.filter((c) => c.count >= streak.goal).length}</dd></div>
            <div><dt>Yakalanan sorun</dt><dd>{data.stats.findings}</dd></div>
            <div><dt>Toplu onay</dt><dd>{data.stats.batch_approvals}</dd></div>
            <div><dt>Düzeltme PR'ı</dt><dd>{data.stats.fix_prs}</dd></div>
          </dl>
        </div>
      </section>

      <div className="section-head">
        <h2>Rozetler <span className="count">{earned}/{data.badges.length}</span></h2>
        <div className="view-toggle" role="radiogroup" aria-label="Rozet filtresi">
          {([["all", "Tümü"], ["earned", "Kazanılan"], ["locked", "Kilitli"]] as const).map(([k, label]) => (
            <button key={k} role="radio" aria-checked={filter === k} className={filter === k ? "on" : ""}
                    onClick={() => setFilter(k)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="badge-grid">
        {badges.map((b) => <BadgeCard key={b.id} badge={b} />)}
      </div>
    </div>
  );
}
