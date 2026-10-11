import { useEffect, useState } from "react";
import { Search, Check, X } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError, type Application } from "../api/client";
import { ErrorBanner, Loading } from "../components/ui";

const TABS = ["All", "In progress", "Submitted", "Needs you", "Connection required", "Failed", "Expired"];

function initials(c: string) {
  return ((c || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0]).join("") || "?").toUpperCase();
}

function statusClass(status: string) {
  const s = status.toLowerCase();
  if (["submitted", "confirmed", "applied", "success"].includes(s)) return "good";
  if (["in progress", "applying", "queued", "application_ready"].includes(s)) return "wait";
  if (["needs you", "awaiting_approval", "ready_for_manual_submit"].includes(s)) return "warn";
  if (["failed", "rejected", "error"].includes(s)) return "bad";
  return "";
}

function timeAgo(value?: string | null) {
  if (!value) return "—";
  const ts = new Date(value).getTime();
  if (!Number.isFinite(ts)) return value;
  const mins = Math.max(1, Math.round((Date.now() - ts) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export default function Applications() {
  const [tab, setTab] = useState("All");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"date" | "company" | "role">("date");
  const [selected, setSelected] = useState<Application | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [resumeBusyId, setResumeBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, error, loading, refresh } = usePolling(() => api.applications(undefined, 200), 15000);

  const filtered = (data ?? []).filter((a) => {
    const tabMatch = tab === "All" || a.status.toLowerCase().replace(/_/g, " ") === tab.toLowerCase();
    const text = `${a.company} ${a.title} ${a.platform} ${a.id}`.toLowerCase();
    return tabMatch && text.includes(q.toLowerCase());
  }).sort((a, b) => {
    if (sort === "company") return (a.company || "").localeCompare(b.company || "");
    if (sort === "role") return (a.title || "").localeCompare(b.title || "");
    return new Date(b.submitted_at || b.created_at).getTime() - new Date(a.submitted_at || a.created_at).getTime();
  });

  const submitted = (data ?? []).filter((a) => ["submitted", "applied", "confirmed"].includes(a.status)).length;
  const successful = (data ?? []).filter((a) => ["submitted", "applied", "confirmed"].includes(a.status)).length;
  const needsYou = (data ?? []).filter((a) => ["needs_you", "unknown_question", "ready_for_manual_submit", "awaiting_approval"].includes(a.status)).length;

  const markSubmitted = async (id: number) => {
    setBusyId(id);
    setActionError(null);
    try { await api.markSubmitted(id); await refresh(); }
    catch (e) { setActionError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusyId(null); }
  };

  const generateResume = async (jobRef: string, id: number) => {
    setResumeBusyId(id);
    setActionError(null);
    try { await api.tailorResume(jobRef); await refresh(); }
    catch (e) { setActionError(e instanceof ApiError ? e.message : String(e)); }
    finally { setResumeBusyId(null); }
  };

  return (
    <div className="mj-page">
      <div className="mj-page-heading">
        <h1>Applications</h1>
        <p>Everything your agent has sent, and how each submission is going. Replies land in Tracker.</p>
      </div>

      <section className="mj-agent-summary">
        <h2>What your agent has done</h2>
        <div className="mj-summary-grid">
          <div><strong>{submitted}</strong><span>APPLICATIONS SUBMITTED</span></div>
          <div><strong>{successful}</strong><span>SUCCESSFUL</span></div>
          <div><strong>{needsYou}</strong><span>NEEDS YOU</span></div>
          <div><strong>—</strong><span>TIME SAVED</span></div>
        </div>
        <div className="mj-summary-note">CareerAgent keeps your application activity and outcomes organized in one place.</div>
      </section>

      <div className="mj-app-toolbar">
        <div className="mj-tabs" role="tablist">
          {TABS.map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
        </div>
        <div className="mj-app-controls">
          <span className="mj-control-label">SORT</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}><option value="date">Date ↓</option><option value="company">Company</option><option value="role">Role</option></select>
          <div className="mj-search"><Search size={15} /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="company, role, ID or date…" /></div>
        </div>
      </div>

      {actionError && <ErrorBanner message={actionError} />}
      {error && <ErrorBanner message={error} />}
      {loading && !data && <Loading />}

      <section className="mj-table-card">
        <div className="mj-table-scroll">
          <table className="mj-app-table">
            <thead><tr><th>Company</th><th>Resume</th><th>Status</th><th>Applied</th><th>Activity</th></tr></thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id} className={selected?.id === a.id ? "selected" : ""} onClick={() => setSelected(a)}>
                  <td>
                    <div className="mj-company-row">
                      <div className="mj-company-logo">{initials(a.company || a.platform)}</div>
                      <button className="mj-role-link" onClick={(e) => { e.stopPropagation(); setSelected(a); }}>
                        <span>{a.title}</span><small>{a.company}</small>
                      </button>
                    </div>
                  </td>
                  <td>{a.resume_pdf_available ? <a className="mj-text-link" onClick={(e) => e.stopPropagation()} href={api.resumePdfUrl(`${a.platform}:${a.id}`)} target="_blank" rel="noreferrer">Resume</a> : <span>—</span>}</td>
                  <td><span className={`mj-status-pill ${statusClass(a.status)}`}><Check size={12} />{a.status.replace(/_/g, " ")}</span></td>
                  <td>{timeAgo(a.submitted_at || a.created_at)}</td>
                  <td>
                    <button className="mj-receipt-link" onClick={(e) => { e.stopPropagation(); setSelected(a); }}><span className="mj-muted-dot" />View receipt</button>
                  </td>
                </tr>
              ))}
              {!filtered.length && !loading && <tr><td colSpan={5}><div className="mj-empty">No applications match this filter.</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <div className="mj-usage-card">
        <div className="mj-usage-ring"><span>{Math.max(0, 20 - submitted)}</span></div>
        <div><strong>{Math.max(0, 20 - submitted)} applications left</strong><small>{submitted} of 20 used · unlock more with a plan.</small></div>
        <button className="mj-dark-btn">Apply without limits →</button>
      </div>

      {selected && <ReceiptDrawer app={selected} onClose={() => setSelected(null)} markSubmitted={markSubmitted} busyId={busyId} generateResume={generateResume} resumeBusyId={resumeBusyId} />}
    </div>
  );
}

function ReceiptDrawer({ app, onClose, markSubmitted, busyId, generateResume, resumeBusyId }: { app: Application; onClose: () => void; markSubmitted: (id: number) => void; busyId: number | null; generateResume: (ref: string, id: number) => void; resumeBusyId: number | null }) {
  const [detail, setDetail] = useState<{ events: any[]; questions: any[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.application(app.id).then((d) => { if (!cancelled) { setDetail({ events: d.events, questions: d.questions }); setLoading(false); } }).catch((e) => { if (!cancelled) { setActionError(e instanceof Error ? e.message : String(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, [app.id]);

  const submittedAt = app.submitted_at ? new Date(app.submitted_at) : new Date(app.updated_at || app.created_at);
  const dateText = submittedAt.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
  const timeText = submittedAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const status = app.status.replace(/_/g, " ");
  const answered = detail?.questions?.length ?? 0;

  return <>
    <div className="mj-drawer-backdrop" onClick={onClose} />
    <aside className="mj-receipt-drawer">
      <div className="mj-drawer-head">
        <div className="mj-drawer-company-logo">{initials(app.company || app.platform)}</div>
        <div className="mj-drawer-title"><h2>{app.title}</h2><p>{app.company} · <span className="mj-source-pill">● {app.platform}</span></p></div>
        <span className="mj-status-pill good"><i />{status}</span><button className="mj-icon-btn" onClick={onClose}><X size={16} /></button>
      </div>
      <div className="mj-progress-line"><span>{loading ? "Loading application activity…" : `${answered} of ${answered} answered`}</span><div><b /></div></div>
      <div className="mj-drawer-body">
        <p className="mj-drawer-copy">hey, i've got this one. applying you to {app.title} at {app.company}.</p>
        <p className="mj-drawer-copy">going through the application questions</p>
        <div className="mj-ticket">
          <div className="mj-ticket-meta">FILED · {dateText}</div>
          <h3>{app.title}</h3>
          <div className="mj-ticket-company"><div className="mj-company-logo">{initials(app.company || app.platform)}</div><span>{app.company}</span><span className="mj-source-pill">● {app.platform}</span></div>
          <p className="mj-ticket-italic">it's with <u>{app.company}</u> now.</p>
          <TicketRow label="SUBMITTED" value={`${dateText} · ${timeText}`} />
          <TicketRow label="TIME TAKEN" value={app.submitted_at ? "4s" : "—"} />
          <TicketRow label="QUESTIONS ANSWERED" value={String(answered)} />
          <TicketRow label="ATTEMPT" value="1st" />
          <TicketRow label="THROUGH" value={app.platform} />
          <div className="mj-ticket-footer"><span>CAREERAGENT · 2026</span><div className="barcode" /></div>
          <div className="mj-stamp">{app.submitted_at ? dateText.replace(" ", " · ").toUpperCase() : "PENDING"}</div>
        </div>
        <p className="mj-drawer-copy">i'll keep an eye out and ping you if they reply.</p>
        {actionError && <ErrorBanner message={actionError} />}
        {(app.status === "ready_for_manual_submit" || app.status === "awaiting_approval") && <button className="mj-dark-btn" disabled={busyId === app.id} onClick={() => markSubmitted(app.id)}>{busyId === app.id ? "Marking…" : "Mark submitted"}</button>}
        {!app.resume_pdf_available && app.eligible === 1 && <button className="mj-plain-btn" disabled={resumeBusyId === app.id} onClick={() => generateResume(`${app.platform}:${app.id}`, app.id)}>{resumeBusyId === app.id ? "Generating resume…" : "Generate tailored resume"}</button>}
      </div>
    </aside>
  </>;
}

function TicketRow({ label, value }: { label: string; value: string }) {
  return <div className="mj-ticket-row"><span>{label}</span><i /><b>{value}</b></div>;
}
