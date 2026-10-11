import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

export function StatusBadge({ status }: { status: string }) {
  const s = status.toUpperCase();
  const cls =
    s === "OK" || s === "CONNECTED" || s === "SUCCESS" || s === "APPROVED" || s === "SENT" || s === "SUBMITTED" || s === "CONFIRMED" || s === "RUNNING"
      ? "badge-ok"
      : s === "WARN" || s === "PENDING" || s === "QUEUED" || s === "AWAITING_APPROVAL" || s === "DRAFT" || s === "STOPPING"
      ? "badge-warn"
      : s === "FAIL" || s === "ERROR" || s === "REJECTED" || s === "FAILED" || s === "DISCONNECTED"
      ? "badge-fail"
      : "badge-neutral";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function EmptyState({ label }: { label: string }) {
  return (
    <div className="my-empty-state">
      <Inbox size={28} />
      <p style={{ margin: 0, fontSize: 14 }}>{label}</p>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="my-error">
      <AlertTriangle size={16} style={{ marginTop: 2, flex: "none" }} />
      <span>{message}</span>
    </div>
  );
}

export function Loading() {
  return (
    <div className="my-loading">
      <Loader2 size={16} className="animate-spin" /> Loading…
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="reference-toolbar">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="my-actions">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className={`stat-card ${accent ? "accent" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

/** Shared page wrapper so every page gets the same width/padding as the dashboard. */
export function Page({ children }: { children: ReactNode }) {
  return <div className="reference-page">{children}</div>;
}

export function KV({ rows }: { rows: Array<[string, string | number]> }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
