import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Automation, Inbox, InboxItem, InboxKind } from "../api";
import { RefreshIcon } from "../components/icons";
import { RiskWord } from "../components/insights";
import { ErrorBox, Loading, SeverityBadge, Switch, VerdictBadge } from "../components/ui";
import { timeAgo, useAsync } from "../hooks";
import { useInbox } from "../inbox";

/** Each group is a task: a verb, one sentence on why, in the order they should be done. */
const GROUPS: { kind: InboxKind; title: string; hint: string; tone: string }[] = [
  { kind: "approve", title: "Onayla", hint: "GitShield incelemeyi bitirdi. Bulgulara bakıp review'u gönder.", tone: "accent" },
  { kind: "failed", title: "Tekrar dene", hint: "İnceleme tamamlanamadı.", tone: "critical" },
  { kind: "outdated", title: "Yeniden incele", hint: "PR'a yeni commit geldi; eski review artık geçerli değil.", tone: "medium" },
  { kind: "new", title: "İncele", hint: "Henüz hiç incelenmedi. En uzun bekleyen en üstte.", tone: "neutral" },
  { kind: "running", title: "İnceleniyor", hint: "Arka planda çalışıyor; bitince burada görünecek.", tone: "info" },
  { kind: "drafts", title: "Issue aç", hint: "Doğrulanmış bulgular GitHub'a issue olarak açılmayı bekliyor.", tone: "high" },
];

const SUMMARY: Partial<Record<InboxKind, (n: number) => string>> = {
  approve: (n) => `${n} review onayını bekliyor`,
  failed: (n) => `${n} inceleme yarıda kaldı`,
  outdated: (n) => `${n} PR'a yeni commit geldi`,
  new: (n) => `${n} PR henüz incelenmedi`,
  drafts: (n) => `${n} repoda açılmamış issue var`,
};

function summaryText(data: Inbox): string {
  const parts = GROUPS.flatMap((g) => {
    const n = data.counts[g.kind];
    const say = SUMMARY[g.kind];
    return n && say ? [say(n)] : [];
  });
  return parts.length ? `${parts.join(", ")}.` : `${data.repos_checked} repo kontrol edildi, bekleyen bir şey yok.`;
}

/** The error every failed item shares (e.g. the LLM provider is down), if there is one. */
function sharedError(items: InboxItem[]): string | null {
  const first = items[0]?.error;
  return items.length > 1 && first && items.every((i) => i.error === first) ? first : null;
}

function automationLine(s: Automation): string {
  if (!s.enabled) return "Otomatik inceleme kapalı";
  if (s.repos.length === 0) return "Otomatik inceleme hiçbir repoda açık değil";
  const when = s.busy ? "şu an kontrol ediyor" : `son kontrol ${timeAgo(s.last_run_at)}`;
  return `Otomatik inceleme: ${s.repos.length} repo, ${Math.round(s.interval_sec / 60)} dakikada bir · ${when}`;
}

/** One status line; the switches and details live in a panel that opens on demand. */
function StatusAndSettings() {
  const inbox = useInbox();
  const automation = useAsync(() => api.automation(), []);
  const notifications = useAsync(() => api.notifications(), []);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const s = automation.data;
  const channels = notifications.data?.channels ?? [];

  useEffect(() => {
    if (!s?.busy) return;
    const t = setTimeout(automation.reload, 3000);
    return () => clearTimeout(t);
  }, [s, automation.reload]);

  const runNow = async () => {
    setBusy(true);
    try {
      await api.runAutomation();
      automation.reload();
    } finally {
      setBusy(false);
    }
  };
  const toggleNotify = async (on: boolean) => {
    setMessage(null);
    try {
      await inbox.setDesktopNotify(on);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };
  const testNotify = async () => {
    setMessage(null);
    try {
      const res = await api.testNotification();
      setMessage(Object.entries(res.results).map(([k, v]) => `${k}: ${v === "ok" ? "gönderildi" : v}`).join(" · "));
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const on = !!s?.enabled && (s?.repos.length ?? 0) > 0;
  return (
    <div className="inbox-status">
      <div className="inbox-status-line">
        <span className="inbox-status-text">
          <span className={`auto-dot ${on ? "on" : ""}`} />
          <span className="small muted">{s ? automationLine(s) : "Otomatik inceleme durumu okunuyor…"}</span>
        </span>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "Ayarları gizle" : "Ayarlar"}
        </button>
      </div>
      {s?.last_error && <div className="small inbox-status-error">Son otomatik kontrolde hata: {s.last_error}</div>}
      {open && (
        <div className="inbox-settings">
          <div className="inbox-setting">
            <div>
              <div className="switch-label">Otomatik inceleme</div>
              <div className="switch-hint">
                {!s?.enabled
                  ? "GITSHIELD_AUTO_REVIEW_INTERVAL=0 olduğu için kapalı."
                  : s.repos.length === 0
                    ? "Bir repo için açmak: repo sayfasındaki \"Otomatik inceleme\" anahtarı."
                    : `İzlenen repolar: ${s.repos.join(", ")}`}
              </div>
            </div>
            {on && (
              <button className="btn btn-sm" onClick={runNow} disabled={busy || s?.busy}>
                {busy || s?.busy ? <span className="spinner" /> : "Şimdi kontrol et"}
              </button>
            )}
          </div>
          <div className="inbox-setting">
            <Switch checked={inbox.desktopNotify} onChange={toggleNotify} label="Masaüstü bildirimleri"
                    hint="Uygulama açıkken onay bekleyen ya da hata alan review'lar için bildirim gösterir." />
          </div>
          <div className="inbox-setting">
            <div>
              <div className="switch-label">Dış bildirim kanalları</div>
              <div className="switch-hint">{channels.length ? channels.join(", ") : "Tanımlı değil (.env ile eklenir)."}</div>
            </div>
            {channels.length > 0 && <button className="btn btn-sm" onClick={testNotify}>Test bildirimi gönder</button>}
          </div>
          {message && <div className="small muted">{message}</div>}
        </div>
      )}
    </div>
  );
}

function ItemRow({ item, onStart, starting, hideError }: {
  item: InboxItem;
  onStart: (i: InboxItem) => void;
  starting: string | null;
  hideError: boolean;
}) {
  const key = `${item.repo}#${item.pr_number}`;
  if (item.kind === "drafts") {
    return (
      <Link to={`/r/${item.repo}`} className="inbox-row">
        <div className="inbox-main">
          <div className="inbox-title">{item.title}</div>
          <div className="inbox-sub">{item.repo}</div>
        </div>
        <div className="inbox-meta">
          {item.severities?.map((s) => <SeverityBadge key={s} severity={s} />)}
          <span className="btn btn-sm btn-primary">Issue'ları gör</span>
        </div>
      </Link>
    );
  }
  const action =
    item.kind === "approve" ? <span className="btn btn-sm btn-primary">Gözden geçir</span>
    : item.kind === "running" ? <span className="spinner" aria-label="İnceleniyor" />
    : (
      <button className="btn btn-sm" disabled={starting !== null}
              onClick={(e) => { e.preventDefault(); onStart(item); }}>
        {starting === key ? <span className="spinner" /> : item.kind === "new" ? "İncele" : "Yeniden incele"}
      </button>
    );
  const ciNote =
    item.ci === "failure" && !item.ci_blame ? "CI başarısız"
    : item.ci === "failure" ? "CI kırık (PR'ın suçu değil)"
    : null;
  return (
    <Link to={`/r/${item.repo}/pull/${item.pr_number}`} className="inbox-row">
      <div className="inbox-lead">
        <RiskWord risk={item.risk} />
        {item.dependency && <span className="inbox-tag">Bağımlılık</span>}
      </div>
      <div className="inbox-main">
        <div className="inbox-title">{item.title}</div>
        <div className="inbox-sub">
          {item.repo} #{item.pr_number} · {timeAgo(item.updated_at)}
          {item.draft && " · taslak PR"}
          {ciNote && <> · <span className="inbox-ci">{ciNote}</span></>}
        </div>
        {item.kind === "failed" && item.error && !hideError && <div className="inbox-error">{item.error}</div>}
      </div>
      <div className="inbox-meta">
        {item.kind === "approve" && item.verdict && <VerdictBadge verdict={item.verdict} />}
        {item.kind === "approve" && !!item.open_comments && <span className="muted small">{item.open_comments} bulgu</span>}
        {action}
      </div>
    </Link>
  );
}

export function InboxPage() {
  const navigate = useNavigate();
  const inbox = useInbox();
  const [starting, setStarting] = useState<string | null>(null);
  const [retryingAll, setRetryingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data = inbox.data;
  // Refresh when the page opens, unless the shared inbox is already loading (e.g. first app load).
  useEffect(() => {
    if (!inbox.loading) inbox.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = async (item: InboxItem) => {
    if (!item.pr_number) return;
    setStarting(`${item.repo}#${item.pr_number}`);
    setError(null);
    try {
      await api.startReview(item.repo, item.pr_number);
      navigate(`/r/${item.repo}/pull/${item.pr_number}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(null);
    }
  };

  const retryAll = async (items: InboxItem[]) => {
    setRetryingAll(true);
    setError(null);
    const failures: string[] = [];
    for (const item of items) {
      if (!item.pr_number) continue;
      try {
        await api.startReview(item.repo, item.pr_number);
      } catch (e) {
        failures.push(`${item.repo} #${item.pr_number}: ${(e as Error).message}`);
      }
    }
    if (failures.length) setError(failures.join("\n"));
    setRetryingAll(false);
    inbox.reload();
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Bekleyenler</p>
          <h1>{data ? (data.actionable ? `${data.actionable} iş seni bekliyor` : "Her şey yolunda") : "Bekleyenler"}</h1>
          <p className="inbox-summary">{data ? summaryText(data) : "Repolar kontrol ediliyor…"}</p>
        </div>
        <button className="btn" onClick={inbox.reload} disabled={inbox.loading}>
          <RefreshIcon size={15} className={inbox.loading ? "spin" : undefined} /> Yenile
        </button>
      </div>

      <StatusAndSettings />
      {error && <ErrorBox error={error} />}

      {inbox.error ? (
        <ErrorBox error={inbox.error} onRetry={inbox.reload} />
      ) : !data ? (
        <Loading label="Repolar taranıyor" />
      ) : data.items.length === 0 ? (
        <div className="empty big">
          Bekleyen iş yok. {data.repos_checked} repo kontrol edildi. ✨
        </div>
      ) : (
        GROUPS.filter((g) => data.counts[g.kind]).map((g, index) => {
          const items = data.items.filter((i) => i.kind === g.kind);
          const common = g.kind === "failed" ? sharedError(items) : null;
          return (
            <section key={g.kind} className={`inbox-group tone-${g.tone}`}>
              <header className="inbox-group-head">
                <span className="inbox-step">{index + 1}</span>
                <div className="inbox-group-text">
                  <h2>{g.title} <span className="count">{data.counts[g.kind]}</span></h2>
                  <p className="muted small">{g.hint}</p>
                </div>
                {g.kind === "approve" && (
                  <Link to="/triage" className="btn btn-sm btn-primary inbox-group-action">
                    Hızlı modda onayla <kbd className="kbd-inv">⌨</kbd>
                  </Link>
                )}
                {g.kind === "failed" && items.length > 1 && (
                  <button className="btn btn-sm inbox-group-action" onClick={() => retryAll(items)}
                          disabled={retryingAll || starting !== null}>
                    {retryingAll ? <span className="spinner" /> : "Hepsini yeniden dene"}
                  </button>
                )}
              </header>
              {common && (
                <div className="inbox-shared-error">
                  <strong>Neden:</strong> {common}
                </div>
              )}
              <div className="inbox-list">
                {items.map((i) => (
                  <ItemRow key={`${i.kind}-${i.repo}-${i.pr_number ?? ""}`} item={i} onStart={start}
                           starting={starting} hideError={!!common} />
                ))}
              </div>
            </section>
          );
        })
      )}
      {data && data.errors.length > 0 && (
        <p className="small muted">Okunamayan repolar: {data.errors.map((e) => e.repo).join(", ")}</p>
      )}
    </div>
  );
}
