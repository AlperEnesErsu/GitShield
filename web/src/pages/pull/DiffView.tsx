import { useMemo } from "react";
import { PullDetail, ReviewComment } from "../../api";
import { DiffOverview, fileAnchor, orderFiles } from "../../components/DiffOverview";
import { Badge } from "../../components/ui";
import { CommentCard } from "./CommentCard";

export function DiffView({ pr, comments, onChange, locked }: {
  pr: PullDetail;
  comments: ReviewComment[];
  onChange?: (c: ReviewComment) => void;
  locked?: boolean;
}) {
  const byFile = useMemo(() => {
    const map = new Map<string, Map<number, ReviewComment[]>>();
    for (const c of comments) {
      if (c.line === null || !c.in_diff) continue;
      const lines = map.get(c.path) ?? new Map<number, ReviewComment[]>();
      lines.set(c.line, [...(lines.get(c.line) ?? []), c]);
      map.set(c.path, lines);
    }
    return map;
  }, [comments]);
  const files = useMemo(() => orderFiles(pr.files), [pr.files]);
  const commentCounts = useMemo(
    () => new Map([...byFile].map(([path, lines]) => [path, [...lines.values()].flat().length])),
    [byFile],
  );

  return (
    <div className="diff">
      <DiffOverview files={pr.files} commentCounts={commentCounts} />
      {files.map((f) => {
        const fileComments = byFile.get(f.path);
        return (
          <details key={f.path} id={fileAnchor(f.path)} className="diff-file"
                   open={!!fileComments || pr.files.length <= 5}>
            <summary>
              <span className="mono">{f.path}</span>
              <span className="add small">+{f.additions}</span>
              <span className="del small">−{f.deletions}</span>
              {fileComments && <Badge tone="high">{[...fileComments.values()].flat().length} yorum</Badge>}
            </summary>
            {f.patch ? (
              <PatchLines patch={f.patch} comments={fileComments} onChange={onChange} locked={locked} />
            ) : (
              <div className="empty">Diff gösterilemiyor (binary ya da çok büyük).</div>
            )}
          </details>
        );
      })}
    </div>
  );
}

function PatchLines({ patch, comments, onChange, locked }: {
  patch: string;
  comments?: Map<number, ReviewComment[]>;
  onChange?: (c: ReviewComment) => void;
  locked?: boolean;
}) {
  const rows = useMemo(() => {
    const out: { kind: string; text: string; oldNo?: number; newNo?: number }[] = [];
    let oldNo = 0;
    let newNo = 0;
    for (const line of patch.split("\n")) {
      const header = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      if (header) {
        oldNo = Number(header[1]);
        newNo = Number(header[2]);
        out.push({ kind: "hunk", text: line });
      } else if (line.startsWith("+")) {
        out.push({ kind: "add", text: line.slice(1), newNo: newNo++ });
      } else if (line.startsWith("-")) {
        out.push({ kind: "del", text: line.slice(1), oldNo: oldNo++ });
      } else if (line.startsWith("\\")) {
        out.push({ kind: "meta", text: line });
      } else {
        out.push({ kind: "ctx", text: line.slice(1), oldNo: oldNo++, newNo: newNo++ });
      }
    }
    return out;
  }, [patch]);

  return (
    <div className="patch">
      {rows.map((row, i) => {
        const lineComments = row.newNo !== undefined ? comments?.get(row.newNo) : undefined;
        return (
          <div key={i}>
            <div className={`pl pl-${row.kind}`}>
              <span className="ln">{row.oldNo ?? ""}</span>
              <span className="ln">{row.newNo ?? ""}</span>
              <span className="code">
                {row.kind === "add" ? "+" : row.kind === "del" ? "−" : " "}
                {row.text}
              </span>
            </div>
            {lineComments?.map((c) => (
              <div key={c.id} className="inline-comment">
                <CommentCard comment={c} onChange={onChange} locked={locked} compact />
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
