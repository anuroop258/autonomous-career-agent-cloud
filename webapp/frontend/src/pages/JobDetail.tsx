import { useState } from "react";
import { useParams } from "react-router-dom";
import { Bookmark, EyeOff, ExternalLink, MapPin, Share2, Clock3, BriefcaseBusiness, IndianRupee } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { ErrorBanner, Loading } from "../components/ui";

function initials(c: string) {
  return ((c || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0]).join("") || "?").toUpperCase();
}

function matchScore(value: number | null | undefined) {
  if (value == null) return 0;
  const n = Number(value);
  return n <= 1 ? Math.round(n * 100) : Math.round(n);
}

export default function JobDetail() {
  const { id } = useParams();
  const jobRef = decodeURIComponent(id || "");
  const { data, error, loading, refresh } = usePolling(() => api.job(jobRef), 20000, [jobRef]);
  const [tailoring, setTailoring] = useState(false);
  const [saved, setSaved] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const tailor = async () => {
    setTailoring(true); setActionError(null);
    try { await api.tailorResume(jobRef); refresh(); }
    catch (e) { setActionError(e instanceof ApiError ? e.message : String(e)); }
    finally { setTailoring(false); }
  };

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBanner message={error} />;
  if (!data) return null;
  const { job, matches, applications, resume_versions, events } = data;
  const score = matchScore((matches?.[0] as any)?.score ?? job.match_score);
  const matchLabel = score >= 75 ? "STRONG MATCH" : score >= 45 ? "FAIR MATCH" : "LOW MATCH";
  const ring = Math.max(4, Math.min(100, score));

  return (
    <div className="mj-job-detail-page">
      <div className="mj-job-detail-topline">
        <span>JOB · {job.id}</span>
        <div className="mj-job-top-actions">
          <button onClick={() => setSaved(!saved)}><Bookmark size={14} />{saved ? "Saved" : "Save"}</button>
          <button><EyeOff size={14} />Hide</button>
          <button><Share2 size={14} />Share</button>
        </div>
      </div>
      {job.url && <div className="mj-original-link"><a href={job.url} target="_blank" rel="noreferrer">View original posting <ExternalLink size={14} /></a></div>}

      {actionError && <ErrorBanner message={actionError} />}
      <section className="mj-job-hero">
        <div className="mj-job-hero-copy">
          <div className="mj-job-kicker">{(job.location || "—").split(",")[0]?.toUpperCase()} · FULLTIME</div>
          <h1>{job.title}</h1>
          <div className="mj-job-company-line"><div className="mj-company-logo large">{initials(job.company || job.source)}</div><div><strong>{job.company || "Unknown company"}</strong><span>{job.location || "Location unavailable"} · {job.application_route === "external" ? "External" : "Hybrid"} · Posted {job.discovered_at ? new Date(job.discovered_at).toLocaleDateString() : "recently"}</span></div></div>
          <div className="mj-source-chip">SOURCED FROM <span>● {job.source}</span></div>
          <div className="mj-meta-row">
            <span><IndianRupee size={16} />Undisclosed</span><span><Clock3 size={16} />Fresher</span><span><BriefcaseBusiness size={16} />Fulltime</span><span><MapPin size={16} />{job.location || "—"}</span>
          </div>
          <div className="mj-hero-actions"><button className="mj-dark-btn" onClick={() => document.getElementById("activity")?.scrollIntoView({ behavior: "smooth" })}>View application activity →</button><button className="mj-plain-btn" onClick={() => setSaved(!saved)}>Not interested</button></div>
        </div>
        <div className="mj-match-ring" style={{ background: `conic-gradient(#10985f ${ring}%, #d1cec4 ${ring}% 100%)` }}><div><strong>{score}</strong><span>{matchLabel}</span></div><label>MATCH</label></div>
      </section>

      <section className="mj-section-block">
        <div className="mj-section-kicker">SECTION · 01</div>
        <h2>Why this is a match</h2>
        <div className="mj-match-panel">
          <div className="mj-match-stats"><div><strong>{score}</strong><span>match score</span></div><div><strong>{job.eligible === 1 ? "YES" : "—"}</strong><span>eligible</span></div><div><strong>{job.matched_skills?.length ?? 0}</strong><span>matched skills</span></div></div>
          <div className="mj-chip-cloud">{(job.matched_skills || []).slice(0, 8).map((s) => <span key={s}>{s}</span>)}</div>
          {job.missing_skills?.length ? <p className="mj-muted-note">Missing: {job.missing_skills.join(", ")}</p> : null}
        </div>
      </section>

      <section className="mj-section-block" id="activity">
        <div className="mj-section-kicker">SECTION · 02</div>
        <h2>Application activity</h2>
        <div className="mj-detail-grid">
          <div className="mj-detail-card"><h3>Applications</h3>{applications.length ? applications.map((a) => <div className="mj-detail-row" key={a.id}><span>{a.platform}</span><b>{a.status.replace(/_/g, " ")}</b></div>) : <p>Nothing started yet.</p>}</div>
          <div className="mj-detail-card"><h3>Resume versions</h3>{resume_versions.length ? resume_versions.map((r: any) => <div className="mj-detail-row" key={r.id}><span>v{r.id}</span><b>{r.template_version || "tailored"}</b></div>) : <p>No tailored resume yet.</p>}<button className="mj-dark-btn compact" onClick={tailor} disabled={tailoring}>{tailoring ? "Tailoring…" : "Tailor resume"}</button></div>
          <div className="mj-detail-card full"><h3>Job description</h3><p className="mj-description">{job.description || "No description stored."}</p></div>
          <div className="mj-detail-card full"><h3>Timeline</h3>{events.length ? events.slice(0, 12).map((e: any) => <div className="mj-detail-row" key={e.id}><span>{new Date(e.created_at).toLocaleString()}</span><b>{e.event_type}{e.platform ? ` · ${e.platform}` : ""}</b></div>) : <p>No events recorded yet.</p>}</div>
        </div>
      </section>
    </div>
  );
}
