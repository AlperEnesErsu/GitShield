import { useState } from "react";
import { api, ReviewComment } from "../../api";
import { FixDialog } from "../../components/FixDialog";
import { Badge, SeverityBadge, VerificationBadge } from "../../components/ui";

export function CommentCard({ comment: c, onChange, locked, compact }: {
  comment: ReviewComment;
  onChange?: (c: ReviewComment) => void;
  locked?: boolean;
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(c.body);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const patch = async (p: Partial<Pick<ReviewComment, "included" | "body">>) => {
    setBusy(true);
    try {
      onChange?.(await api.patchComment(c.id, p));
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const [suppressing, setSuppressing] = useState(false);
  const [fixing, setFixing] = useState(false);
  const suppress = async (scope: "file" | "repo") => {
    setBusy(true);
    try {
      const res = await api.suppressComment(c.id, scope);
      onChange?.(res.comment);
      setNote(scope === "file"
        ? "Hafızaya eklendi: bu dosyada bir daha söylenmeyecek."
        : "Hafızaya eklendi: bu repoda bir daha söylenmeyecek.");
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
      setSuppressing(false);
    }
  };

  const toIssue = async () => {
    setBusy(true);
    try {
      await api.commentToIssue(c.id);
      setNote("Taslak issue oluşturuldu; repo sayfasındaki “Açılmamış taslak issue'lar” bölümünde.");
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article id={compact ? undefined : `comment-${c.id}`}
             className={`comment ${c.included ? "" : "excluded"} ${compact ? "compact" : ""}`}>
      <header className="comment-head">
        {!locked && onChange && (
          <input type="checkbox" checked={c.included} disabled={busy} title="GitHub'a gönderilecek mi?"
                 onChange={(e) => patch({ included: e.target.checked })} />
        )}
        <SeverityBadge severity={c.severity} />
        <strong className="comment-title">{c.title}</strong>
        <VerificationBadge value={c.verification} note={c.verification_note} />
        <Badge tone="muted">{c.source === "scanner" ? `tarayıcı · ${c.rule_id}` : c.source === "carried" ? "önceki review" : `AI · ${c.category}`}</Badge>
      </header>
      {!compact && (
        <div className="comment-loc mono small">
          {c.path}:{c.line}
          {!c.in_diff && <Badge tone="medium" title="Satır diff dışında; review özetine eklenir">özet içinde</Badge>}
        </div>
      )}
      {editing ? (
        <div className="edit">
          <textarea className="input textarea" rows={6} value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="row">
            <button className="btn btn-sm btn-ghost" onClick={() => { setBody(c.body); setEditing(false); }}>Vazgeç</button>
            <button className="btn btn-sm" disabled={busy}
                    onClick={async () => { await patch({ body }); setEditing(false); }}>Kaydet</button>
          </div>
        </div>
      ) : (
        <div className="comment-body">{c.body}</div>
      )}
      {c.suggestion && <pre className="pre suggestion">{c.suggestion}</pre>}
      {c.verification_note && (
        <div className="verifier-note small">
          <span className="muted">Doğrulayıcı:</span> {c.verification_note}
        </div>
      )}
      {note && <div className="small muted">{note}</div>}
      {fixing && <FixDialog comment={c} onClose={() => setFixing(false)} onCreated={(next) => onChange?.(next)} />}
      {!locked && onChange && !editing && (
        <footer className="comment-actions">
          <button className="link-btn small" onClick={() => setEditing(true)}>Düzenle</button>
          {c.fix_pr_url ? (
            <a className="link-btn small" href={c.fix_pr_url} target="_blank" rel="noreferrer">Düzeltme PR'ı ↗</a>
          ) : c.line !== null && (
            <button className="link-btn small" disabled={busy} onClick={() => setFixing(true)}
                    title="AI bu yorumu düzelten küçük bir PR hazırlar; önce önizleme gösterilir">
              Düzeltme PR'ı oluştur
            </button>
          )}
          <button className="link-btn small" disabled={busy} onClick={toIssue}>Taslak issue yap</button>
          {suppressing ? (
            <span className="suppress-choice small">
              Bir daha söyleme:
              <button className="link-btn small" disabled={busy} onClick={() => suppress("file")}>bu dosyada</button>
              <button className="link-btn small" disabled={busy} onClick={() => suppress("repo")}>tüm repoda</button>
              <button className="link-btn small muted" onClick={() => setSuppressing(false)}>vazgeç</button>
            </span>
          ) : (
            <button className="link-btn small" disabled={busy} onClick={() => setSuppressing(true)}
                    title="Yorumu çıkarır ve repo hafızasına ekler; sonraki review'larda tekrar edilmez">
              Bunu bir daha söyleme
            </button>
          )}
        </footer>
      )}
    </article>
  );
}
