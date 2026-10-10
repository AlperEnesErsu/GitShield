export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type Verdict = "APPROVE" | "REQUEST_CHANGES" | "COMMENT";
export type Verification = "confirmed" | "rejected" | "uncertain" | "unverified";

export interface Label {
  name: string;
  color: string;
}

export interface Status {
  version: string;
  github: { login: string | null; error: string | null };
  llm: { provider: string; model: string };
  review_language: string;
}

export interface LanguageShare {
  name: string;
  color: string | null;
  bytes: number;
  share: number;
}

export interface RepoOverview {
  full_name: string;
  description: string | null;
  url: string;
  homepage: string | null;
  private: boolean;
  archived: boolean;
  created_at: string;
  pushed_at: string | null;
  disk_kb: number;
  stars: number;
  forks: number;
  watchers: number;
  license: string | null;
  default_branch: string | null;
  commits: number | null;
  languages: LanguageShare[];
  pulls: { open: number; merged: number; closed: number };
  issues: { open: number; closed: number };
  participation: { all: number[]; owner: number[] } | null;
  gitshield: { reviews: number; submitted: number; draft_issues: number };
}

export type CiState = "success" | "failure" | "pending" | "none";

export interface Risk {
  score: number;
  level: "low" | "medium" | "high";
  factors: { label: string; points: number }[];
}

export interface Dependency {
  package: string;
  from: string | null;
  to: string | null;
  change: "major" | "minor" | "patch" | "unknown";
  group: boolean;
  bot: boolean;
}

/** Risk, CI and dependency info the backend attaches to every open PR. */
export interface PrInsights {
  risk: Risk | null;
  ci: CiState;
  dependency: Dependency | null;
  /** Verdict of a cached CI diagnosis when CI is failing: who is to blame. */
  ci_blame?: CiBlame | null;
}

export interface BatchResult {
  number: number;
  status: "approved" | "skipped" | "failed";
  reason?: string;
  url?: string;
  review_id?: number;
}

export interface Repo {
  full_name: string;
  owner: string;
  name: string;
  description: string | null;
  url: string;
  private: boolean;
  archived: boolean;
  fork: boolean;
  pushed_at: string | null;
  stars: number;
  permission: string;
  language: { name: string; color: string } | null;
  default_branch: string | null;
  open_prs: number;
  open_issues: number;
  merged_prs: number;
  forks: number;
  languages: LanguageShare[];
  reviews: number;
  submitted_reviews: number;
  draft_issues: number;
  last_review_at: string | null;
}

export interface PullSummary extends PrInsights {
  number: number;
  title: string;
  url: string;
  state: string;
  draft: boolean;
  author: string;
  author_avatar: string;
  created_at: string;
  updated_at: string;
  head_ref: string;
  base_ref: string;
  head_sha: string;
  labels: Label[];
  review: {
    id: number;
    status: ReviewStatus;
    verdict: Verdict;
    open_comments: number;
    outdated: boolean;
    created_at: string;
  } | null;
}

export interface Issue {
  number: number;
  title: string;
  url: string;
  state: string;
  author: string;
  comments: number;
  created_at: string;
  updated_at: string;
  labels: Label[];
  assignees: string[];
}

export interface DraftIssue {
  id: number;
  repo: string;
  review_id: number | null;
  comment_id: number | null;
  title: string;
  body: string;
  severity: Severity;
  status: "draft" | "opened" | "dismissed";
  github_issue_number: number | null;
  github_issue_url: string | null;
  created_at: string;
}

export type ReviewStatus = "running" | "ready" | "failed" | "submitted";
export type StepStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface ProgressStep {
  key: "fetch" | "scan" | "ai_review" | "verify" | "approve" | "submit";
  label: string;
  status: StepStatus;
  detail: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ReviewComment {
  id: number;
  review_id: number;
  source: "scanner" | "llm" | "carried";
  path: string;
  line: number | null;
  in_diff: boolean;
  severity: Severity;
  category: string;
  title: string;
  body: string;
  suggestion: string | null;
  rule_id: string | null;
  verification: Verification;
  verification_note: string;
  included: boolean;
  fix_pr_url?: string | null;
}

export interface FixPreview {
  path: string;
  start_line: number;
  end_line: number;
  original: string;
  replacement: string;
  explanation: string;
  diff: string;
  base_branch: string;
  head_sha: string;
  branch: string;
  can_push: boolean;
  reason: string | null;
  changed: boolean;
}

export interface Followup {
  id: number;
  prev_comment_id: number | null;
  path: string;
  old_line: number | null;
  new_line: number | null;
  severity: Severity;
  title: string;
  status: "fixed" | "still_open" | "unclear";
  note: string;
}

export interface Review {
  id: number;
  repo: string;
  pr_number: number;
  head_sha: string;
  status: ReviewStatus;
  error: string | null;
  summary: string;
  verdict: Verdict;
  recommended_verdict: Verdict | null;
  verifier_notes: string;
  provider: string;
  model: string;
  skipped_files: { path: string; reason: string }[];
  stats: Record<string, number>;
  github_review_url: string | null;
  created_at: string;
  submitted_at: string | null;
  progress: ProgressStep[];
  mode: "full" | "incremental";
  base_sha: string | null;
  followups: Followup[];
  comments: ReviewComment[];
}

export interface PullDetail extends PrInsights {
  number: number;
  title: string;
  body: string;
  url: string;
  state: string;
  merged: boolean;
  draft: boolean;
  author: string;
  head_ref: string;
  base_ref: string;
  head_sha: string;
  additions: number;
  deletions: number;
  changed_files: number;
  files: { path: string; status: string; additions: number; deletions: number; patch: string | null }[];
  reviews: { id: number; status: ReviewStatus; verdict: Verdict; created_at: string; head_sha: string }[];
  latest_review: Review | null;
}

export type InboxKind = "approve" | "failed" | "outdated" | "new" | "running" | "drafts";

export interface InboxItem extends Partial<PrInsights> {
  kind: InboxKind;
  priority: number;
  repo: string;
  pr_number?: number;
  title: string;
  author?: string;
  author_avatar?: string;
  draft?: boolean;
  created_at?: string;
  updated_at: string;
  review_id?: number | null;
  verdict?: Verdict | null;
  open_comments?: number;
  error?: string | null;
  draft_count?: number;
  severities?: Severity[];
}

export interface Inbox {
  items: InboxItem[];
  counts: Partial<Record<InboxKind, number>>;
  actionable: number;
  errors: { repo: string; error: string }[];
  repos_checked: number;
}

export interface RepoSettings {
  repo: string;
  auto_review: boolean;
  include_drafts: boolean;
}

export interface Automation {
  enabled: boolean;
  interval_sec: number;
  busy: boolean;
  current: string | null;
  last_run_at: string | null;
  next_run_in_sec: number | null;
  last_error: string | null;
  started_reviews: number;
  repos: string[];
}

export interface MemoryItem {
  id: number;
  repo: string;
  kind: "suppress" | "rule";
  text: string;
  rule_id: string | null;
  path: string | null;
  source_comment_id: number | null;
  active: boolean;
  hits: number;
  created_at: string;
}

export interface StalePull {
  repo: string;
  number: number;
  title: string;
  author: string;
  age_days: number;
  updated_at: string;
}

export interface Metrics {
  days: number;
  sla_days: number;
  repos_checked: number;
  errors: { repo: string; error: string }[];
  merge: {
    count: number;
    median_hours: number | null;
    p75_hours: number | null;
    by_repo: { repo: string; count: number; median_hours: number | null }[];
    weekly: { week: string; merged: number; median_hours: number | null }[];
  };
  open: {
    count: number;
    median_age_days: number | null;
    over_sla: StalePull[];
    buckets: { label: string; count: number }[];
  };
  gitshield: {
    reviews: number;
    submitted: number;
    failed: number;
    awaiting: number;
    median_ai_seconds: number | null;
    median_approval_minutes: number | null;
    weekly: { week: string; reviews: number }[];
  };
}

export type CiBlame = "pr" | "environment" | "base" | "outdated" | "flaky" | "unknown";

export interface CiJob {
  name: string;
  id: number;
  url: string | null;
  conclusion: string;
  is_actions: boolean;
  pattern?: string | null;
  blame: CiBlame;
  blame_label: string;
  title: string;
  explanation: string;
  suggestion: string;
  evidence?: string;
  excerpt?: string;
  base?: { conclusion: string | null; run_url?: string; at?: string; event?: string; error?: string };
  audit?: { packages: string[]; touched_by_pr: string[] };
}

export interface CiDiagnosis {
  head_sha: string;
  base: string;
  actor: string;
  total_checks: number;
  failed: number;
  passing: number;
  pending: number;
  jobs: CiJob[];
  verdict: { blame: CiBlame | "none"; text: string };
  ai: { summary: string; cause: string; blame: CiBlame; fix_steps: string[]; confidence: string } | null;
  cached_at?: string;
}

export interface Badge {
  id: string;
  name: string;
  description: string;
  icon: string;
  tier: "bronze" | "silver" | "gold";
  target: number;
  value: number;
  earned: boolean;
  earned_at: string | null;
  new: boolean;
}

export interface Gamification {
  level: number;
  title: string;
  xp: number;
  level_floor: number;
  next_level_xp: number;
  progress: number;
  streak: { current: number; best: number; today: number; goal: number; at_risk: boolean };
  heatmap: { date: string; count: number }[];
  stats: Record<string, number>;
  badges: Badge[];
  new_badges: Badge[];
}

/** Fired after every successful write so progress widgets (streak, badges) can refresh. */
export const ACTIVITY_EVENT = "gitshield:activity";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method,
    headers: {
      // Required by the server for writes: blocks cross-site (CSRF) requests to the local API.
      "X-GitShield-Client": "web",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let message = resp.statusText;
    try {
      const data = await resp.json();
      message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, message);
  }
  if (method !== "GET") window.dispatchEvent(new Event(ACTIVITY_EVENT));
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

const repoPath = (fullName: string) => `/repos/${fullName}`;

export const api = {
  inbox: () => request<Inbox>("GET", "/inbox"),
  gamification: () => request<Gamification>("GET", "/gamification"),
  markBadgesSeen: () => request<void>("POST", "/gamification/seen"),
  setDailyGoal: (goal: number) => request<Gamification>("PUT", "/gamification/goal", { goal }),
  ciDiagnosis: (repo: string, n: number, opts: { refresh?: boolean; ai?: boolean } = {}) =>
    request<CiDiagnosis>("GET", `${repoPath(repo)}/pulls/${n}/ci-diagnosis?refresh=${!!opts.refresh}&ai=${!!opts.ai}`),
  rerunJob: (repo: string, jobId: number) =>
    request<{ rerun: number }>("POST", `${repoPath(repo)}/actions/jobs/${jobId}/rerun`),
  metrics: (days: number, slaDays: number) => request<Metrics>("GET", `/metrics?days=${days}&sla_days=${slaDays}`),
  notifications: () => request<{ channels: string[]; app_url: string }>("GET", "/notifications"),
  testNotification: () => request<{ results: Record<string, string> }>("POST", "/notifications/test"),
  fixPreview: (commentId: number) => request<FixPreview>("POST", `/comments/${commentId}/fix/preview`),
  createFix: (commentId: number, start: number, end: number, replacement: string) =>
    request<{ url: string; number: number; branch: string }>("POST", `/comments/${commentId}/fix`,
      { start_line: start, end_line: end, replacement }),
  memory: (repo: string) => request<MemoryItem[]>("GET", `${repoPath(repo)}/memory`),
  addRule: (repo: string, text: string) => request<MemoryItem>("POST", `${repoPath(repo)}/memory`, { text }),
  patchMemory: (id: number, patch: Partial<Pick<MemoryItem, "text" | "active">>) =>
    request<MemoryItem>("PATCH", `/memory/${id}`, patch),
  deleteMemory: (id: number) =>
    fetch(`/api/memory/${id}`, { method: "DELETE", headers: { "X-GitShield-Client": "web" } }).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText);
    }),
  suppressComment: (id: number, scope: "file" | "repo") =>
    request<{ memory: MemoryItem; comment: ReviewComment }>("POST", `/comments/${id}/suppress`, { scope }),
  dependencyBatch: (repo: string, numbers: number[], allowMajor = false) =>
    request<{ results: BatchResult[] }>("POST", `${repoPath(repo)}/dependency-batch`,
      { numbers, allow_major: allowMajor }),
  automation: () => request<Automation>("GET", "/automation"),
  runAutomation: () => request<Automation>("POST", "/automation/run"),
  repoSettings: (repo: string) => request<RepoSettings>("GET", `${repoPath(repo)}/settings`),
  setRepoSettings: (repo: string, patch: Partial<Omit<RepoSettings, "repo">>) =>
    request<RepoSettings>("PUT", `${repoPath(repo)}/settings`, patch),
  status: () => request<Status>("GET", "/status"),
  repos: (refresh = false) =>
    request<{ login: string; repos: Repo[] }>("GET", `/repos${refresh ? "?refresh=true" : ""}`),
  overview: (repo: string) => request<RepoOverview>("GET", `${repoPath(repo)}/overview`),
  pulls: (repo: string) => request<PullSummary[]>("GET", `${repoPath(repo)}/pulls`),
  issues: (repo: string) => request<Issue[]>("GET", `${repoPath(repo)}/issues`),
  draftIssues: (repo: string) => request<DraftIssue[]>("GET", `${repoPath(repo)}/draft-issues?all=true`),
  pull: (repo: string, n: number) => request<PullDetail>("GET", `${repoPath(repo)}/pulls/${n}`),
  startReview: (repo: string, n: number, full = false) =>
    request<{ id: number; status: ReviewStatus }>("POST", `${repoPath(repo)}/pulls/${n}/reviews${full ? "?full=true" : ""}`),
  review: (id: number) => request<Review>("GET", `/reviews/${id}`),
  patchReview: (id: number, patch: Partial<Pick<Review, "summary" | "verdict">>) =>
    request<Review>("PATCH", `/reviews/${id}`, patch),
  patchComment: (id: number, patch: Partial<Pick<ReviewComment, "included" | "title" | "body">>) =>
    request<ReviewComment>("PATCH", `/comments/${id}`, patch),
  commentToIssue: (id: number) => request<DraftIssue>("POST", `/comments/${id}/draft-issue`),
  submitReview: (id: number, event?: Verdict) =>
    request<{ url: string | null; review: Review }>("POST", `/reviews/${id}/submit`, { event }),
  patchDraftIssue: (id: number, patch: Partial<Pick<DraftIssue, "title" | "body">>) =>
    request<DraftIssue>("PATCH", `/draft-issues/${id}`, patch),
  openDraftIssue: (id: number) => request<DraftIssue>("POST", `/draft-issues/${id}/open`),
  dismissDraftIssue: (id: number) => request<DraftIssue>("POST", `/draft-issues/${id}/dismiss`),
};
