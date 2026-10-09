import { useEffect, useState } from "react";
import { api, FixPreview, ReviewComment } from "../api";
import { ErrorBox, Loading } from "./ui";

/** Preview an AI-written fix for a comment, let the user edit it, then open a fix PR on confirm. */
export function FixDialog({ comment, onClose, onCreated }: {
  comment: ReviewComment;
  onClose: () => void;
  onCreated: (c: ReviewComment) => void;
}) {
  const [preview, setPreview] = useState<FixPreview | null>(null);
  const [replacement, setReplacement] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<string | null>(null);

  useEffect(() => {
    api.fixPreview(comment.id)
      .then((p) => { setPreview(p); setReplacement(p.replacement); })
      .catch((e: Error) => setError(e.message));
  }, [comment.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !creating && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [creating, onClose]);

  const create = async () => {
    if (!preview) return;
    setCreating(true);
    setError(null);
    try {
      const res = await api.createFix(comment.id, preview.start_line, preview.end_line, replacement);
      setCreated(res.url);
      onCreated({ ...comment, fix_pr_url: res.url });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const edited = preview && replacement !== preview.replacement;

  return (
    <div className="modal-backdrop" onClick={() => !creating && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Düzeltme PR'ı" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <p className="eyebrow">Düzeltme PR'ı</p>
            <h3>{comment.title}</h3>
            <p className="muted small mono">{comment.path}:{comment.line}</p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} disabled={creating} aria-label="Kapat">✕</button>
        </header>

        {error && <ErrorBox error={error} />}
        {!preview && !error && <Loading label="Düzeltme hazırlanıyor" />}

        {created ? (
          <div className="next-action next-success">
            <div className="next-text">
              <div className="next-title">Düzeltme PR'ı açıldı</div>
              <div className="next-body">PR yazarı inceleyip kendi branch'ine birleştirebilir.</div>
            </div>
            <a className="btn" href={created} target="_blank" rel="noreferrer">PR'ı aç ↗</a>
          </div>
        ) : preview && (
          <>
            <p className="small">{preview.explanation}</p>
            <div className="fix-grid">
              <div>
                <div className="fix-label">Önce · satır {preview.start_line}–{preview.end_line}</div>
                <pre className="pre fix-before">{preview.original}</pre>
              </div>
              <div>
                <div className="fix-label">Sonra {edited && <span className="muted">(düzenlendi)</span>}</div>
                <textarea className="input textarea mono fix-after" rows={Math.min(14, replacement.split("\n").length + 2)}
                          value={replacement} onChange={(e) => setReplacement(e.target.value)} spellCheck={false} />
              </div>
            </div>
            <details className="fix-diff">
              <summary>Önerilen diff</summary>
              <pre className="pre">{preview.diff || "(fark yok)"}</pre>
            </details>
            {!preview.can_push && preview.reason && <div className="banner-warn">{preview.reason}</div>}
            <div className="dep-bar confirm">
              <span className="small">
                <span className="mono">{preview.branch}</span> branch'i açılıp <span className="mono">{preview.base_branch}</span>{" "}
                dalına hedeflenen bir PR oluşturulacak.
              </span>
              <div className="spacer" />
              <button className="btn btn-ghost" onClick={onClose} disabled={creating}>Vazgeç</button>
              <button className="btn btn-primary" onClick={create}
                      disabled={creating || !preview.can_push || !replacement.trim() || (!preview.changed && !edited)}>
                {creating ? <span className="spinner" /> : "PR oluştur"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
