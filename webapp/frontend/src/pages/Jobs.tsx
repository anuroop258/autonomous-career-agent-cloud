import { useState } from "react";
import { Link } from "react-router-dom";
import type { CSSProperties } from "react";
import { Search, MapPin, LayoutGrid, Table2 } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError, type Job } from "../api/client";
import { Loading, ErrorBanner, EmptyState, StatusBadge, PageHeader } from "../components/ui";

const PORTALS = ["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"];
const PAGE = 60;

const refOf = (j: Job) => j.job_ref || `${j.source}:${j.id}`;
function initials(c: string) {
  return ((c || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0]).join("") || "?").toUpperCase();
}

export default function Jobs() {
  const [q, setQ] = useState("");
  const [portal, setPortal] = useState("");
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [view, setView] = useState<"table" | "cards">("cards");
  const [shown, setShown] = useState(PAGE);
  const [tailoring, setTailoring] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, refresh } = usePolling(
    () => api.jobs({ portal: portal || undefined, eligible: eligibleOnly ? true : undefined, q: q || undefined }),
    6000,
    [q, portal, eligibleOnly],
  );

  const tailor = async (jobRef: string) => {
    setTailoring(jobRef);
    setActionError(null);
    try {
      await api.tailorResume(jobRef);
      refresh();
    } catch (e) {
      setActionError(e instanceof ApiError ? `Job ${jobRef}: ${e.message}` : String(e));
    } finally {
      setTailoring(null);
    }
  };

  const rows = (data ?? []).slice(0, shown);

  return (
    <div className="reference-page">
      <PageHeader
        title="Jobs"
        subtitle="Discovered, matched and de-duplicated jobs from the shared database."
        actions={
          <div className="view-toggle">
            <button className={view === "table" ? "on" : ""} onClick={() => setView("table")}><Table2 size={13} style={{ display: "inline", marginRight: 5 }} />Table</button>
            <button className={view === "cards" ? "on" : ""} onClick={() => setView("cards")}><LayoutGrid size={13} style={{ display: "inline", marginRight: 5 }} />Cards</button>
          </div>
        }
      />

      <div className="filter-row" style={{ alignItems: "center" }}>
        <div style={{ position: "relative" }}>
          <Search size={16} style={{ position: "absolute", left: 14, top: 12, color: "#8a857b" }} />
          <input className="reference-search" style={{ paddingLeft: 38 }} value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE); }} placeholder="Search title or company…" />
        </div>
        <select className="reference-select" value={portal} onChange={(e) => { setPortal(e.target.value); setShown(PAGE); }}>
          <option value="">All portals</option>
          {PORTALS.map((p) => <option key={p} value={p} style={{ textTransform: "capitalize" }}>{p}</option>)}
        </select>
        <label className="my-chip" style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
          <input type="checkbox" checked={eligibleOnly} onChange={(e) => { setEligibleOnly(e.target.checked); setShown(PAGE); }} />
          Eligible only
        </label>
        {data && <span style={{ color: "#8a857b", fontSize: 13 }}>{data.length} job{data.length === 1 ? "" : "s"}</span>}
      </div>

      {actionError && <ErrorBanner message={actionError} />}
      {error && <ErrorBanner message={error} />}
      {loading && !data && <Loading />}
      {data && data.length === 0 && <div className="my-application-card"><EmptyState label="No jobs found. Run a search from Job Search." /></div>}

      {data && data.length > 0 && view === "table" && (
        <div className="my-application-card">
          <table className="my-table">
            <thead>
              <tr>
                <th>Company</th><th>Title</th><th>Portal</th><th>JD match</th><th>Eligible</th>
                <th>Application</th><th>Resume</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((j) => {
                const ref = refOf(j);
                const busy = tailoring === ref;
                return (
                  <tr key={ref}>
                    <td><div className="company-cell"><div className="mini-logo">{initials(j.company)}</div>{j.company || "—"}</div></td>
                    <td style={{ whiteSpace: "normal", maxWidth: 360 }}>
                      <Link to={`/jobs/${encodeURIComponent(ref)}`} className="link-btn" style={{ fontSize: 13.5 }}>{j.title}</Link>
                    </td>
                    <td style={{ textTransform: "capitalize" }}>{j.source}</td>
                    <td>{j.match_score != null ? Math.round(j.match_score) : "—"}</td>
                    <td>{j.eligible == null ? "—" : Number(j.eligible) === 1 ? <StatusBadge status="OK" /> : <StatusBadge status="FAIL" />}</td>
                    <td>{j.application_status ? <StatusBadge status={j.application_status} /> : <span style={{ color: "#a09a8f" }}>none</span>}</td>
                    <td>
                      {j.resume_pdf_available ? (
                        <a href={api.resumePdfUrl(ref)} target="_blank" rel="noreferrer" className="link-btn">Open resume</a>
                      ) : Number(j.eligible) === 1 ? (
                        <button className="link-btn" disabled={busy} onClick={() => tailor(ref)}>{busy ? "Generating…" : "Generate resume"}</button>
                      ) : (
                        <span style={{ fontSize: 12, color: "#a09a8f" }}>Not generated</span>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="my-btn soft" style={{ padding: "5px 12px", fontSize: 12.5 }} disabled={busy} onClick={() => tailor(ref)}>{busy ? "Tailoring…" : "Tailor resume"}</button>
                        {j.url && <a href={j.url} target="_blank" rel="noreferrer" className="my-btn" style={{ padding: "5px 12px", fontSize: 12.5 }}>Open</a>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && data.length > 0 && view === "cards" && (
        <div className="my-job-grid">
          {rows.map((j) => {
            const ref = refOf(j);
            const busy = tailoring === ref;
            const sc = j.match_score == null ? null : Math.max(0, Math.min(99, Math.round(j.match_score)));
            return (
              <article key={ref} className="job-card">
                <div className="job-top">
                  <div className="company-logo">{initials(j.company || j.source)}</div>
                  <div className="company-info">
                    <div className="company-name">{j.company || "Company not captured"}</div>
                    <span className="via">via <strong>{j.source}</strong></span>
                  </div>
                  <div className="score-wrap">
                    <div className="score-ring" style={{ "--pct": `${sc ?? 0}%` } as CSSProperties}><div className="score-inner">{sc == null ? "—" : `${sc}%`}</div></div>
                    <span className="score-label">{j.eligible === 1 ? "Eligible" : j.eligible === 0 ? "Ineligible" : "Not scored"}</span>
                  </div>
                </div>
                <div className="job-body">
                  <h3 className="job-title">{j.title}</h3>
                  <div className="job-posted">found {j.discovered_at ? new Date(j.discovered_at).toLocaleDateString() : "recently"}</div>
                  <div className="tag-row">
                    {j.location && <span className="tag"><MapPin size={12} />{j.location}</span>}
                    {j.application_status && <span className="tag blue">{j.application_status.replace(/_/g, " ")}</span>}
                    {(j.matched_skills || []).slice(0, 2).map((s) => <span key={s} className="tag gold">{s}</span>)}
                  </div>
                  <p className="why">{j.matched_skills?.length ? `Matched: ${j.matched_skills.join(", ")}` : j.description?.slice(0, 120) || "No match explanation stored yet."}</p>
                  <div className="card-actions">
                    <Link to={`/jobs/${encodeURIComponent(ref)}`}><button style={{ width: "100%" }}>View</button></Link>
                    {j.url ? <a href={j.url} target="_blank" rel="noreferrer"><button style={{ width: "100%" }}>Open</button></a> : <button disabled>No link</button>}
                    {j.resume_pdf_available
                      ? <a href={api.resumePdfUrl(ref)} target="_blank" rel="noreferrer"><button className="apply" style={{ width: "100%" }}>Resume</button></a>
                      : <button className="apply" disabled={busy} onClick={() => tailor(ref)}>{busy ? "…" : "Tailor"}</button>}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {data && data.length > shown && (
        <div style={{ textAlign: "center", marginTop: 18 }}>
          <button className="my-btn dark" onClick={() => setShown((n) => n + PAGE)}>Show more ({data.length - shown} left)</button>
        </div>
      )}
    </div>
  );
}      <div className="mj-page-heading jobs-heading">
        <h1>Jobs for you</h1>
        <p>The whole feed your agent works from. Sorted by what fits you best.</p>
      </div>
