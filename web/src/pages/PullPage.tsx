import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Followup, PullDetail, Review, ReviewComment, Severity, Verdict, Verification } from "../api";
import { ChartCard, CompositionBar, Series, StackedBarList } from "../components/charts";
import { ExternalIcon } from "../components/icons";
import { ProcessStepper } from "../components/Process";
import { RiskPanel, RiskWord } from "../components/insights";
import { FixDialog } from "../components/FixDialog";
import { CiDiagnosisCard } from "../components/CiDiagnosis";
import { DiffOverview, fileAnchor, orderFiles } from "../components/DiffOverview";
import {
  Badge,
  Collapsible,
  ErrorBox,
  Loading,
  SeverityBadge,
  VerdictBadge,
  VerificationBadge,
  verdictLabel,
} from "../components/ui";
import { timeAgo, useAsync } from "../hooks";

const POLL_MS = 2000;

export function PullPage() {
  const { owner, repo, number } = useParams();
  const fullName = `${owner}/${repo}`;
  const prNumber = Number(number);
  const pr = useAsync(() => api.pull(fullName, prNumber), [fullName, prNumber]);
  const [reviewId, setReviewId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [tab, setTab] = useState<"review" | "diff">("review");

  useEffect(() => {
    if (pr.data && reviewId === null) setReviewId(pr.data.latest_review?.id ?? null);
  }, [pr.data, reviewId]);

  const review = useAsync<Review | null>(
    () => (reviewId === null ? Promise.resolve(null) : api.review(reviewId)),
    [reviewId],
  );
  const r = review.data;

  // Poll while the background pipeline is running so the stepper moves live.
  useEffect(() => {
    if (r?.status !== "running") return;
    const t = setTimeout(review.reload, POLL_MS);
    return () => clearTimeout(t);
  }, [r, review.reload]);

  // Refresh the PR (review list, counts) once a run finishes.
  const finished = r && r.status !== "running";
  useEffect(() => {
    if (finished) pr.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);

  const start = async (full = false) => {
    setStarting(true);
    setStartError(null);
    try {
      const { id } = await api.startReview(fullName, prNumber, full);
      setReviewId(id);
      setTab("review");
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  if (pr.error) return <div className="page"><ErrorBox error={pr.error} onRetry={pr.reload} /></div>;
  if (!pr.data) return <div className="page"><Loading label="PR getiriliyor" /></div>;
  const p = pr.data;
  const current = reviewId === null ? null : r;
  const canRerun = p.state === "open" && current?.status !== "running";

  const findings = current?.comments.filter((c) => c.verification !== "rejected") ?? [];
  const showFindings = () => {
    setTab("review");
    requestAnimationFrame(() => document.getElementById("findings")?.scrollIntoView({ behavior: "smooth" }));
  };

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/">Genel bakış</Link> <span className="sep">/</span>{" "}
        <Link to={`/r/${fullName}`}>{fullName}</Link> <span className="sep">/</span> <span>#{p.number}</span>
      </nav>
      <div className="page-head">
        <div>
          <h1>{p.title}</h1>
          <div className="meta-row">
            <span>{p.author} · #{p.number}</span>
            {p.draft && <Badge tone="muted">taslak</Badge>}
            <span>{p.changed_files} dosya değişti</span>
          </div>
        </div>
        <div className="head-actions">
          <a className="btn btn-ghost" href={p.url} target="_blank" rel="noreferrer">GitHub'da aç <ExternalIcon size={14} /></a>
        </div>
      </div>
      {startError && <ErrorBox error={startError} />}

      <ResultCard pr={p} review={current ?? null} findings={findings} starting={starting}
                  onStart={() => start()} onShowFindings={showFindings} />

      {p.ci === "failure" && <CiDiagnosisCard repo={fullName} number={p.number} headSha={p.head_sha} />}

      {review.error && <ErrorBox error={review.error} onRetry={review.reload} />}

      <div className="tabs" role="tablist" id="findings">
        <button role="tab" aria-selected={tab === "review"} className={tab === "review" ? "active" : ""}
                onClick={() => setTab("review")}>Bulgular{current ? ` (${findings.length})` : ""}</button>
        <button role="tab" aria-selected={tab === "diff"} className={tab === "diff" ? "active" : ""}
                onClick={() => setTab("diff")}>Kod değişiklikleri ({p.files.length})</button>
      </div>

      <ReviewPanel review={current ?? null} loading={reviewId !== null && !r} pr={p} tab={tab}
                   setReview={(next) => review.setData(() => next)} onSubmitted={pr.reload} />

      <Collapsible title="Ayrıntılar" hint="İnceleme adımları, risk puanının dökümü, yorum hunisi, önceki review'lar">
        <div className="details-actions">
          {p.reviews.length > 1 && (
            <select className="input select" value={reviewId ?? ""} aria-label="Review seç"
                    onChange={(e) => setReviewId(Number(e.target.value))}>
              {p.reviews.map((x) => (
                <option key={x.id} value={x.id}>
                  Review #{x.id} · {timeAgo(x.created_at)} · {x.status}
                </option>
              ))}
            </select>
          )}
          {current?.mode === "incremental" && current.base_sha && (
            <Badge tone="info" title="Yalnızca son incelenen commit'ten sonraki değişiklikler incelendi">
              Artımlı · {current.base_sha.slice(0, 7)} → {current.head_sha.slice(0, 7)}
            </Badge>
          )}
          <span className="mono small muted">{p.head_ref} → {p.base_ref} · +{p.additions} −{p.deletions}</span>
          {current && (
            <button className="btn btn-sm" onClick={() => start(true)} disabled={starting || !canRerun}
                    title="Önceki review'ları yok sayıp tüm PR diff'ini baştan incele">
              Baştan incele
            </button>
          )}
        </div>
        <ProcessStepper review={current} />
        <RiskPanel risk={p.risk} ci={p.ci} />
        {(current?.status === "ready" || current?.status === "submitted") && <FunnelCard review={current} />}
      </Collapsible>
    </div>
  );
}

const SEVERITY_ORDER: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const SEVERITY_WORD: Record<Severity, string> = {
  CRITICAL: "kritik", HIGH: "yüksek", MEDIUM: "orta", LOW: "düşük", INFO: "bilgi",
};
const CI_WORD: Record<PullDetail["ci"], string | null> = {
  success: "CI geçti", failure: "CI başarısız", pending: "CI sürüyor", none: null,
};

/** The top of the PR page: what GitShield found, and the one thing to do next. */
function ResultCard({ pr, review, findings, starting, onStart, onShowFindings }: {
  pr: PullDetail;
  review: Review | null;
  findings: ReviewComment[];
  starting: boolean;
  onStart: () => void;
  onShowFindings: () => void;
}) {
  const sorted = [...findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  );
  const serious = findings.filter((c) => c.severity === "CRITICAL" || c.severity === "HIGH").length;
  const bySeverity = SEVERITY_ORDER.map((s) => [s, findings.filter((c) => c.severity === s).length] as const)
    .filter(([, n]) => n > 0);
  const outdated = !!review && review.head_sha !== pr.head_sha && pr.state === "open";
  const busyButton = (label: string, primary = true) => (
    <button className={`btn ${primary ? "btn-primary" : ""}`} onClick={onStart} disabled={starting}>
      {starting ? <span className="spinner" /> : label}
    </button>
  );

  let tone = "neutral";
  let headline: string;
  let todo: string;
  let action: ReactNode = null;

  if (!review) {
    headline = "Bu PR henüz incelenmedi";
    todo = "İncelemeyi başlat. Güvenlik taraması, AI review ve doğrulama kendiliğinden çalışır; bitince sonuç burada görünür.";
    action = pr.state === "open" ? busyButton("İncelemeyi başlat") : null;
  } else if (review.status === "running") {
    tone = "info";
    const step = review.progress?.find((s) => s.status === "running");
    headline = step ? `İnceleniyor: ${step.label}` : "İnceleniyor";
    todo = "Beklemen yeterli; sayfa kendiliğinden güncellenir.";
  } else if (review.status === "failed") {
    tone = "critical";
    headline = "İnceleme tamamlanamadı";
    todo = review.error ?? "Bilinmeyen bir hata oluştu.";
    action = busyButton("Yeniden dene", false);
  } else {
    tone = findings.length === 0 ? "success" : serious ? "critical" : "medium";
    headline = findings.length === 0
      ? "Sorun bulunmadı"
      : `${findings.length} sorun bulundu${serious ? ` — ${serious} tanesi yüksek önemde` : ""}`;
    if (outdated) {
      todo = "Bu sonuç eski bir commit için. PR'a yeni commit geldi; yeniden incelemek gerekiyor.";
      action = busyButton("Yeniden incele");
    } else if (review.status === "submitted") {
      todo = `Yapacak bir şey yok: review ${timeAgo(review.submitted_at)} GitHub'a gönderildi.`;
      action = review.github_review_url ? (
        <a className="btn" href={review.github_review_url} target="_blank" rel="noreferrer">GitHub'da gör ↗</a>
      ) : null;
    } else if (findings.length === 0) {
      todo = "Kısa özeti kontrol et ve onayı GitHub'a gönder.";
      action = <button className="btn btn-primary" onClick={onShowFindings}>Gönderime git ↓</button>;
    } else {
      todo = "Bulgulara göz at; gereksiz olanların işaretini kaldır, sonra review'u GitHub'a gönder.";
      action = <button className="btn btn-primary" onClick={onShowFindings}>Bulguları incele ↓</button>;
    }
  }

  const ci = CI_WORD[pr.ci];
  return (
    <section className={`result-card result-${tone}`}>
      <div className="result-main">
        <p className="result-label">GitShield sonucu</p>
        <h2 className="result-headline">{headline}</h2>
        {bySeverity.length > 0 && (
          <div className="result-counts">
            {bySeverity.map(([s, n]) => (
              <span key={s} className={`result-count sev-${s.toLowerCase()}`}>{n} {SEVERITY_WORD[s]}</span>
            ))}
          </div>
        )}
        {sorted.length > 0 && (
          <ul className="result-findings">
            {sorted.slice(0, 3).map((c) => (
              <li key={c.id}>
                <SeverityBadge severity={c.severity} />
                <a href={`#comment-${c.id}`} onClick={onShowFindings}>{c.title}</a>
                <span className="mono small muted">{c.path}{c.line !== null ? `:${c.line}` : ""}</span>
              </li>
            ))}
            {sorted.length > 3 && <li className="muted small">ve {sorted.length - 3} bulgu daha</li>}
          </ul>
        )}
        {review?.status === "running" && <ProcessStepper review={review} />}
        <div className="result-facts">
          <RiskWord risk={pr.risk} />
          {ci && <span className={pr.ci === "failure" ? "fact-bad" : ""}>{ci}</span>}
          {review && (review.status === "ready" || review.status === "submitted") && (
            <span>Önerilen karar: <VerdictBadge verdict={review.verdict} /></span>
          )}
        </div>
      </div>
      <div className={`result-todo ${review?.status === "failed" ? "todo-alert" : ""}`}>
        <p className="result-label">Ne yapmalısın?</p>
        <p>{todo}</p>
        {action}
      </div>
    </section>
  );
}

function ReviewPanel({ review: r, loading, pr, tab, setReview, onSubmitted }: {
  review: Review | null;
  loading: boolean;
  pr: PullDetail;
  tab: "review" | "diff";
  setReview: (r: Review) => void;
  onSubmitted: () => void;
}) {
  if (loading) return <Loading />;

  const setComment = (c: ReviewComment) =>
    r && setReview({ ...r, comments: r.comments.map((x) => (x.id === c.id ? c : x)) });

  if (tab === "diff") {
    return <DiffView pr={pr} comments={r?.comments ?? []} onChange={setComment} locked={r?.status !== "ready"} />;
  }
  if (!r) {
    return (
      <div className="empty big">
        Review sonuçları burada görünecek. Yukarıdan <strong>İncelemeyi başlat</strong>.
      </div>
    );
  }
  if (r.status === "running") {
    return <div className="empty big">Yorumlar adımlar tamamlanınca burada listelenecek.</div>;
  }
  if (r.status === "failed") return null;

  return <ReviewEditor key={r.id} review={r} pr={pr} setReview={setReview}
                       setComment={setComment} onSubmitted={onSubmitted} />;
}

const FUNNEL_SERIES: Series[] = [{ key: "n", label: "Yorum", color: "var(--series-1)" }];

type Filter = "all" | Verification | "included";

function ReviewEditor({ review, pr, setReview, setComment, onSubmitted }: {
  review: Review;
  pr: PullDetail;
  setReview: (r: Review) => void;
  setComment: (c: ReviewComment) => void;
  onSubmitted: () => void;
}) {
  const locked = review.status !== "ready";
  const [summary, setSummary] = useState(review.summary);
  const [verdict, setVerdict] = useState<Verdict>(review.verdict);
  const [filter, setFilter] = useState<Filter>("all");
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const comments = review.comments;
  const included = comments.filter((c) => c.included);
  const inline = included.filter((c) => c.in_diff);
  const outdated = review.head_sha !== pr.head_sha;

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: comments.length, included: included.length };
    for (const c of comments) out[c.verification] = (out[c.verification] ?? 0) + 1;
    return out;
  }, [comments, included.length]);

  const visible = comments.filter((c) =>
    filter === "all" ? true : filter === "included" ? c.included : c.verification === filter,
  );

  const saveMeta = async () => {
    if (summary === review.summary && verdict === review.verdict) return;
    try {
      setReview(await api.patchReview(review.id, { summary, verdict }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await saveMeta();
      const res = await api.submitReview(review.id, verdict);
      setReview(res.review);
      setConfirming(false);
      onSubmitted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="review">
      {outdated && (
        <div className="banner banner-warn">
          Bu review <span className="mono">{review.head_sha.slice(0, 7)}</span> commit'i için yapıldı; PR'a
          sonradan yeni commit geldi. Satır yorumları GitHub'da "outdated" görünebilir. Yeniden incelemen önerilir.
        </div>
      )}
      {review.skipped_files.length > 0 && (
        <div className="banner banner-warn">
          <strong>{review.skipped_files.length} dosya LLM'e gönderilmedi:</strong>{" "}
          {review.skipped_files.map((s) => `${s.path} (${s.reason})`).join(", ")}
        </div>
      )}

      <div className="filters">
        {(["all", "confirmed", "uncertain", "rejected", "unverified", "included"] as Filter[])
          .filter((f) => f === "all" || f === "included" || counts[f])
          .map((f) => (
            <button key={f} className={`chip ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>
              {FILTER_LABEL[f]} <span className="count">{counts[f] ?? 0}</span>
            </button>
          ))}
      </div>

      {visible.length === 0 ? (
        <div className="empty">{comments.length ? "Bu filtrede yorum yok." : "Hiç bulgu yok — temiz görünüyor. ✨"}</div>
      ) : (
        <div className="comment-list">
          {visible.map((c) => (
            <CommentCard key={c.id} comment={c} onChange={setComment} locked={locked} />
          ))}
        </div>
      )}

      {review.followups.length > 0 && <FollowupsCard followups={review.followups} />}

      <div className="card">
        <div className="card-head">
          <h3>GitHub'a gidecek özet ve karar</h3>
          <span className="muted small">{review.provider} {review.model} · {timeAgo(review.created_at)}</span>
        </div>
        <textarea className="input textarea" rows={5} value={summary} disabled={locked}
                  onChange={(e) => setSummary(e.target.value)} onBlur={saveMeta} />
        <div className="verdict-row">
          <label className="small muted" htmlFor="verdict">Karar</label>
          <select id="verdict" className="input select" value={verdict} disabled={locked}
                  onChange={(e) => setVerdict(e.target.value as Verdict)} onBlur={saveMeta}>
            {(["REQUEST_CHANGES", "COMMENT", "APPROVE"] as Verdict[]).map((v) => (
              <option key={v} value={v}>{verdictLabel(v)}</option>
            ))}
          </select>
          {review.recommended_verdict && review.recommended_verdict !== verdict && (
            <span className="small">
              Doğrulayıcı önerisi: <VerdictBadge verdict={review.recommended_verdict} />
            </span>
          )}
        </div>
      </div>

      {error && <ErrorBox error={error} />}

      <div className={`submit-bar ${review.status === "submitted" ? "is-done" : ""}`}>
        {review.status === "submitted" ? (
          <>
            <span>✓ GitHub'a gönderildi · {timeAgo(review.submitted_at)}</span>
            {review.github_review_url && (
              <a className="btn" href={review.github_review_url} target="_blank" rel="noreferrer">Review'u gör ↗</a>
            )}
          </>
        ) : confirming ? (
          <>
            <span>
              <strong>{included.length}</strong> yorum ({inline.length} satır içi, {included.length - inline.length} özet
              içinde) <VerdictBadge verdict={verdict} /> kararıyla <strong>{pr.author}</strong>'in PR'ına gönderilecek.
            </span>
            <div className="spacer" />
            <button className="btn btn-ghost" onClick={() => setConfirming(false)} disabled={submitting}>Vazgeç</button>
            <button className="btn btn-primary" onClick={submit} disabled={submitting}>
              {submitting ? <span className="spinner" /> : "Evet, gönder"}
            </button>
          </>
        ) : (
          <>
            <span className="muted">
              {included.length} / {comments.length} yorum seçili · reddedilenler varsayılan olarak hariç
            </span>
            <div className="spacer" />
            <button className="btn btn-primary" onClick={() => setConfirming(true)}>GitHub'a gönder…</button>
          </>
        )}
      </div>
    </div>
  );
}

/** How many comments were produced, survived verification and will be sent. */
function FunnelCard({ review }: { review: Review }) {
  const comments = review.comments;
  const included = comments.filter((c) => c.included);
  return (
    <ChartCard title="Yorum hunisi"
               subtitle={`${review.stats.scanner_findings ?? 0} tarayıcı bulgusu · ${review.stats.llm_comments ?? 0} AI yorumu`}>
      <StackedBarList series={FUNNEL_SERIES} empty="Hiç yorum üretilmedi — PR temiz görünüyor." rows={
        comments.length ? [
          { key: "Üretilen", label: "Üretilen", values: { n: comments.length } },
          { key: "Doğrulamayı geçen", label: "Doğrulamayı geçen",
            values: { n: comments.filter((c) => c.verification !== "rejected").length } },
          { key: "Gönderilecek", label: "Gönderilecek", values: { n: included.length } },
          { key: "Satır içi", label: "Satır içi", values: { n: included.filter((c) => c.in_diff).length } },
        ] : []} />
      {review.verifier_notes && <p className="small verifier-note">{review.verifier_notes}</p>}
    </ChartCard>
  );
}

const FILTER_LABEL: Record<Filter, string> = {
  all: "Tümü",
  confirmed: "Doğrulanan",
  uncertain: "Belirsiz",
  rejected: "Reddedilen",
  unverified: "Doğrulanmamış",
  included: "Gönderilecek",
};

function CommentCard({ comment: c, onChange, locked, compact }: {
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

function DiffView({ pr, comments, onChange, locked }: {
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

const FOLLOWUP: Record<Followup["status"], [string, string, string]> = {
  fixed: ["success", "✓", "Düzeltildi"],
  still_open: ["high", "●", "Hâlâ açık"],
  unclear: ["medium", "?", "Belirsiz"],
};

function FollowupsCard({ followups }: { followups: Followup[] }) {
  const count = (k: Followup["status"]) => followups.filter((f) => f.status === k).length;
  return (
    <ChartCard title="Önceki review'daki yorumlar"
               subtitle="Yeni commit'ler önceki yorumları çözdü mü? Dokunulmayan satırlar kesin olarak açık sayılır.">
      <CompositionBar parts={(["fixed", "unclear", "still_open"] as const).map((k, i) => ({
        key: k, label: FOLLOWUP[k][2], value: count(k), color: `var(--series-${[3, 1, 2][i]})`,
      }))} unit={(v) => `${v} yorum`} />
      <ul className="followups">
        {followups.map((f) => {
          const [tone, icon, label] = FOLLOWUP[f.status];
          return (
            <li key={f.id}>
              <Badge tone={tone}>{icon} {label}</Badge>
              <div className="followup-main">
                <div><SeverityBadge severity={f.severity} /> <strong>{f.title}</strong></div>
                <div className="muted small">
                  <span className="mono">{f.path}:{f.new_line ?? f.old_line}</span> · {f.note}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </ChartCard>
  );
}
