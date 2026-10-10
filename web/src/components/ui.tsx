import { ReactNode, useState } from "react";
import type { Label, ReviewStatus, Severity, Verdict, Verification } from "../api";

export function Badge({ tone = "neutral", children, title }: {
  tone?: string;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity, string> = {
  CRITICAL: "critical",
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
  INFO: "neutral",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEVERITY_TONE[severity]}>{severity}</Badge>;
}

const VERDICT_LABEL: Record<Verdict, string> = {
  APPROVE: "Onay",
  REQUEST_CHANGES: "Değişiklik iste",
  COMMENT: "Yorum",
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const tone = verdict === "APPROVE" ? "success" : verdict === "REQUEST_CHANGES" ? "high" : "info";
  return <Badge tone={tone}>{VERDICT_LABEL[verdict]}</Badge>;
}

export const verdictLabel = (v: Verdict) => VERDICT_LABEL[v];

const VERIFICATION: Record<Verification, [string, string]> = {
  confirmed: ["success", "✓ Doğrulandı"],
  rejected: ["muted", "✕ Reddedildi"],
  uncertain: ["medium", "? Belirsiz"],
  unverified: ["neutral", "Doğrulanmadı"],
};

export function VerificationBadge({ value, note }: { value: Verification; note?: string }) {
  const [tone, label] = VERIFICATION[value];
  return (
    <Badge tone={tone} title={note || undefined}>
      {label}
    </Badge>
  );
}

export function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  switch (status) {
    case "running":
      return (
        <Badge tone="info">
          <span className="spinner" /> İnceleniyor
        </Badge>
      );
    case "failed":
      return <Badge tone="critical">Hata</Badge>;
    case "submitted":
      return <Badge tone="success">Gönderildi</Badge>;
    default:
      return <Badge tone="info">Onay bekliyor</Badge>;
  }
}

export function LabelChip({ label }: { label: Label }) {
  return (
    <span className="label-chip">
      <span className="label-dot" style={{ background: `#${label.color}` }} />
      {label.name}
    </span>
  );
}

export function Collapsible({ title, count, defaultOpen = false, hint, children }: {
  title: ReactNode;
  count?: number;
  defaultOpen?: boolean;
  hint?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={`collapsible ${open ? "open" : ""}`}>
      <button className="collapsible-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="chevron" aria-hidden>
          ▸
        </span>
        <span className="collapsible-title">{title}</span>
        {count !== undefined && <span className="count">{count}</span>}
        {hint && <span className="collapsible-hint">{hint}</span>}
      </button>
      {open && <div className="collapsible-body">{children}</div>}
    </section>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <span>{error}</span>
      {onRetry && (
        <button className="btn btn-ghost btn-sm" onClick={onRetry}>
          Tekrar dene
        </button>
      )}
    </div>
  );
}

const SKELETON_WIDTHS = [92, 76, 84, 64, 88, 70];

/** Shimmering placeholder rows shaped like a list, with the label kept for screen readers. */
export function Loading({ label = "Yükleniyor", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div className="skeleton" role="status" aria-live="polite">
      <div className="skeleton-label"><span className="spinner" /> {label}…</div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-row">
          <span className="sk sk-avatar" />
          <span className="sk sk-line" style={{ width: `${SKELETON_WIDTHS[i % SKELETON_WIDTHS.length]}%` }} />
        </div>
      ))}
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function Switch({ checked, onChange, label, hint, disabled }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={`switch ${disabled ? "disabled" : ""}`}>
      <input type="checkbox" role="switch" checked={checked} disabled={disabled}
             onChange={(e) => onChange(e.target.checked)} />
      <span className="switch-track" aria-hidden><span className="switch-thumb" /></span>
      <span className="switch-text">
        <span className="switch-label">{label}</span>
        {hint && <span className="switch-hint">{hint}</span>}
      </span>
    </label>
  );
}
