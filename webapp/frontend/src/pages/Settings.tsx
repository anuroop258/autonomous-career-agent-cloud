import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";
import { PageHeader, ErrorBanner, Loading, KV } from "../components/ui";

const yn = (b: boolean) => (b ? "Yes" : "No");

export default function Settings() {
  const { data: cfg, error, loading } = usePolling(() => api.config(), 60000);
  const { data: status } = usePolling(() => api.status(), 30000);
  if (loading && !cfg) return <div className="reference-page"><Loading /></div>;
  return (
    <div className="reference-page">
      <PageHeader title="Settings" subtitle="Read-only view of the configuration the agent is running with." />
      {error && <ErrorBanner message={error} />}
      {cfg && (
        <>
          <div className="panel-grid" style={{ marginTop: 0 }}>
            <section className="reference-panel">
              <h2>Candidate &amp; limits</h2>
              <KV rows={[
                ["Candidate", cfg.candidate_id], ["Allow submit", yn(cfg.allow_submit)],
                ["Max per day", cfg.max_per_day], ["Max per platform", cfg.max_per_platform],
                ["Max retries", cfg.max_retries], ["Database", cfg.db_path],
                ["Titles", cfg.titles?.join(", ") || "—"], ["Locations", cfg.locations?.join(", ") || "—"],
              ]} />
            </section>
            <section className="reference-panel">
              <h2>Resume</h2>
              <KV rows={[
                ["Tailoring", yn(cfg.resume.tailor)], ["Upload tailored resume", yn(cfg.resume.use_tailored_for_upload)],
                ["Master resume", cfg.resume.master_resume_path ?? "—"], ["AI rewrite", yn(cfg.resume.ai_rewrite)],
                ["Preserve metrics", yn(cfg.resume.preserve_metrics)], ["Max buzzwords", cfg.resume.max_buzzwords],
              ]} />
            </section>
          </div>

          <section className="reference-panel" style={{ marginTop: 16 }}>
            <h2>Portals</h2>
            <div className="my-application-card">
              <table className="my-table">
                <thead><tr><th>Portal</th><th>Enabled</th><th>Mode</th><th>Max / day</th><th>CDP port</th></tr></thead>
                <tbody>
                  {Object.entries(cfg.portals).map(([name, p]) => (
                    <tr key={name}>
                      <td style={{ textTransform: "capitalize" }}>{name}</td>
                      <td><span className={`status-pill ${p.enabled ? "good" : ""}`}>{p.enabled ? "Enabled" : "Off"}</span></td>
                      <td>{p.mode}</td><td>{p.max_per_day}</td><td>{p.cdp_port}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="reference-panel" style={{ marginTop: 16 }}>
            <h2>Outreach</h2>
            <KV rows={[
              ["Enabled", yn(cfg.outreach.enabled)], ["Mode", cfg.outreach.mode], ["Daily cap", cfg.outreach.daily_cap],
              ["Follow-up after (days)", cfg.outreach.followup_days], ["Max follow-ups", cfg.outreach.max_followups],
              ["Auto recruiter discovery", yn(cfg.outreach.auto_recruiter_discovery)], ["Search provider", cfg.outreach.search_provider],
            ]} />
          </section>

          <section className="reference-panel" style={{ marginTop: 16 }}>
            <h2>Environment checks</h2>
            {!status ? <Loading /> : (
              <div className="my-application-card">
                <table className="my-table">
                  <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
                  <tbody>
                    {status.checks.map((c) => (
                      <tr key={c.name}>
                        <td>{c.name}</td>
                        <td><span className={`status-pill ${c.status === "OK" ? "good" : c.status === "FAIL" ? "bad" : "warn"}`}>{c.status}</span></td>
                        <td style={{ whiteSpace: "normal", maxWidth: 500, color: "#77736b" }}>{c.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
