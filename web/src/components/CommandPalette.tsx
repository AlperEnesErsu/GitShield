import { KeyboardEvent as ReactKeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Repo } from "../api";
import { useInbox } from "../inbox";
import { ThemePref } from "../theme";
import { SearchIcon } from "./icons";

interface Command {
  id: string;
  group: string;
  title: string;
  hint?: string;
  icon: string;
  keywords?: string;
  run: () => void;
}

const lower = (s: string) => s.toLocaleLowerCase("tr");

/** Every query word must appear somewhere in the title, hint or keywords. */
function matches(cmd: Command, query: string): boolean {
  const hay = lower(`${cmd.title} ${cmd.hint ?? ""} ${cmd.keywords ?? ""}`);
  return lower(query).split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

export function CommandPalette({ setTheme }: { setTheme: (t: ThemePref) => void }) {
  const navigate = useNavigate();
  const inbox = useInbox();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [repos, setRepos] = useState<Repo[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("gitshield:palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("gitshield:palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    setTimeout(() => inputRef.current?.focus(), 0);
    if (!repos.length) api.repos().then((r) => setRepos(r.repos)).catch(() => undefined);
  }, [open, repos.length]);

  const commands = useMemo<Command[]>(() => {
    const go = (to: string) => () => navigate(to);
    const pages: Command[] = [
      { id: "p-home", group: "Sayfalar", title: "Genel bakış", icon: "🏠", run: go("/") },
      { id: "p-inbox", group: "Sayfalar", title: "Bekleyenler", icon: "📥",
        hint: inbox.data ? `${inbox.data.actionable} iş` : undefined, run: go("/inbox") },
      { id: "p-triage", group: "Sayfalar", title: "Hızlı mod", icon: "⌨️", keywords: "triage onay klavye", run: go("/triage") },
      { id: "p-metrics", group: "Sayfalar", title: "Metrikler", icon: "📊", keywords: "süre sla merge", run: go("/metrics") },
      { id: "p-ach", group: "Sayfalar", title: "Başarılar", icon: "🏅", keywords: "rozet seri xp seviye", run: go("/achievements") },
    ];
    const actions: Command[] = [
      { id: "a-light", group: "Eylemler", title: "Açık temaya geç", icon: "☀️", keywords: "tema light", run: () => setTheme("light") },
      { id: "a-dark", group: "Eylemler", title: "Koyu temaya geç", icon: "🌙", keywords: "tema dark", run: () => setTheme("dark") },
      { id: "a-system", group: "Eylemler", title: "Sistem temasını kullan", icon: "🖥️", keywords: "tema system", run: () => setTheme("system") },
      { id: "a-refresh", group: "Eylemler", title: "Bekleyenleri yenile", icon: "↻", run: () => inbox.reload() },
    ];
    const prs: Command[] = (inbox.data?.items ?? [])
      .filter((i) => i.pr_number)
      .map((i) => ({
        id: `pr-${i.repo}-${i.pr_number}`, group: "Bekleyen PR'lar", icon: "🔀",
        title: i.title, hint: `${i.repo} #${i.pr_number}`, keywords: `${i.author ?? ""} ${i.kind}`,
        run: go(`/r/${i.repo}/pull/${i.pr_number}`),
      }));
    const repoCmds: Command[] = repos.map((r) => ({
      id: `repo-${r.full_name}`, group: "Repolar", icon: r.private ? "🔒" : "📁",
      title: r.full_name, hint: r.open_prs ? `${r.open_prs} açık PR` : r.description ?? undefined,
      keywords: r.language?.name, run: go(`/r/${r.full_name}`),
    }));
    return [...pages, ...prs, ...repoCmds, ...actions];
  }, [inbox, repos, navigate, setTheme]);

  const results = useMemo(() => {
    const filtered = query.trim() ? commands.filter((c) => matches(c, query)) : commands;
    return filtered.slice(0, 40);
  }, [commands, query]);

  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const run = (cmd: Command | undefined) => {
    if (!cmd) return;
    setOpen(false);
    cmd.run();
  };

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(results.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); run(results[active]); }
    else if (e.key === "Escape") setOpen(false);
  };

  let lastGroup = "";
  return (
    <div className="palette-backdrop" onClick={() => setOpen(false)}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Komut paleti" onClick={(e) => e.stopPropagation()}>
        <label className="palette-input">
          <SearchIcon size={17} />
          <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onKeyDown}
                 placeholder="Repo, PR, sayfa ya da eylem ara…" aria-label="Ara"
                 role="combobox" aria-expanded aria-controls="palette-list" aria-activedescendant={`pal-${active}`} />
          <kbd>Esc</kbd>
        </label>
        <div className="palette-list" id="palette-list" role="listbox" ref={listRef}>
          {results.length === 0 && <div className="palette-empty">Sonuç yok</div>}
          {results.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <div key={c.id}>
                {header && <div className="palette-group">{header}</div>}
                <div id={`pal-${i}`} data-idx={i} role="option" aria-selected={i === active}
                     className={`palette-item ${i === active ? "active" : ""}`}
                     onMouseMove={() => setActive(i)} onClick={() => run(c)}>
                  <span className="palette-icon" aria-hidden>{c.icon}</span>
                  <span className="palette-title">{c.title}</span>
                  {c.hint && <span className="palette-hint">{c.hint}</span>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="palette-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> gezin</span>
          <span><kbd>Enter</kbd> aç</span>
          <span><kbd>Ctrl</kbd>+<kbd>K</kbd> aç/kapat</span>
        </div>
      </div>
    </div>
  );
}

export function PaletteButton() {
  return (
    <button className="palette-trigger" onClick={() => window.dispatchEvent(new Event("gitshield:palette"))}
            aria-label="Komut paletini aç (Ctrl+K)">
      <SearchIcon size={14} />
      <span>Ara</span>
      <kbd>Ctrl K</kbd>
    </button>
  );
}
