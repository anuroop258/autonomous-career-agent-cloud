import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search, ArrowUpRight, BriefcaseBusiness, CircleCheck, CircleAlert, Hand } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, type Application } from "../api/client";
import { Loading, ErrorBanner } from "../components/ui";

type TrackerColumn = {
  id: string;
  title: string;
  match: (status: string) => boolean;
  tone: "neutral" | "action" | "progress" | "success" | "attention";
};

// Preserve real backend statuses; the labels are presentation-only.
const COLUMNS: TrackerColumn[] = [
  { id: "queued", title: "Queued", match: (s) => ["discovered", "application_ready", "queued"].includes(s), tone: "neutral" },
  { id: "needs-you", title: "Needs you", match: (s) => ["awaiting_approval", "ready_for_manual_submit", "unknown_question", "security_check", "answer_not_verified", "application_incomplete", "external_partial", "external_filled", "native_flow_stopped", "external_blocked", "blocked"].includes(s), tone: "action" },
  { id: "applying", title: "Applying", match: (s) => ["applying", "native_dry_run"].includes(s), tone: "progress" },
  { id: "submitted", title: "Submitted", match: (s) => ["submitted", "applied", "external_applied"].includes(s), tone: "success" },
  { id: "confirmed", title: "Confirmed", match: (s) => s === "confirmed", tone: "success" },
  { id: "issues", title: "Issues & skipped", match: (s) => /error|failed|rejected|skipped/.test(s) || ["apply_not_found", "external_apply_not_reached", "match_found_no_direct_apply", "low_match", "experience_mismatch", "not_applied"].includes(s), tone: "attention" },
];

const FILTERS = [
  { id: "all", label: "All applications", match: (_s: string) => true },
  { id: "needs-you", label: "Needs you", match: (s: string) => COLUMNS[1].match(s) },
  { id: "active", label: "In progress", match: (s: string) => COLUMNS[0].match(s) || COLUMNS[2].match(s) },
  { id: "submitted", label: "Submitted", match: (s: string) => COLUMNS[3].match(s) || COLUMNS[4].match(s) },
  { id: "issues", label: "Issues & skipped", match: (s: string) => COLUMNS[5].match(s) },
];

function niceStatus(status: string) {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function displayCompany(company: string | null | undefined) {
  if (!company || ["unknown_company", "unknown company", "n/a", "null"].includes(company.trim().toLowerCase())) return "Company not detected";
  return company;
}

function displayTitle(title: string | null | undefined) {
  if (!title || ["unknown_role", "unknown role", "n/a", "null"].includes(title.trim().toLowerCase())) return "Role not detected";
  return title;
}

export default function Tracker() {
  const { data, error, loading } = usePolling(() => api.applications(undefined, 200), 15000);
  const [activeFilter, setActiveFilter] = useState("all");
  const [query, setQuery] = useState("");
  const all: Application[] = data || [];

  const summary = useMemo(() => ({
    total: all.length,
    needsYou: all.filter((a) => COLUMNS[1].match(a.status)).length,
    submitted: all.filter((a) => COLUMNS[3].match(a.status) || COLUMNS[4].match(a.status)).length,
    issues: all.filter((a) => COLUMNS[5].match(a.status)).length,
  }), [all]);

  const visibleApplications = useMemo(() => {
    const filter = FILTERS.find((f) => f.id === activeFilter) || FILTERS[0];
    const q = query.trim().toLowerCase();
    return all.filter((a) => filter.match(a.status) && (!q || `${a.title} ${a.company} ${a.platform} ${a.status} ${a.location}`.toLowerCase().includes(q)));
  }, [all, activeFilter, query]);

  const columns = useMemo(() => {
    const known = new Set<number>();
    const grouped = COLUMNS.map((c) => {
      const items = visibleApplications.filter((a) => c.match(a.status));
      items.forEach((a) => known.add(a.id));
      return { ...c, items };
    });
    const other = visibleApplications.filter((a) => !known.has(a.id));
    if (other.length) grouped.push({ id: "other", title: "Other statuses", match: (_s: string) => true, tone: "neutral" as const, items: other });
    return grouped;
  }, [visibleApplications]);

  return (
    <div className="tracker-page">
      <div className="tracker-heading">
        <div>
          <div className="tracker-eyebrow">APPLICATION TRACKER</div>
          <h1>Tracker</h1>
          <p>See what is moving, what needs your attention, and what has been submitted.</p>
        </div>
        <label className="tracker-search">
          <Search size={16} aria-hidden="true" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search role, company, portal…" aria-label="Search tracker" />
          {query && <button type="button" onClick={() => setQuery("")} aria-label="Clear search">×</button>}
        </label>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="tracker-summary" aria-label="Application summary">
        <div className="tracker-stat"><span className="tracker-stat-icon"><BriefcaseBusiness size={17} /></span><div><strong>{summary.total}</strong><span>Applications tracked</span></div></div>
        <div className="tracker-stat action"><span className="tracker-stat-icon"><Hand size={17} /></span><div><strong>{summary.needsYou}</strong><span>Need your attention</span></div></div>
        <div className="tracker-stat success"><span className="tracker-stat-icon"><CircleCheck size={17} /></span><div><strong>{summary.submitted}</strong><span>Submitted / confirmed</span></div></div>
        <div className="tracker-stat issue"><span className="tracker-stat-icon"><CircleAlert size={17} /></span><div><strong>{summary.issues}</strong><span>Issues / skipped</span></div></div>
      </div>

      <div className="tracker-filter-row" role="group" aria-label="Filter applications by status">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className={`tracker-filter ${activeFilter === f.id ? "active" : ""}`} onClick={() => setActiveFilter(f.id)}>
            {f.label}
            {f.id === "all" && <span>{summary.total}</span>}
            {f.id === "needs-you" && <span>{summary.needsYou}</span>}
            {f.id === "submitted" && <span>{summary.submitted}</span>}
            {f.id === "issues" && <span>{summary.issues}</span>}
          </button>
        ))}
        <span className="tracker-results">Showing {visibleApplications.length} of {summary.total}</span>
      </div>

      {loading && !data ? <Loading /> : visibleApplications.length === 0 ? (
        <div className="tracker-empty">
          <div className="tracker-empty-mark"><Search size={20} /></div>
          <h2>No applications found</h2>
          <p>{query ? "Try another search term or clear the search." : "Applications will appear here as the agent discovers and processes jobs."}</p>
          {(query || activeFilter !== "all") && <button type="button" className="my-btn dark" onClick={() => { setQuery(""); setActiveFilter("all"); }}>Clear filters</button>}
        </div>
      ) : (
        <div className="tracker-board-wrap">
          <div className="tracker-board" aria-label="Applications grouped by status">
            {columns.filter((c) => activeFilter === "all" || c.items.length > 0).map((column) => (
              <section key={column.id} className={`tracker-column tone-${column.tone}`} aria-label={column.title}>
                <header className="tracker-column-head">
                  <span className="tracker-column-mark" />
                  <h2>{column.title}</h2>
                  <span className="tracker-count">{column.items.length}</span>
                </header>
                <div className="tracker-column-cards">
                  {column.items.length === 0 ? (
                    <div className="tracker-column-empty">Nothing here yet</div>
                  ) : column.items.map((application) => (
                    <article key={application.id} className="tracker-card">
                      <div className="tracker-card-top">
                        <span className={`tracker-status status-${column.tone}`}>{niceStatus(application.status)}</span>
                        <span className="tracker-portal">{application.platform || "Portal unknown"}</span>
                      </div>
                      <h3>{displayTitle(application.title)}</h3>
                      <p className="tracker-company">{displayCompany(application.company)}</p>
                      {application.location && <p className="tracker-location">{application.location}</p>}
                      {application.last_error && <p className="tracker-error" title={application.last_error}>{application.last_error}</p>}
                      <div className="tracker-card-footer">
                        <span>{application.updated_at ? new Date(application.updated_at).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : ""}</span>
                        <Link to={`/jobs/${application.platform}:${application.id}`} className="tracker-details">View details <ArrowUpRight size={14} /></Link>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
          <div className="tracker-scroll-hint">Scroll horizontally to see every status <span aria-hidden="true">→</span></div>
        </div>
      )}
    </div>
  );
}
