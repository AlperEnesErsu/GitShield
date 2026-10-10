import { Link } from "react-router-dom";
import type { InboxKind } from "../api";
import { useGamification } from "../gamification";
import { useInbox } from "../inbox";

const ACTIONS: { kind: InboxKind; label: string; tone: string }[] = [
  { kind: "approve", label: "onayını bekliyor", tone: "accent" },
  { kind: "failed", label: "hata aldı", tone: "critical" },
  { kind: "outdated", label: "yeni commit aldı", tone: "medium" },
  { kind: "new", label: "incelenmedi", tone: "neutral" },
  { kind: "drafts", label: "taslak issue grubu", tone: "high" },
];

function greeting(): string {
  const h = new Date().getHours();
  if (h < 6) return "İyi geceler";
  if (h < 12) return "Günaydın";
  if (h < 18) return "İyi günler";
  return "İyi akşamlar";
}

/** Home-page summary: who you are on the ladder, what is waiting, and the one thing to do next. */
export function TodayPanel({ login }: { login?: string }) {
  const { data: inbox } = useInbox();
  const { data: g, enabled: gamificationOn } = useGamification();
  const counts = inbox?.counts ?? {};
  const approve = counts.approve ?? 0;
  const goalLeft = g ? Math.max(0, g.streak.goal - g.streak.today) : 0;

  const cta = approve > 0
    ? { to: "/triage", text: `${approve} review'u hızlı modda onayla`, primary: true }
    : (inbox?.actionable ?? 0) > 0
      ? { to: "/inbox", text: "Bekleyenlere git", primary: true }
      : gamificationOn
        ? { to: "/achievements", text: "İlerlemene bak", primary: false }
        : { to: "/metrics", text: "Metriklere bak", primary: false };

  return (
    <section className="today">
      <div className="today-main">
        <p className="eyebrow">Bugün</p>
        <h1>{greeting()}{login ? `, ${login}` : ""}</h1>
        <p className="today-sub">
          {!inbox ? "Bekleyen işler toplanıyor…"
            : inbox.actionable === 0 ? "Bekleyen iş yok — her şey yolunda. ✨"
            : `${inbox.actionable} iş seni bekliyor.`}
          {g && g.streak.at_risk && " Serin tehlikede: bugün bir review gönder."}
          {g && !g.streak.at_risk && goalLeft > 0 && g.streak.current > 0 && ` Günlük hedefe ${goalLeft} review kaldı.`}
        </p>
        <div className="today-actions">
          {ACTIONS.filter((a) => counts[a.kind]).map((a) => (
            <Link key={a.kind} to="/inbox" className={`today-pill tone-${a.tone}`}>
              <strong>{counts[a.kind]}</strong> {a.label}
            </Link>
          ))}
          {inbox && inbox.actionable === 0 && <span className="today-pill tone-success">Inbox Zero</span>}
        </div>
        <Link to={cta.to} className={`btn ${cta.primary ? "btn-primary" : ""} today-cta`}>{cta.text} →</Link>
      </div>

      {g && (
        <Link to="/achievements" className="today-progress" aria-label="Başarılar">
          <div className={`today-flame ${g.streak.current ? "lit" : ""}`}>
            <span aria-hidden>🔥</span>
            <strong>{g.streak.current}</strong>
            <small>günlük seri</small>
          </div>
          <div className="today-level">
            <div className="today-level-row">
              <span>Seviye {g.level} · {g.title}</span>
              <span className="muted">{g.xp} XP</span>
            </div>
            <div className="xp-bar"><span style={{ width: `${g.progress * 100}%` }} /></div>
            <div className="today-goal">
              {Array.from({ length: g.streak.goal }, (_, i) => (
                <span key={i} className={i < g.streak.today ? "done" : ""} />
              ))}
              <small>bugün {g.streak.today}/{g.streak.goal}</small>
            </div>
            <div className="today-badges">
              {g.badges.filter((b) => b.earned).slice(0, 6).map((b) => (
                <span key={b.id} title={b.name} className={`mini-medal tier-${b.tier}`}>{b.icon}</span>
              ))}
              <small className="muted">{g.badges.filter((b) => b.earned).length}/{g.badges.length} rozet</small>
            </div>
          </div>
        </Link>
      )}
    </section>
  );
}
