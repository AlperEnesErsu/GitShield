import type { PullDetail } from "../api";
import { CompositionBar, formatNumber } from "./charts";

export type FileKind = "code" | "test" | "docs" | "config";
type PrFile = PullDetail["files"][number];

// Same notion of a test path as the risk score (TEST_PATH in gitshield/web/insights.py).
const TEST_PATH = /(^|\/)(tests?|__tests__|spec|test_)|(_test|\.test|\.spec)\./i;
const DOCS_PATH = /(^|\/)docs?\/|\.(md|mdx|rst|adoc|txt)$/i;
const CONFIG_PATH =
  /(^|\/)\.[^/]+$|^\.github\/|\.(json|ya?ml|toml|lock|ini|cfg|gradle|xml|plist|properties)$|(^|\/)(Dockerfile|Makefile|go\.sum)$/i;

export const KINDS: { key: FileKind; label: string; color: string }[] = [
  { key: "code", label: "Kod", color: "var(--series-1)" },
  { key: "test", label: "Test", color: "var(--series-3)" },
  { key: "docs", label: "Doküman", color: "var(--series-2)" },
  { key: "config", label: "Yapılandırma / lock", color: "var(--chart-other)" },
];

const kindOf = (path: string) => KINDS.find((k) => k.key === fileKind(path))!;

export function fileKind(path: string): FileKind {
  if (TEST_PATH.test(path)) return "test";
  if (DOCS_PATH.test(path)) return "docs";
  if (CONFIG_PATH.test(path)) return "config";
  return "code";
}

const KIND_ORDER: Record<FileKind, number> = { code: 0, test: 1, docs: 2, config: 3 };
const size = (f: PrFile) => f.additions + f.deletions;

/** Reading order for a review: shipped code first, biggest first; tests, docs and config after. */
export function orderFiles(files: PrFile[]): PrFile[] {
  return [...files].sort((a, b) =>
    KIND_ORDER[fileKind(a.path)] - KIND_ORDER[fileKind(b.path)] || size(b) - size(a) || a.path.localeCompare(b.path));
}

export const fileAnchor = (path: string) => `diff-${path.replace(/[^\w-]/g, "_")}`;

function jumpTo(path: string) {
  const el = document.getElementById(fileAnchor(path));
  if (el instanceof HTMLDetailsElement) el.open = true;
  el?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function FileLabel({ path, comments }: { path: string; comments: number }) {
  const cut = path.lastIndexOf("/");
  const kind = kindOf(path);
  return (
    <span className="file-label" title={path}>
      <span className="swatch" style={{ background: kind.color }} aria-label={kind.label} />
      {cut >= 0 && <span className="file-dir">{path.slice(0, cut + 1)}</span>}
      <span className="file-base">{path.slice(cut + 1)}</span>
      {comments > 0 && <span className="file-comments">{comments} yorum</span>}
    </span>
  );
}

/** Where a PR's change lands: how much is code vs tests vs docs, and which files carry it. */
export function DiffOverview({ files, commentCounts }: {
  files: PrFile[];
  commentCounts: Map<string, number>;
}) {
  if (files.length < 2) return null;
  const byKind = new Map<FileKind, { lines: number; files: number }>();
  for (const f of files) {
    const k = byKind.get(fileKind(f.path)) ?? { lines: 0, files: 0 };
    byKind.set(fileKind(f.path), { lines: k.lines + size(f), files: k.files + 1 });
  }
  const parts = KINDS.map((k) => ({
    key: k.key, color: k.color,
    label: `${k.label} · ${byKind.get(k.key)?.files ?? 0} dosya`,
    value: byKind.get(k.key)?.lines ?? 0,
  }));
  const ordered = orderFiles(files);
  const max = Math.max(1, ...files.map(size));

  return (
    <section className="card diff-overview" aria-label="Değişiklik haritası">
      <header className="diff-overview-head">
        <h3>Değişiklik haritası</h3>
        <span className="muted small">
          {files.length} dosya · {formatNumber(files.reduce((n, f) => n + size(f), 0))} satır · dosyaya tıkla, diff'ine git
        </span>
      </header>
      <CompositionBar parts={parts} unit={(v) => `${formatNumber(v)} satır`} />
      {/* Bars take the file kind's color for added lines, so they read with the bar above;
          deletions keep the diff's red. */}
      <div className="barlist">
        {ordered.map((f) => (
          <button key={f.path} type="button" className="barlist-row clickable" onClick={() => jumpTo(f.path)}
                  title={`${f.path} · +${f.additions} −${f.deletions}`}>
            <span className="barlist-label"><FileLabel path={f.path} comments={commentCounts.get(f.path) ?? 0} /></span>
            <span className="barlist-track">
              <span className="barlist-bar" style={{ width: `${(size(f) / max) * 100}%` }}>
                {f.additions > 0 && <span className="seg" style={{ flexGrow: f.additions, background: kindOf(f.path).color }} />}
                {f.deletions > 0 && <span className="seg" style={{ flexGrow: f.deletions, background: "var(--del-text)" }} />}
              </span>
            </span>
            <span className="barlist-value diff-counts">
              <span className="add">+{formatNumber(f.additions)}</span>
              {f.deletions > 0 && <span className="del">−{formatNumber(f.deletions)}</span>}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
