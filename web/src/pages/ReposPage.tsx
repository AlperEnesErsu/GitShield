import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, LanguageShare, Repo } from "../api";
import {
  BarRow,
  ChartCard,
  CompositionBar,
  formatNumber,
  Kpi,
  Part,
  Series,
  StackedBarList,
} from "../components/charts";
import { Column, DataTable } from "../components/DataTable";
import { DraftIcon, IssueIcon, LockIcon, PullIcon, RefreshIcon, RepoIcon, SearchIcon } from "../components/icons";
import { Badge, ErrorBox, Loading } from "../components/ui";
import { timeAgo, useAsync } from "../hooks";

export const OTHER_COLOR = "var(--chart-other)";
export const langColor = (l: { color: string | null }) => l.color ?? OTHER_COLOR;

const WORK_SERIES: Series[] = [
  { key: "prs", label: "Açık PR", color: "var(--series-1)" },
  { key: "issues", label: "Açık issue", color: "var(--series-2)" },
  { key: "drafts", label: "Taslak issue", color: "var(--series-3)" },
];
const ACTIVITY_SERIES: Series[] = [{ key: "repos", label: "Repo", color: "var(--series-1)" }];
const BUCKETS: [string, number][] = [
  ["Son 7 gün", 7],
  ["Son 30 gün", 30],
  ["Son 90 gün", 90],
  ["Son 1 yıl", 365],
  ["Daha eski", Infinity],
];

function LangBar({ languages }: { languages: LanguageShare[] }) {
  if (!languages.length) return null;
  return (
    <div className="mini-lang" title={languages.map((l) => `${l.name} ${Math.round(l.share * 100)}%`).join(" · ")}>
      {languages.map((l) => (
        <span key={l.name} style={{ flexGrow: l.bytes, background: langColor(l) }} />
      ))}
    </div>
  );
}

const COLUMNS: Column<Repo>[] = [
  {
    key: "name",
    header: "Repo",
    sortValue: (r) => r.full_name.toLowerCase(),
    render: (r) => (
      <div className="cell-main repo-cell">
        <div className="cell-title">
          <span className="muted">{r.owner} /</span>
          <strong>{r.name}</strong>
          {r.private && <Badge tone="muted"><LockIcon size={11} /> private</Badge>}
          {r.archived && <Badge tone="muted">arşiv</Badge>}
          {r.fork && <Badge tone="muted">fork</Badge>}
        </div>
        {r.description && <div className="cell-sub clamp">{r.description}</div>}
        <LangBar languages={r.languages} />
      </div>
    ),
  },
  {
    key: "language",
    header: "Dil",
    secondary: true,
    sortValue: (r) => r.language?.name ?? null,
    render: (r) =>
      r.language ? (
        <span className="lang">
          <span className="label-dot" style={{ background: r.language.color }} />
          {r.language.name}
        </span>
      ) : (
        <span className="muted">—</span>
      ),
  },
  {
    key: "prs",
    header: "Açık PR",
    align: "right",
    sortValue: (r) => r.open_prs,
    render: (r) => <span className={r.open_prs ? "num strong" : "num faint"}>{r.open_prs}</span>,
  },
  {
    key: "merged",
    header: "Merge",
    align: "right",
    secondary: true,
    sortValue: (r) => r.merged_prs,
    render: (r) => <span className={r.merged_prs ? "num" : "num faint"}>{formatNumber(r.merged_prs)}</span>,
  },
  {
    key: "issues",
    header: "Açık issue",
    align: "right",
    sortValue: (r) => r.open_issues,
    render: (r) => <span className={r.open_issues ? "num" : "num faint"}>{r.open_issues}</span>,
  },
  {
    key: "drafts",
    header: "Taslak",
    align: "right",
    sortValue: (r) => r.draft_issues,
    render: (r) =>
      r.draft_issues ? <Badge tone="high">{r.draft_issues}</Badge> : <span className="num faint">0</span>,
  },
  {
    key: "pushed",
    header: "Son push",
    secondary: true,
    sortValue: (r) => r.pushed_at,
    render: (r) => <span className="muted nowrap">{timeAgo(r.pushed_at)}</span>,
  },
  {
    key: "permission",
    header: "Yetki",
    secondary: true,
    sortValue: (r) => r.permission,
    render: (r) => <span className="perm">{r.permission?.toLowerCase()}</span>,
  },
];

export function ReposPage() {
  const navigate = useNavigate();
  const [refresh, setRefresh] = useState(0);
  const repos = useAsync(() => api.repos(refresh > 0), [refresh]);
  const [query, setQuery] = useState("");
  const [onlyWithPrs, setOnlyWithPrs] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const all = repos.data?.repos ?? [];
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter(
      (r) =>
        (showArchived || !r.archived) &&
        (!onlyWithPrs || r.open_prs > 0) &&
        (!q || r.full_name.toLowerCase().includes(q) || r.description?.toLowerCase().includes(q)),
    );
  }, [all, query, onlyWithPrs, showArchived]);

  const summary = useMemo(() => {
    const sum = (f: (r: Repo) => number) => all.reduce((n, r) => n + f(r), 0);

    const attention: BarRow[] = all
      .filter((r) => r.open_prs + r.open_issues + r.draft_issues > 0)
      .sort((a, b) => b.open_prs * 3 + b.open_issues + b.draft_issues * 2 - (a.open_prs * 3 + a.open_issues + a.draft_issues * 2))
      .slice(0, 7)
      .map((r) => ({
        key: r.full_name,
        tipTitle: r.full_name,
        label: <><span className="muted">{r.owner}/</span>{r.name}</>,
        values: { prs: r.open_prs, issues: r.open_issues, drafts: r.draft_issues },
        onClick: () => navigate(`/r/${r.full_name}`),
      }));

    const bytes = new Map<string, { color: string | null; bytes: number }>();
    for (const r of all) {
      if (r.archived) continue;
      for (const l of r.languages) {
        const cur = bytes.get(l.name) ?? { color: l.color, bytes: 0 };
        cur.bytes += l.bytes;
        bytes.set(l.name, cur);
      }
    }
    const ranked = [...bytes.entries()].sort((a, b) => b[1].bytes - a[1].bytes);
    const languages: Part[] = ranked.slice(0, 6).map(([name, v]) => ({
      key: name, label: name, value: v.bytes, color: v.color ?? OTHER_COLOR,
    }));
    const rest = ranked.slice(6).reduce((n, [, v]) => n + v.bytes, 0);
    if (rest) languages.push({ key: "other", label: "Diğer", value: rest, color: OTHER_COLOR });

    const now = Date.now();
    const counts = BUCKETS.map(() => 0);
    for (const r of all) {
      if (!r.pushed_at) continue;
      const days = (now - new Date(r.pushed_at).getTime()) / 86400000;
      counts[BUCKETS.findIndex(([, limit]) => days <= limit)]++;
    }
    const activity: BarRow[] = BUCKETS.map(([label], i) => ({
      key: label, label, values: { repos: counts[i] },
    }));

    return {
      prs: sum((r) => r.open_prs),
      merged: sum((r) => r.merged_prs),
      issues: sum((r) => r.open_issues),
      issueRepos: all.filter((r) => r.open_issues > 0).length,
      drafts: sum((r) => r.draft_issues),
      reviews: sum((r) => r.reviews),
      privateCount: all.filter((r) => r.private).length,
      attention,
      languages,
      activity,
    };
  }, [all, navigate]);

  const login = repos.data?.login;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Genel bakış</p>
          <h1>{login ? `Merhaba, ${login}` : "Repolar"}</h1>
          <p className="muted">Erişimin olan tüm repolar, açık iş yükü ve GitShield bulguları tek ekranda.</p>
        </div>
        <button className="btn" onClick={() => setRefresh((n) => n + 1)} disabled={repos.loading}>
          <RefreshIcon size={15} className={repos.loading ? "spin" : undefined} /> Yenile
        </button>
      </div>

      {repos.error ? (
        <ErrorBox error={repos.error} onRetry={repos.reload} />
      ) : repos.loading && !repos.data ? (
        <Loading label="Repolar getiriliyor" />
      ) : (
        <>
          <div className="kpis">
            <Kpi icon={<RepoIcon />} label="Repo" value={all.length}
                 sub={`${summary.privateCount} private · ${all.length - summary.privateCount} public`} />
            <Kpi icon={<PullIcon />} label="Açık PR" value={summary.prs} tone="accent"
                 sub={`${formatNumber(summary.merged)} PR merge edildi`} />
            <Kpi icon={<IssueIcon />} label="Açık issue" value={summary.issues}
                 sub={`${summary.issueRepos} repoda`} />
            <Kpi icon={<DraftIcon />} label="Açılmamış taslak issue" value={summary.drafts}
                 tone={summary.drafts ? "warn" : undefined} sub={`${summary.reviews} GitShield review`} />
          </div>

          <div className="chart-grid">
            <ChartCard title="Dikkat bekleyen repolar" subtitle="Açık PR, issue ve taslak issue yüküne göre"
                       className="span-2">
              <StackedBarList rows={summary.attention} series={WORK_SERIES}
                              empty="Açık PR ya da issue yok — her şey yolunda." />
            </ChartCard>
            <ChartCard title="Dil dağılımı" subtitle="Aktif repolardaki kod hacmi">
              <CompositionBar parts={summary.languages} unit={formatBytes} />
            </ChartCard>
            <ChartCard title="Push aktivitesi" subtitle="Son push zamanına göre repo sayısı">
              <StackedBarList rows={summary.activity} series={ACTIVITY_SERIES} />
            </ChartCard>
          </div>

          <div className="section-head">
            <h2>Tüm repolar <span className="count">{rows.length}</span></h2>
            <div className="toolbar">
              <label className="search">
                <SearchIcon size={15} />
                <input type="search" placeholder="Repo ara…" value={query} onChange={(e) => setQuery(e.target.value)} />
              </label>
              <label className="check">
                <input type="checkbox" checked={onlyWithPrs} onChange={(e) => setOnlyWithPrs(e.target.checked)} />
                Açık PR'ı olanlar
              </label>
              <label className="check">
                <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
                Arşivlenmişler
              </label>
            </div>
          </div>
          <DataTable
            rows={rows}
            columns={COLUMNS}
            rowKey={(r) => r.full_name}
            onRowClick={(r) => navigate(`/r/${r.full_name}`)}
            initialSort={{ key: "prs", dir: "desc" }}
            empty="Filtreye uyan repo yok."
          />
        </>
      )}
    </div>
  );
}

export function formatBytes(bytes: number) {
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`;
  return `${bytes} B`;
}
