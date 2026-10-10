import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ACTIVITY_EVENT, api, Badge, Gamification } from "./api";

const REFRESH_MS = 120_000;
const TOAST_MS = 6000;

interface GamificationValue {
  data: Gamification | null;
  reload: () => void;
  setData: (g: Gamification) => void;
}

const GamificationContext = createContext<GamificationValue | null>(null);

/** Loads progress, refreshes after every write (ACTIVITY_EVENT) and celebrates new badges once. */
export function GamificationProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Gamification | null>(null);
  const [toasts, setToasts] = useState<Badge[]>([]);
  const timer = useRef<number | null>(null);

  const reload = useCallback(() => {
    api.gamification()
      .then((g) => {
        setData(g);
        if (g.new_badges.length) {
          setToasts((t) => [...t, ...g.new_badges.filter((b) => !t.some((x) => x.id === b.id))]);
          void api.markBadgesSeen().catch(() => undefined);
        }
      })
      .catch(() => undefined); // progress is decorative; never block the app on it
  }, []);

  useEffect(() => {
    reload();
    const interval = setInterval(reload, REFRESH_MS);
    // Debounced: a batch of writes (e.g. dependency batch) triggers one refresh.
    const onActivity = () => {
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(reload, 1200);
    };
    window.addEventListener(ACTIVITY_EVENT, onActivity);
    return () => {
      clearInterval(interval);
      window.removeEventListener(ACTIVITY_EVENT, onActivity);
    };
  }, [reload]);

  useEffect(() => {
    if (!toasts.length) return;
    const t = window.setTimeout(() => setToasts((list) => list.slice(1)), TOAST_MS);
    return () => window.clearTimeout(t);
  }, [toasts]);

  return (
    <GamificationContext.Provider value={{ data, reload, setData }}>
      {children}
      {toasts[0] && <BadgeToast key={toasts[0].id} badge={toasts[0]} onClose={() => setToasts((l) => l.slice(1))} />}
    </GamificationContext.Provider>
  );
}

export function useGamification(): GamificationValue {
  const ctx = useContext(GamificationContext);
  if (!ctx) throw new Error("useGamification must be used inside GamificationProvider");
  return ctx;
}

function BadgeToast({ badge, onClose }: { badge: Badge; onClose: () => void }) {
  return (
    <div className={`badge-toast tier-${badge.tier}`} role="status" aria-live="polite">
      <div className="confetti" aria-hidden>
        {Array.from({ length: 14 }, (_, i) => <span key={i} style={{ ["--i" as string]: i }} />)}
      </div>
      <div className="badge-toast-icon">{badge.icon}</div>
      <div className="badge-toast-text">
        <div className="badge-toast-kicker">Yeni rozet kazandın!</div>
        <div className="badge-toast-name">{badge.name}</div>
        <div className="badge-toast-desc">{badge.description}</div>
      </div>
      <div className="badge-toast-actions">
        <Link to="/achievements" className="btn btn-sm" onClick={onClose}>Gör</Link>
        <button className="btn btn-sm btn-ghost" onClick={onClose} aria-label="Kapat">✕</button>
      </div>
    </div>
  );
}

/** Compact streak + level indicator for the top bar. */
export function ProgressChip() {
  const { data } = useGamification();
  if (!data) return null;
  const { streak } = data;
  return (
    <Link to="/achievements" className="progress-chip" title={
      `${streak.current} günlük seri (en iyi ${streak.best}) · bugün ${streak.today}/${streak.goal} · ` +
      `Seviye ${data.level} ${data.title} · ${data.xp} XP`}>
      <span className={`flame ${streak.current ? "lit" : ""} ${streak.at_risk ? "at-risk" : ""}`} aria-hidden>🔥</span>
      <strong>{streak.current}</strong>
      <span className="chip-sep" />
      <span className="lvl">Sv {data.level}</span>
      <span className="xp-mini" aria-hidden><span style={{ width: `${Math.round(data.progress * 100)}%` }} /></span>
    </Link>
  );
}
