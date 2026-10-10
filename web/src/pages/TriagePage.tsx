import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, InboxItem, Review, Verdict } from "../api";
import { ProcessStepper } from "../components/Process";
import { ErrorBox, Loading, SeverityBadge, VerdictBadge, VerificationBadge, verdictLabel } from "../components/ui";
import { useInbox } from "../inbox";

const KEYS: [string, string][] = [
  ["j / k", "Sonraki / önceki yorum"],
  ["x", "Seçili yorumu dahil et / çıkar"],
  ["m", "Bir daha söyleme (bu dosyada; hafızaya ekler)"],
  ["a", "Onayla (approve)"],
  ["r", "Değişiklik iste"],
  ["c", "Yorum olarak gönder"],
  ["Enter", "Gönderimi onayla"],
  ["Esc", "Vazgeç"],
  ["n / p", "Sonraki / önceki PR (atla)"],
  ["o", "PR'ı GitHub'da aç"],
  ["?", "Kısayolları göster"],
];

function isTyping(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

export function TriagePage() {
  const inbox = useInbox();
  // Freeze the queue when the page opens so submitting does not reshuffle it under the user.
  const [queue, setQueue] = useState<InboxItem[] | null>(null);
  useEffect(() => {
    if (queue === null && inbox.data) setQueue(inbox.data.items.filter((i) => i.kind === "approve" && i.review_id));
  }, [inbox.data, queue]);

  const [index, setIndex] = useState(0);
  const [done, setDone] = useState<Record<number, string>>({});
  const item = queue?.[index];

  if (inbox.error) return <div className="page"><ErrorBox error={inbox.error} onRetry={inbox.reload} /></div>;
  if (!queue) return <div className="page"><Loading label="Onay kuyruğu hazırlanıyor" /></div>;

  const remaining = queue.filter((q) => !done[q.review_id!]).length;

  return (
    <div className="page triage">
      <div className="page-head">
        <div>
          <p className="eyebrow">Hızlı mod</p>
          <h1>{remaining ? `${remaining} review onayını bekliyor` : "Kuyruk bitti 🎉"}</h1>
          <p className="muted">Klavyeyle ilerle: <kbd>j</kbd>/<kbd>k</kbd> yorumlar, <kbd>a</kbd> onayla,{" "}
            <kbd>Enter</kbd> gönder, <kbd>n</kbd> atla. Tüm kısayollar için <kbd>?</kbd></p>
        </div>
        <Link className="btn" to="/inbox">Bekleyenlere dön</Link>
      </div>

      {queue.length > 0 && (
        <div className="triage-queue">
          {queue.map((q, i) => (
            <button key={q.review_id} onClick={() => setIndex(i)}
                    className={`triage-pip ${i === index ? "current" : ""} ${done[q.review_id!] ? "done" : ""}`}
                    title={`${q.repo} #${q.pr_number} — ${q.title}`} aria-label={`${i + 1}. PR`} />
          ))}
        </div>
      )}

      {!item ? (
        <div className="empty big">
          {queue.length ? "Tüm review'lar işlendi." : "Onayını bekleyen review yok."}{" "}
          <Link to="/inbox">Bekleyenlere dön</Link>
        </div>
      ) : (
        <TriageCard key={item.review_id} item={item} position={`${index + 1} / ${queue.length}`}
                    sent={done[item.review_id!]}
                    onSent={(label) => {
                      setDone((d) => ({ ...d, [item.review_id!]: label }));
                      inbox.reload();
                      const next = queue.findIndex((q, i) => i > index && !done[q.review_id!]);
                      if (next !== -1) setIndex(next);
                    }}
                    onNext={() => setIndex((i) => Math.min(queue.length - 1, i + 1))}
                    onPrev={() => setIndex((i) => Math.max(0, i - 1))} />
      )}
    </div>
  );
}

function TriageCard({ item, position, sent, onSent, onNext, onPrev }: {
  item: InboxItem;
  position: string;
  sent?: string;
  onSent: (label: string) => void;
  onNext: () => void;
  onPrev: () => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState(0);
  const [pending, setPending] = useState<Verdict | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [help, setHelp] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.review(item.review_id!).then(setReview).catch((e: Error) => setError(e.message));
  }, [item.review_id]);

  const comments = useMemo(() => review?.comments ?? [], [review]);
  const included = comments.filter((c) => c.included).length;

  const toggle = useCallback(async (idx: number) => {
    const c = comments[idx];
    if (!c || !review) return;
    const updated = await api.patchComment(c.id, { included: !c.included });
    setReview({ ...review, comments: review.comments.map((x) => (x.id === c.id ? updated : x)) });
  }, [comments, review]);

  const suppress = useCallback(async (idx: number) => {
    const c = comments[idx];
    if (!c || !review) return;
    const res = await api.suppressComment(c.id, "file");
    setReview({ ...review, comments: review.comments.map((x) => (x.id === c.id ? res.comment : x)) });
  }, [comments, review]);

  const submit = useCallback(async (verdict: Verdict) => {
    if (!review) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.submitReview(review.id, verdict);
      setPending(null);
      onSent(verdictLabel(verdict));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }, [review, onSent]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey || submitting) return;
      const key = e.key;
      if (pending) {
        if (key === "Enter") { e.preventDefault(); submit(pending); }
        else if (key === "Escape") setPending(null);
        return;
      }
      if (key === "?") return setHelp((h) => !h);
      if (key === "Escape") return setHelp(false);
      if (key === "n") return onNext();
      if (key === "p") return onPrev();
      if (key === "o") return void window.open(`https://github.com/${item.repo}/pull/${item.pr_number}`, "_blank", "noopener");
      if (sent || !review || review.status !== "ready") return;
      if (key === "j") setFocus((f) => Math.min(comments.length - 1, f + 1));
      else if (key === "k") setFocus((f) => Math.max(0, f - 1));
      else if (key === "x") void toggle(focus);
      else if (key === "m") void suppress(focus);
      else if (key === "a") setPending("APPROVE");
      else if (key === "r") setPending("REQUEST_CHANGES");
      else if (key === "c") setPending("COMMENT");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, submitting, sent, review, comments.length, focus, toggle, suppress, submit, onNext, onPrev, item]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${focus}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focus]);

  return (
    <div className="triage-card">
      <header className="triage-head">
        <div className="triage-pos mono">{position}</div>
        <div className="triage-title">
          <div className="muted small">{item.repo} <span className="mono">#{item.pr_number}</span> · {item.author}</div>
          <Link to={`/r/${item.repo}/pull/${item.pr_number}`} className="triage-pr">{item.title}</Link>
        </div>
        {review && <VerdictBadge verdict={review.verdict} />}
      </header>

      {error && <ErrorBox error={error} />}
      {!review ? <Loading /> : (
        <>
          <ProcessStepper review={review} />
          {sent ? (
            <div className="next-action next-success"><div className="next-text">
              <div className="next-title">Gönderildi · {sent}</div>
              <div className="next-body">Sonraki PR için <kbd>n</kbd>.</div>
            </div></div>
          ) : review.status !== "ready" ? (
            <div className="next-action"><div className="next-text">
              <div className="next-title">Bu review artık onay beklemiyor ({review.status}).</div>
              <div className="next-body">Atlamak için <kbd>n</kbd>.</div>
            </div></div>
          ) : null}

          <p className="triage-summary">{review.summary}</p>

          {comments.length > 0 && (
            <div className="triage-comments" ref={listRef}>
              {comments.map((c, i) => (
                <div key={c.id} data-idx={i} onClick={() => setFocus(i)}
                     className={`triage-comment ${i === focus ? "focused" : ""} ${c.included ? "" : "excluded"}`}>
                  <span className={`triage-check ${c.included ? "on" : ""}`} aria-label={c.included ? "dahil" : "hariç"}>
                    {c.included ? "✓" : ""}
                  </span>
                  <SeverityBadge severity={c.severity} />
                  <div className="triage-comment-main">
                    <div className="triage-comment-title">{c.title}</div>
                    <div className="muted small mono">{c.path}:{c.line}</div>
                    {i === focus && <div className="triage-comment-body">{c.body}</div>}
                  </div>
                  <VerificationBadge value={c.verification} note={c.verification_note} />
                </div>
              ))}
            </div>
          )}

          {!sent && review.status === "ready" && (
            <div className={`triage-bar ${pending ? "confirm" : ""}`}>
              {pending ? (
                <>
                  <span>
                    <strong>{included}</strong> yorumla <VerdictBadge verdict={pending} /> olarak{" "}
                    <strong>{item.author}</strong>'in PR'ına gönderilsin mi?
                  </span>
                  <div className="spacer" />
                  <span className="muted small"><kbd>Esc</kbd> vazgeç</span>
                  <button className="btn btn-primary" onClick={() => submit(pending)} disabled={submitting}>
                    {submitting ? <span className="spinner" /> : <>Gönder <kbd className="kbd-inv">Enter</kbd></>}
                  </button>
                </>
              ) : (
                <>
                  <span className="muted">{included} / {comments.length} yorum dahil</span>
                  <div className="spacer" />
                  <button className="btn" onClick={() => setPending("COMMENT")}>Yorum <kbd>c</kbd></button>
                  <button className="btn" onClick={() => setPending("REQUEST_CHANGES")}>Değişiklik iste <kbd>r</kbd></button>
                  <button className="btn btn-primary" onClick={() => setPending("APPROVE")}>
                    Onayla <kbd className="kbd-inv">a</kbd>
                  </button>
                </>
              )}
            </div>
          )}
        </>
      )}

      {help && (
        <div className="kbd-help" role="dialog" aria-label="Klavye kısayolları" onClick={() => setHelp(false)}>
          <div className="kbd-help-card" onClick={(e) => e.stopPropagation()}>
            <h3>Klavye kısayolları</h3>
            <dl>
              {KEYS.map(([k, d]) => (
                <div key={k}><dt><kbd>{k}</kbd></dt><dd>{d}</dd></div>
              ))}
            </dl>
          </div>
        </div>
      )}
    </div>
  );
}
