import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, InboxItem, InboxKind } from "../api";
import { RefreshIcon } from "../components/icons";
import { CiBadge, RiskBadge } from "../components/insights";
import { Badge, ErrorBox, Loading, SeverityBadge, VerdictBadge } from "../components/ui";
import { timeAgo, useAsync } from "../hooks";
import { useInbox } from "../inbox";

const GROUPS: { kind: InboxKind; title: string; hint: string; tone: string }[] = [
  { kind: "approve", title: "Onayını bekliyor", hint: "AI review hazır; gözden geçir ve gönder", tone: "accent" },
  { kind: "failed", title: "Hata aldı", hint: "İnceleme yarıda kaldı; yeniden dene", tone: "critical" },
  { kind: "outdated", title: "Yeni commit geldi", hint: "Önceki review eski commit için; yeniden incele", tone: "medium" },
  { kind: "new", title: "Henüz incelenmedi", hint: "En uzun bekleyen en üstte", tone: "neutral" },
  { kind: "running", title: "İnceleniyor", hint: "Arka planda çalışıyor", tone: "info" },
  { kind: "drafts", title: "Açılmamış taslak issue'lar", hint: "Doğrulanmış bulgular GitHub'a açılmayı bekliyor", tone: "high" },
];

function AutomationBar() {
  const status = useAsync(() => api.automation(), []);
  const [busy, setBusy] = useState(false);
  const s = status.data;

  useEffect(() => {
    if (!s?.busy) return;
    const t = setTimeout(status.reload, 3000);
    return () => clearTimeout(t);
  }, [s, status.reload]);

  if (!s) return null;
  const minutes = Math.round(s.interval_sec / 60);
  const runNow = async () => {
    setBusy(true);
    try {
      await api.runAutomation();
      status.reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`auto-bar ${s.repos.length ? "on" : ""}`}>
      <span className="auto-dot" />
      <div className="auto-text">
        {!s.enabled ? (
          <>Otomatik inceleme kapalı <span className="muted">(GITSHIELD_AUTO_REVIEW_INTERVAL=0)</span></>
        ) : s.repos.length === 0 ? (
          <>Otomatik inceleme hiçbir repoda açık değil. <span className="muted">Repo sayfasındaki anahtarla aç.</span></>
        ) : (
          <>
            <strong>Otomatik inceleme</strong> {s.repos.length} repoyu her {minutes} dakikada kontrol ediyor
            <span className="muted">
              {" "}· {s.busy ? `şu an: ${s.current ?? "kontrol ediliyor"}` : `son kontrol ${timeAgo(s.last_run_at)}`}
              {s.started_reviews > 0 && ` · bu oturumda ${s.started_reviews} PR incelendi`}
            </span>
            {s.last_error && <div className="small" style={{ color: "var(--critical)" }}>Son hata: {s.last_error}</div>}
          </>
        )}
      </div>
      {s.enabled && s.repos.length > 0 && (
        <button className="btn btn-sm" onClick={runNow} disabled={busy || s.busy}>
          {busy || s.busy ? <span className="spinner" /> : "Şimdi kontrol et"}
        </button>
      )}
    </div>
  );
}

function ItemRow({ item, onStart, starting }: {
  item: InboxItem;
  onStart: (i: InboxItem) => void;
  starting: string | null;
}) {
  const key = `${item.repo}#${item.pr_number}`;
  if (item.kind === "drafts") {
    return (
      <Link to={`/r/${item.repo}`} className="inbox-row">
        <div className="inbox-main">
          <div className="inbox-repo">{item.repo}</div>
          <div className="inbox-title">{item.title}</div>
        </div>
        <div className="inbox-meta">
          {item.severities?.map((s) => <SeverityBadge key={s} severity={s} />)}
          <span className="btn btn-sm">Aç</span>
        </div>
      </Link>
    );
  }
  const action =
    item.kind === "approve" ? <span className="btn btn-sm btn-primary">Gözden geçir</span>
    : item.kind === "running" ? <span className="muted small"><span className="spinner" /></span>
    : (
      <button className="btn btn-sm" disabled={starting !== null}
              onClick={(e) => { e.preventDefault(); onStart(item); }}>
        {starting === key ? <span className="spinner" /> : item.kind === "new" ? "İncele" : "Yeniden incele"}
      </button>
    );
  return (
    <Link to={`/r/${item.repo}/pull/${item.pr_number}`} className="inbox-row">
      {item.author_avatar && <img className="inbox-avatar" src={item.author_avatar} alt="" width={28} height={28} />}
      <div className="inbox-main">
        <div className="inbox-repo">{item.repo} <span className="mono">#{item.pr_number}</span> · {item.author}</div>
        <div className="inbox-title">{item.title}</div>
        {item.kind === "failed" && item.error && <div className="inbox-error">{item.error}</div>}
      </div>
      <div className="inbox-meta">
        {item.draft && <Badge tone="muted">taslak</Badge>}
        <RiskBadge risk={item.risk} />
        <CiBadge ci={item.ci} compact />
        {item.kind === "approve" && item.verdict && <VerdictBadge verdict={item.verdict} />}
        {item.kind === "approve" && !!item.open_comments && <span className="muted small">{item.open_comments} yorum</span>}
        <span className="muted small nowrap" title="Son güncelleme">{timeAgo(item.updated_at)}</span>
        {action}
      </div>
    </Link>
  );
}

export function InboxPage() {
  const navigate = useNavigate();
  const inbox = useInbox();
  const [starting, setStarting] = useState<string | null>(null);
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

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Bekleyenler</p>
          <h1>{data ? (data.actionable ? `${data.actionable} iş seni bekliyor` : "Her şey yolunda") : "Bekleyenler"}</h1>
          <p className="muted">Tüm repolardaki PR'lar ve bulgular aciliyet sırasıyla. En önemlisi en üstte.</p>
        </div>
        <button className="btn" onClick={inbox.reload} disabled={inbox.loading}>
          <RefreshIcon size={15} className={inbox.loading ? "spin" : undefined} /> Yenile
        </button>
      </div>

      <AutomationBar />
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
        GROUPS.filter((g) => data.counts[g.kind]).map((g) => (
          <section key={g.kind} className={`inbox-group tone-${g.tone}`}>
            <header className="inbox-group-head">
              <span className="dot" />
              <h2>{g.title} <span className="count">{data.counts[g.kind]}</span></h2>
              <span className="muted small">{g.hint}</span>
              {g.kind === "approve" && (
                <Link to="/triage" className="btn btn-sm btn-primary inbox-group-action">
                  Hızlı mod <kbd className="kbd-inv">⌨</kbd>
                </Link>
              )}
            </header>
            <div className="inbox-list">
              {data.items.filter((i) => i.kind === g.kind).map((i) => (
                <ItemRow key={`${i.kind}-${i.repo}-${i.pr_number ?? ""}`} item={i} onStart={start} starting={starting} />
              ))}
            </div>
          </section>
        ))
      )}
      {data && data.errors.length > 0 && (
        <p className="small muted">Okunamayan repolar: {data.errors.map((e) => e.repo).join(", ")}</p>
      )}
    </div>
  );
}
