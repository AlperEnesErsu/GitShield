import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { CommandPalette, PaletteButton } from "./components/CommandPalette";
import { api } from "./api";
import { MonitorIcon, MoonIcon, ShieldIcon, SunIcon } from "./components/icons";
import { useAsync } from "./hooks";
import { GamificationProvider, ProgressChip, useGamification } from "./gamification";
import { InboxProvider, useInbox } from "./inbox";
import { ThemePref, useTheme } from "./theme";

const THEMES: { value: ThemePref; label: string; icon: JSX.Element }[] = [
  { value: "light", label: "Açık tema", icon: <SunIcon size={15} /> },
  { value: "dark", label: "Koyu tema", icon: <MoonIcon size={15} /> },
  { value: "system", label: "Sistem teması", icon: <MonitorIcon size={15} /> },
];

export function App() {
  return (
    <InboxProvider>
      <GamificationProvider>
        <Shell />
      </GamificationProvider>
    </InboxProvider>
  );
}

function InboxLink() {
  const inbox = useInbox();
  const n = inbox.data?.actionable ?? 0;
  return (
    <NavLink to="/inbox">
      Bekleyenler {n > 0 && <span className="nav-badge">{n}</span>}
    </NavLink>
  );
}

function Shell() {
  const location = useLocation();
  const { enabled: gamificationOn } = useGamification();
  const status = useAsync(() => api.status(), []);
  const [theme, setTheme] = useTheme();
  const s = status.data;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            <span className="brand-mark"><ShieldIcon size={16} strokeWidth={2.2} /></span>
            <span>GitShield</span>
          </Link>
          <nav className="topnav">
            <NavLink to="/" end>Genel bakış</NavLink>
            <InboxLink />
            <NavLink to="/metrics">Metrikler</NavLink>
            {gamificationOn && <NavLink to="/achievements">Başarılar</NavLink>}
          </nav>
          <div className="topbar-meta">
            <PaletteButton />
            <ProgressChip />
            {s && (
              <span className={`pill ${s.llm.provider === "none" ? "pill-warn" : "pill-ok"}`}
                    title="LLM_PROVIDER / LLM_MODEL ile değiştirilebilir">
                <span className="pill-dot" />
                {s.llm.provider === "none" ? "Yalnızca tarama" : `${s.llm.provider} · ${s.llm.model}`}
              </span>
            )}
            <div className="segmented" role="radiogroup" aria-label="Tema">
              {THEMES.map((t) => (
                <button key={t.value} role="radio" aria-checked={theme === t.value} title={t.label}
                        aria-label={t.label} className={theme === t.value ? "on" : ""}
                        onClick={() => setTheme(t.value)}>
                  {t.icon}
                </button>
              ))}
            </div>
            {s?.github.login && (
              <a className="avatar-chip" href={`https://github.com/${s.github.login}`} target="_blank" rel="noreferrer">
                <img src={`https://github.com/${s.github.login}.png?size=48`} alt="" width={24} height={24} />
                <span>{s.github.login}</span>
              </a>
            )}
          </div>
        </div>
      </header>
      {s?.github.error && (
        <div className="banner">
          <strong>GitHub bağlantısı yok:</strong> {s.github.error} — <code>.env</code> dosyasına{" "}
          <code>GITHUB_TOKEN</code> ekleyin ya da <code>gh auth login</code> çalıştırıp sunucuyu yeniden başlatın.
        </div>
      )}
      <CommandPalette setTheme={setTheme} />
      <main className="content">
        <ErrorBoundary resetKey={location.pathname}>
          <div className="route-fade" key={location.pathname}>
            <Outlet />
          </div>
        </ErrorBoundary>
      </main>
    </div>
  );
}
