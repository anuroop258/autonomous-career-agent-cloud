import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { MapPin, Bookmark, ExternalLink } from "lucide-react";
import heroUrl from "../assets/myjobb-hero.avif";
import { usePolling } from "../hooks/usePolling";
import { api, type Job, type Application } from "../api/client";
import { ErrorBanner, Loading, EmptyState, StatCard } from "../components/ui";

function initials(company: string) {
  const parts = (company || "").trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map((x) => x[0]).join("") || "?").toUpperCase();
}
const score = (job: Job) => (job.match_score == null ? null : Math.max(0, Math.min(99, Math.round(job.match_score))));

function statusClass(status: string) {
  const s = status.toLowerCase();
  if (s.includes("submitted") || s.includes("confirmed")) return "good";
  if (s.includes("applying") || s.includes("progress") || s.includes("approval")) return "wait";
  if (s.includes("fail") || s.includes("reject") || s.includes("error")) return "bad";
  return "warn";
}

function JobCard({ job, saved, onSave }: { job: Job; saved: boolean; onSave: (id: number) => void }) {
  const sc = score(job);
  const tags: Array<{ t: string; c: string }> = [];
  if (job.location) tags.push({ t: job.location, c: "" });
  if (job.application_route && job.application_route !== "unknown") {
    tags.push({ t: job.application_route === "external" ? "External apply" : "Native apply", c: "blue" });
  }
  if (job.eligible === 1) tags.push({ t: "Eligible", c: "green" });
  else if (job.eligible === 0) tags.push({ t: "Not eligible", c: "pink" });
  (job.matched_skills || []).slice(0, 2).forEach((s) => tags.push({ t: s, c: "gold" }));
  return (
    <article className="job-card">
      <div className="job-top">
        <div className="company-logo">{initials(job.company || job.source)}</div>
        <div className="company-info">
          <div className="company-name">{job.company || "Company not captured"}</div>
          <span className="via">via <strong>{job.source}</strong></span>
        </div>
        <div className="score-wrap">
          <div className="score-ring" style={{ "--pct": `${sc ?? 0}%` } as CSSProperties}>
            <div className="score-inner">{sc == null ? "—" : `${sc}%`}</div>
          </div>
          <span className="score-label">{sc == null ? "Not scored" : job.eligible === 1 ? "Worth applying" : "Review"}</span>
        </div>
      </div>
      <div className="job-body">
        <h3 className="job-title">{job.title}</h3>
        <div className="job-posted">found {job.discovered_at ? new Date(job.discovered_at).toLocaleDateString() : "recently"}</div>
        <div className="tag-row">
          {tags.map((t, i) => <span key={`${t.t}-${i}`} className={`tag ${t.c}`}>{i === 0 && t.c === "" && <MapPin size={12} />}{t.t}</span>)}
        </div>
        <p className="why">
          {job.matched_skills?.length ? `Matches ${job.matched_skills.slice(0, 4).join(", ")}.` : job.description?.slice(0, 110) || "No match explanation stored yet."}
        </p>
        <div className="card-actions">
          <button className={saved ? "my-btn soft" : ""} onClick={() => onSave(job.id)}><Bookmark size={14} style={{ display: "inline", marginRight: 4 }} />{saved ? "Saved" : "Save"}</button>
          {job.url ? <a href={job.url} target="_blank" rel="noreferrer"><button style={{ width: "100%" }}>Open</button></a> : <button disabled>No link</button>}
          <Link to={`/jobs/${encodeURIComponent(job.job_ref)}`}><button className="apply" style={{ width: "100%" }}>Details</button></Link>
        </div>
      </div>
    </article>
  );
}

export default function Dashboard() {
  const { data, error, loading } = usePolling(() => api.dashboard(), 20000);
  const { data: cfg } = usePolling(() => api.config(), 60000);
  const { data: run } = usePolling(() => api.automationStatus(), 8000);

  const apps = data?.recent_applications ?? [];
  const jobs = data?.top_jobs ?? [];
  const attention = data?.needs_attention ?? [];

  const derived = useMemo(() => {
    const list = apps;
    const portals = new Map<string, { name: string; count: number; submitted: number }>();
    const stages = new Map<string, number>();
    for (const a of list) {
      const r = portals.get(a.platform) ?? { name: a.platform, count: 0, submitted: 0 };
      r.count++;
      if (a.status === "submitted" || a.status === "applied" || a.status === "confirmed") r.submitted++;
      portals.set(a.platform, r);
      stages.set(a.status, (stages.get(a.status) ?? 0) + 1);
    }
    return {
      byPortal: [...portals.values()].sort((x, y) => y.count - x.count),
      funnel: [...stages.entries()].map(([stage, count]) => ({ stage, count })).sort((x, y) => y.count - x.count),
    };
  }, [apps]);

  const [saved, setSaved] = useState<number[]>(() => {
    try { return JSON.parse(localStorage.getItem("career-agent-saved") || "[]"); } catch { return []; }
  });
  const toggleSave = (id: number) =>
    setSaved((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      try { localStorage.setItem("career-agent-saved", JSON.stringify(next)); } catch { /* storage unavailable */ }
      return next;
    });

  const top = useMemo(
    () => [...(jobs || [])].sort((a, b) => (b.match_score ?? -1) - (a.match_score ?? -1)).slice(0, 6),
    [jobs],
  );

  const title = cfg?.titles?.[0] || "Your next role";
  const where = cfg?.locations?.[0];
  const running = run?.status === "running";
  const queued = run?.status === "queued";
  const active = running || queued;
  const appliedToday = data?.jobs.applied_today ?? 0;
  const perDay = cfg?.max_per_day ?? 0;
  const left = Math.max(0, perDay - appliedToday);

  return (
    <div className="my-page">
      <section className="my-hero" style={{ backgroundImage: `url(${heroUrl})` }}>
        <div className="my-hero-inner">
          <div className="eyebrow">{running ? `agent running · ${(run?.portals ?? []).join(", ")}` : queued ? `agent queued · ${(run?.portals ?? []).join(", ")}` : "your agent is idle"}</div>
          <h1>{title}{where ? <> in <em>{where}</em></> : null}</h1>
          <p>
            Your agent discovers jobs, scores them against your profile, prepares the right résumé and works through the application queue.
            {data ? ` Updated ${new Date(data.generated_at).toLocaleTimeString()}.` : ""}
          </p>
          <Link to="/job-search"><button className="cream-btn">{active ? "Open run controls" : "Start a job search"}</button></Link>
          <div className="my-goal-stats">
            <span><b>{data?.jobs_discovered ?? "—"}</b>jobs discovered</span>
            <span><b>{data?.jobs.eligible ?? "—"}</b>eligible</span>
            <span><b>{data?.applications_total ?? "—"}</b>applications</span>
            <span><b>{data?.applications_submitted ?? "—"}</b>submitted</span>
          </div>
        </div>
      </section>

      {error && <div style={{ marginTop: 18 }}><ErrorBanner message={error} /></div>}
      {loading && !data && <Loading />}

      {data && (
        <>
          <div className="stat-grid">
            <StatCard label="Jobs discovered" value={data.jobs_discovered} />
            <StatCard label="Jobs eligible" value={data.jobs.eligible ?? 0} />
            <StatCard label="Applications" value={data.applications_total} />
            <StatCard label="Submitted" value={data.applications_submitted} accent />
            <StatCard label="Interviews" value={data.interviews} />
            <StatCard label="Pending approvals" value={data.pending_approvals} />
          </div>
          <div className="stat-grid" style={{ marginTop: 12 }}>
            <StatCard label="Discovered today" value={data.jobs.discovered_today} />
            <StatCard label="Applied today" value={data.jobs.applied_today} />
            <StatCard label="Awaiting approval" value={data.awaiting_approval} />
            <StatCard label="Manual submit needed" value={data.ready_for_manual_submit} />
            <StatCard label="Emails sent" value={data.outreach.sent} />
            <StatCard label="Replies" value={data.outreach.replied} />
          </div>
        </>
      )}

      <div className="my-section-head">
        <h2>Top matches <span className="muted-count">({top.length})</span></h2>
        <div className="my-actions"><Link to="/jobs" className="my-btn">Browse all jobs</Link></div>
      </div>
      {top.length === 0 ? (
        <div className="my-application-card"><EmptyState label="No jobs yet. Run a search from Job Search." /></div>
      ) : (
        <div className="my-job-grid">
          {top.map((job) => <JobCard key={job.job_ref} job={job} saved={saved.includes(job.id)} onSave={toggleSave} />)}
        </div>
      )}

      {data && (
        <div className="panel-grid">
          <section className="reference-panel">
            <h2 className="panel-title">Applications by portal</h2>
            {(data.applications.by_portal.length ? data.applications.by_portal : derived.byPortal).length === 0 ? (
              <EmptyState label="No applications yet" />
            ) : (
              <table className="data">
                <thead><tr><th>Portal</th><th>Total</th><th>Submitted</th></tr></thead>
                <tbody>
                  {(data.applications.by_portal.length ? data.applications.by_portal : derived.byPortal).map((r) => (
                    <tr key={r.name}><td style={{ textTransform: "capitalize" }}>{r.name}</td><td>{r.count}</td><td>{r.submitted}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="reference-panel">
            <h2 className="panel-title">Application funnel</h2>
            <table className="data">
              <thead><tr><th>Stage</th><th>Count</th></tr></thead>
              <tbody>
                {(data.applications.funnel.length ? data.applications.funnel : derived.funnel).map((f) => (
                  <tr key={f.stage}><td style={{ textTransform: "capitalize" }}>{f.stage.replace(/_/g, " ")}</td><td>{f.count}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="reference-panel">
            <h2 className="panel-title">Jobs by company</h2>
            {data.jobs.by_company.length === 0 ? (
              <EmptyState label="No jobs yet" />
            ) : (
              <table className="data">
                <thead><tr><th>Company</th><th>Jobs</th></tr></thead>
                <tbody>
                  {data.jobs.by_company.slice(0, 8).map((r) => (
                    <tr key={r.name}><td>{r.name}</td><td>{r.count}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="reference-panel">
            <h2 className="panel-title">Needs attention</h2>
            {!attention || attention.length === 0 ? (
              <EmptyState label="Nothing needs you right now" />
            ) : (
              <table className="data">
                <thead><tr><th>Title</th><th>Company</th><th>Platform</th><th>State</th></tr></thead>
                <tbody>
                  {attention.slice(0, 8).map((r, i) => (
                    <tr key={i}>
                      <td>{String(r.title ?? "—")}</td>
                      <td>{String(r.company ?? "—")}</td>
                      <td style={{ textTransform: "capitalize" }}>{String(r.platform ?? "—")}</td>
                      <td>{String((r as unknown as Record<string, unknown>).state ?? r.status ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      )}

      <div className="my-section-head">
        <h2>Recent applications</h2>
        <Link to="/applications" className="link-btn">See all →</Link>
      </div>
      <ApplicationPreview apps={(apps || []).slice(0, 5)} />

      {cfg && perDay > 0 && (
        <div className="quota-card">
          <div className="quota-ring" style={{ background: `conic-gradient(#18b777 ${Math.min(100, Math.round((appliedToday / perDay) * 100))}%,#eceae3 0)` }}>
            <span>{left}</span>
          </div>
          <div className="quota-copy">
            <strong>{left} applications left today</strong>
            <small>{appliedToday} of {perDay} used · {cfg.allow_submit ? "apply is ON" : "review mode — nothing is submitted automatically"}</small>
          </div>
          <Link to="/job-search" className="my-btn dark">Open job search →</Link>
        </div>
      )}
    </div>
  );
}

function ApplicationPreview({ apps }: { apps: Application[] }) {
  if (!apps.length) return <div className="my-application-card my-empty">No applications yet. Run a portal from Job Search.</div>;
  return (
    <div className="my-application-card">
      <table className="my-table">
        <thead><tr><th>Role</th><th>Platform</th><th>Status</th><th>Submitted</th><th /></tr></thead>
        <tbody>
          {apps.map((a, i) => (
            <tr key={a.id} className={i === 0 ? "active" : ""}>
              <td>
                <div className="company-cell">
                  <div className="mini-logo">{initials(a.company || a.platform)}</div>
                  <div><strong>{a.title}</strong><div style={{ color: "#857f75", fontSize: 12 }}>{a.company || "—"}</div></div>
                </div>
              </td>
              <td style={{ textTransform: "capitalize" }}>{a.platform}</td>
              <td><span className={`status-pill ${statusClass(a.status)}`}>{a.status.replace(/_/g, " ")}</span></td>
              <td>{a.submitted_at ? new Date(a.submitted_at).toLocaleString() : "—"}</td>
              <td>{a.url ? <a href={a.url} target="_blank" rel="noreferrer" className="link-btn"><ExternalLink size={12} style={{ display: "inline", marginRight: 3 }} />Open</a> : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
