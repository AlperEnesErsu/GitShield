import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, DraftIssue, Issue, PullSummary } from "../api";
import { Column, DataTable } from "../components/DataTable";
import {
  Badge,
  Collapsible,
  ErrorBox,
  LabelChip,
  Loading,
  ReviewStatusBadge,
  SeverityBadge,
  Switch,
  VerdictBadge,
} from "../components/ui";
import { timeAgo, useAsync } from "../hooks";
import { RepoOverviewSection } from "../components/RepoOverview";
import { MiniSteps, PrBoard, stageOf } from "../components/PrBoard";
import { CiBadge, DependencyPanel, RiskBadge } from "../components/insights";
import { ExternalIcon, LockIcon } from "../components/icons";

export function RepoPage() {
  const { owner, repo } = useParams();
  const fullName = `${owner}/${repo}`;
  const navigate = useNavigate();

  const overview = useAsync(() => api.overview(fullName), [fullName]);
  const pulls = useAsync(() => api.pulls(fullName), [fullName]);
  const issues = useAsync(() => api.issues(fullName), [fullName]);
  const drafts = useAsync(() => api.draftIssues(fullName), [fullName]);
  const settings = useAsync(() => api.repoSettings(fullName), [fullName]);
  const saveSettings = async (patch: { auto_review?: boolean; include_drafts?: boolean }) => {
    try {
      const next = await api.setRepoSettings(fullName, patch);
      settings.setData(() => next);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };
  const [starting, setStarting] = useState<number | null>(null);
  const [view, setView] = useState<"board" | "table">("board");
  const [actionError, setActionError] = useState<string | null>(null);

  const startReview = async (pr: PullSummary) => {
    setStarting(pr.number);
    setActionError(null);
    try {
      await api.startReview(fullName, pr.number);
      navigate(`/r/${fullName}/pull/${pr.number}`);
    } catch (e) {
      setActionError((e as Error).message);
      setStarting(null);
    }
  };

  const prColumns: Column<PullSummary>[] = [
    {
      key: "number",
      header: "#",
      width: "64px",
      sortValue: (p) => p.number,
      render: (p) => <span className="mono muted">#{p.number}</span>,
    },
    {
      key: "title",
      header: "Başlık",
      sortValue: (p) => p.title.toLowerCase(),
      render: (p) => (
        <div className="cell-main">
          <div className="cell-title">
            <Link to={`/r/${fullName}/pull/${p.number}`} onClick={(e) => e.stopPropagation()}>
              {p.title}
            </Link>
            {p.draft && <Badge tone="muted">taslak</Badge>}
          </div>
          <div className="cell-sub">
            <span className="mono">{p.head_ref}</span> → <span className="mono">{p.base_ref}</span>
            {p.labels.map((l) => (
              <LabelChip key={l.name} label={l} />
            ))}
          </div>
        </div>
      ),
    },
    {
      key: "risk",
      header: "Risk",
      sortValue: (p) => p.risk?.score ?? null,
      render: (p) => (
        <div className="review-cell">
          <RiskBadge risk={p.risk} />
          <CiBadge ci={p.ci} compact />
        </div>
      ),
    },
    {
      key: "author",
      header: "Yazar",
      secondary: true,
      sortValue: (p) => p.author.toLowerCase(),
      render: (p) => (
        <span className="author">
          <img src={p.author_avatar} alt="" width={20} height={20} />
          {p.author}
        </span>
      ),
    },
    {
      key: "updated",
      header: "Güncellendi",
      secondary: true,
      sortValue: (p) => p.updated_at,
      render: (p) => <span className="muted">{timeAgo(p.updated_at)}</span>,
    },
    {
      key: "review",
      header: "GitShield review",
      sortValue: (p) => (p.review ? p.review.open_comments : -1),
      render: (p) =>
        p.review ? (
          <div className="review-cell">
            <MiniSteps stage={stageOf(p)} />
            <ReviewStatusBadge status={p.review.status} />
            {p.review.status !== "running" && p.review.status !== "failed" && (
              <VerdictBadge verdict={p.review.verdict} />
            )}
            {p.review.open_comments > 0 && <span className="muted small">{p.review.open_comments} yorum</span>}
            {p.review.outdated && (
              <Badge tone="medium" title="Review'dan sonra PR'a yeni commit geldi">
                eski
              </Badge>
            )}
          </div>
        ) : (
          <span className="muted small">Review yok</span>
        ),
    },
    {
      key: "action",
      header: "",
      align: "right",
      render: (p) =>
        p.review?.status === "running" ? null : (
          <button
            className="btn btn-sm"
            disabled={starting !== null}
            onClick={(e) => {
              e.stopPropagation();
              startReview(p);
            }}
          >
            {starting === p.number ? <span className="spinner" /> : p.review ? "Yeniden incele" : "İncele"}
          </button>
        ),
    },
  ];

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/">Genel bakış</Link> <span className="sep">/</span> <span>{fullName}</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">{owner}</p>
          <h1 className="title-row">
            {repo}
            {overview.data?.private && <Badge tone="muted"><LockIcon size={11} /> private</Badge>}
            {overview.data?.archived && <Badge tone="muted">arşiv</Badge>}
          </h1>
          <p className="muted">
            {overview.data?.description ?? " "}
          </p>
          {overview.data && (
            <div className="meta-row">
              {overview.data.default_branch && <span className="mono">⎇ {overview.data.default_branch}</span>}
              {overview.data.license && <span>{overview.data.license}</span>}
              <span>Oluşturuldu {timeAgo(overview.data.created_at)}</span>
              <span>Son push {timeAgo(overview.data.pushed_at)}</span>
            </div>
          )}
        </div>
        <a className="btn" href={`https://github.com/${fullName}`} target="_blank" rel="noreferrer">
          GitHub'da aç <ExternalIcon size={14} />
        </a>
      </div>

      {actionError && <ErrorBox error={actionError} />}

      {settings.data && (
        <div className="settings-row">
          <Switch checked={settings.data.auto_review} onChange={(v) => saveSettings({ auto_review: v })}
                  label="Otomatik inceleme"
                  hint="Yeni PR ya da yeni commit gelince arka planda incelenir; sonuç onayını bekler." />
          {settings.data.auto_review && (
            <Switch checked={settings.data.include_drafts} onChange={(v) => saveSettings({ include_drafts: v })}
                    label="Taslak PR'ları da incele" />
          )}
        </div>
      )}

      <div className="section-head">
        <h2>PR süreci {pulls.data && <span className="count">{pulls.data.length} açık</span>}</h2>
        <div className="view-toggle" role="radiogroup" aria-label="Görünüm">
          <button role="radio" aria-checked={view === "board"} className={view === "board" ? "on" : ""}
                  onClick={() => setView("board")}>Pano</button>
          <button role="radio" aria-checked={view === "table"} className={view === "table" ? "on" : ""}
                  onClick={() => setView("table")}>Tablo</button>
        </div>
      </div>
      {pulls.error ? (
        <ErrorBox error={pulls.error} onRetry={pulls.reload} />
      ) : pulls.loading && !pulls.data ? (
        <Loading />
      ) : view === "board" ? (
        (pulls.data ?? []).length ? (
          <PrBoard pulls={pulls.data ?? []} repo={fullName} onStart={startReview} starting={starting} />
        ) : (
          <div className="empty">Bu repoda açık PR yok.</div>
        )
      ) : (
        <DataTable
          rows={pulls.data ?? []}
          columns={prColumns}
          rowKey={(p) => p.number}
          onRowClick={(p) => navigate(`/r/${fullName}/pull/${p.number}`)}
          initialSort={{ key: "updated", dir: "desc" }}
          empty="Bu repoda açık PR yok."
        />
      )}

      {pulls.data && (
        <DependencyPanel key={pulls.data.map((p) => `${p.number}:${p.review?.status ?? ""}`).join(",")}
                         repo={fullName} pulls={pulls.data} onDone={() => { pulls.reload(); drafts.reload(); }} />
      )}

      <div className="section-head"><h2>Repo özeti</h2></div>
      <RepoOverviewSection overview={overview.data} error={overview.error} pulls={pulls.data}
                           onRetry={overview.reload} />

      <DraftIssuesSection
        drafts={drafts.data}
        error={drafts.error}
        reload={drafts.reload}
        update={(issue) => drafts.setData((list) => list?.map((d) => (d.id === issue.id ? issue : d)))}
      />

      <Collapsible title="GitHub issue'ları" count={issues.data?.length} hint="açık">
        {issues.error ? (
          <ErrorBox error={issues.error} onRetry={issues.reload} />
        ) : issues.loading && !issues.data ? (
          <Loading />
        ) : (
          <IssuesTable issues={issues.data ?? []} />
        )}
      </Collapsible>
    </div>
  );
}

function IssuesTable({ issues }: { issues: Issue[] }) {
  const columns: Column<Issue>[] = [
    { key: "number", header: "#", width: "64px", sortValue: (i) => i.number,
      render: (i) => <span className="mono muted">#{i.number}</span> },
    {
      key: "title",
      header: "Başlık",
      sortValue: (i) => i.title.toLowerCase(),
      render: (i) => (
        <div className="cell-main">
          <a href={i.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
            {i.title}
          </a>
          {i.labels.length > 0 && (
            <div className="cell-sub">
              {i.labels.map((l) => (
                <LabelChip key={l.name} label={l} />
              ))}
            </div>
          )}
        </div>
      ),
    },
    { key: "author", header: "Açan", secondary: true, sortValue: (i) => i.author,
      render: (i) => <span className="muted">{i.author}</span> },
    { key: "assignees", header: "Atanan", secondary: true,
      render: (i) => <span className="muted">{i.assignees.join(", ") || "—"}</span> },
    { key: "comments", header: "Yorum", align: "right", sortValue: (i) => i.comments,
      render: (i) => <span className="num">{i.comments}</span> },
    { key: "updated", header: "Güncellendi", secondary: true, sortValue: (i) => i.updated_at,
      render: (i) => <span className="muted">{timeAgo(i.updated_at)}</span> },
  ];
  return (
    <DataTable rows={issues} columns={columns} rowKey={(i) => i.number}
               initialSort={{ key: "updated", dir: "desc" }} empty="Açık issue yok." />
  );
}

function DraftIssuesSection({ drafts, error, reload, update }: {
  drafts: DraftIssue[] | undefined;
  error: string | null;
  reload: () => void;
  update: (issue: DraftIssue) => void;
}) {
  const [showClosed, setShowClosed] = useState(false);
  const pending = drafts?.filter((d) => d.status === "draft") ?? [];
  const visible = showClosed ? drafts ?? [] : pending;

  return (
    <Collapsible
      title="Açılmamış taslak issue'lar"
      count={pending.length}
      hint="GitShield bulgularından üretildi · onaylayınca GitHub'da açılır"
    >
      {error ? (
        <ErrorBox error={error} onRetry={reload} />
      ) : (
        <>
          <label className="check small">
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
            Açılmış / yoksayılmışları da göster
          </label>
          {visible.length === 0 ? (
            <div className="empty">
              Bekleyen taslak yok. Doğrulanmış HIGH/CRITICAL bulgular burada birikir.
            </div>
          ) : (
            <div className="draft-list">
              {visible.map((d) => (
                <DraftIssueCard key={d.id} issue={d} onChange={update} />
              ))}
            </div>
          )}
        </>
      )}
    </Collapsible>
  );
}

function DraftIssueCard({ issue, onChange }: { issue: DraftIssue; onChange: (i: DraftIssue) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [title, setTitle] = useState(issue.title);
  const [body, setBody] = useState(issue.body);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = title !== issue.title || body !== issue.body;

  const run = async (fn: () => Promise<DraftIssue>) => {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = () =>
    run(async () => {
      if (dirty) await api.patchDraftIssue(issue.id, { title, body });
      return api.openDraftIssue(issue.id);
    });

  return (
    <div className={`draft-card status-${issue.status}`}>
      <div className="draft-head">
        <SeverityBadge severity={issue.severity} />
        <button className="link-btn draft-title" onClick={() => setExpanded((x) => !x)}>
          {issue.title}
        </button>
        <span className="muted small">{timeAgo(issue.created_at)}</span>
        <div className="spacer" />
        {issue.status === "draft" ? (
          <>
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => run(() => api.dismissDraftIssue(issue.id))}>
              Yoksay
            </button>
            <button className="btn btn-sm btn-primary" disabled={busy} onClick={open}>
              {busy ? <span className="spinner" /> : "GitHub'da aç"}
            </button>
          </>
        ) : issue.status === "opened" ? (
          <a className="btn btn-sm" href={issue.github_issue_url ?? "#"} target="_blank" rel="noreferrer">
            #{issue.github_issue_number} ↗
          </a>
        ) : (
          <Badge tone="muted">yoksayıldı</Badge>
        )}
      </div>
      {error && <ErrorBox error={error} />}
      {expanded && (
        <div className="draft-body">
          {issue.status === "draft" ? (
            <>
              <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
              <textarea className="input textarea" rows={10} value={body} onChange={(e) => setBody(e.target.value)} />
              {dirty && (
                <button className="btn btn-sm" disabled={busy}
                        onClick={() => run(() => api.patchDraftIssue(issue.id, { title, body }))}>
                  Kaydet
                </button>
              )}
            </>
          ) : (
            <pre className="pre">{issue.body}</pre>
          )}
        </div>
      )}
    </div>
  );
}
