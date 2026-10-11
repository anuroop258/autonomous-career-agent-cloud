import { useState } from "react";
import { Play, Square, RefreshCw, ShieldCheck } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError, CLOUD_RUNNER_MODE } from "../api/client";
import { PageHeader, ErrorBanner, Loading, StatusBadge } from "../components/ui";

const PORTALS = ["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"] as const;

export default function JobSearch() {
  const { data: cfg } = usePolling(() => api.config(), 60000);
  const { data: cdp, refresh: refreshCdp } = usePolling(() => api.cdpStatus(), 10000);
  const { data: run, refresh: refreshRun } = usePolling(() => api.automationStatus(), 5000);
  const [busy, setBusy] = useState<string | null>(null);
  const [maxJobs, setMaxJobs] = useState(1);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // launch the browser session, wait until CDP answers, then start the agent
  const runPortal = async (portal: string) => {
    setBusy(portal); setErr(null); setMsg(null);
    try {
      if (CLOUD_RUNNER_MODE) {
        const password = window.prompt("Enter the automation password configured by the site owner to start this cloud job search.");
        if (!password) return;
        if (!window.confirm(`Start the ${portal} cloud run? The agent may submit up to ${maxJobs} applications using your saved profile and resume. Continue only if you approve this run.`)) return;
        const r = await api.startCloudAutomation(portal, maxJobs, password);
        setMsg(`Queued ${r.portal} cloud run (${r.task_id}). Track its progress in Runs and logs.`);
        refreshRun();
        return;
      }
      const password = window.prompt("Enter the automation password configured in the backend to start or launch this run.");
      if (!password) return;
      if (!cdp?.[portal]?.connected) {
        await api.launchPortal(portal, password);
        let ok = false;
        for (let i = 0; i < 20 && !ok; i++) {
          await sleep(1500);
          ok = (await api.cdpTest(portal)).connected;
        }
        if (!ok) throw new Error(`${portal} browser did not connect. Log in in the opened window and try again.`);
      }
      const r = await api.startAutomation([portal], password);
      setMsg(`Started ${r.portals.join(", ")}.`);
      refreshCdp(); refreshRun();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const stopAll = async () => {
    setBusy("stop"); setErr(null); setMsg(null);
    try {
      if (CLOUD_RUNNER_MODE) {
        const password = window.prompt("Enter the automation password to stop the active cloud run.");
        if (!password) return;
        await api.stopCloudAutomation(password);
      } else {
        const password = window.prompt("Enter the automation password configured in the backend to stop the active run.");
        if (!password) return;
        await api.stopAutomation(password);
      }
      setMsg("Stop requested."); refreshRun();
    }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const continueIndeed = async () => {
    setBusy("continue"); setErr(null); setMsg(null);
    try {
      const password = window.prompt("Enter the automation password configured in the backend to continue the Indeed run.");
      if (!password) return;
      const r = await api.continueIndeedHumanVerification(password); setMsg(r.message); refreshRun();
    }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const running = run?.status === "running" || run?.status === "stopping";
  const indeedWaiting = !!run?.runs?.indeed?.human_verification;

  return (
    <div className="reference-page">
      <PageHeader
        title="Job Search"
        subtitle={CLOUD_RUNNER_MODE ? "Start a portal on a temporary cloud Linux runner. Browsing the dashboard is public; only starting or stopping automation asks for the owner password." : "Launch a portal's browser session and start the agent for it. Each portal runs on its own."}
        actions={<>
          <span>Run: <StatusBadge status={run?.status ?? "idle"} /></span>
          <button className="my-btn" disabled={busy === "stop" || !running} onClick={stopAll}><Square size={14} /> Stop</button>
          {!CLOUD_RUNNER_MODE && <button className="my-btn soft" disabled={busy === "continue"} onClick={continueIndeed}><ShieldCheck size={14} /> {indeedWaiting ? "Continue Indeed (waiting for you)" : "Continue Indeed"}</button>}
        </>}
      />
      {err && <ErrorBanner message={err} />}
      {msg && <div className="reference-panel" style={{ marginBottom: 14, color: "#0b7d51" }}>{msg}</div>}

      {CLOUD_RUNNER_MODE && (
        <div className="reference-panel" style={{ marginBottom: 16 }}>
          <label className="my-label" htmlFor="cloud-run-limit">Maximum applications targeted</label>
          <select id="cloud-run-limit" value={maxJobs} onChange={(e) => setMaxJobs(Number(e.target.value))} style={{ marginLeft: 12, padding: "8px 12px", borderRadius: 10, border: "1px solid #e8e1d4", background: "white" }}>
            {[1,2,3,4,5].map((count) => <option key={count} value={count}>{count}</option>)}
          </select>
          <p className="mj-muted-note" style={{ marginTop: 8, marginBottom: 0 }}>A temporary GitHub Linux runner performs the work. Usage is limited by the free Actions allowance.</p>
        </div>
      )}

      {cfg && (
        <div className="reference-panel" style={{ marginBottom: 16 }}>
          <div className="my-label">Search configuration</div>
          <div className="tag-row" style={{ marginTop: 10, marginBottom: 0 }}>
            <span className="tag green">{cfg.allow_submit ? "Apply enabled" : "Review mode"}</span>
            <span className="tag">{cfg.max_per_day} / day</span>
            <span className="tag">{cfg.max_per_platform} / platform</span>
            {(cfg.titles || []).map((t) => <span key={t} className="tag">{t}</span>)}
            {(cfg.locations || []).map((l) => <span key={l} className="tag">{l}</span>)}
          </div>
        </div>
      )}

      {!cdp ? <Loading /> : (
        <div className="run-grid">
          {PORTALS.map((p) => {
            const c = cdp[p]; const pr = run?.runs?.[p]; const pc = cfg?.portals?.[p];
            const portalRunning = ["queued", "running", "stopping"].includes(pr?.status || "");
            return (
              <div key={p} className={`run-card ${portalRunning ? "selected" : ""}`}>
                <div className="run-name">{p}<StatusBadge status={pr?.status ?? "idle"} /></div>
                <div className="run-meta">
                  {CLOUD_RUNNER_MODE ? "Remote Linux browser · starts on demand" : <>CDP port {c?.port ?? pc?.cdp_port ?? "—"} · {c?.connected ? "browser connected" : "browser not connected"}</>}
                  {pc && <> · {pc.enabled ? "enabled" : "disabled"} · up to {pc.max_per_day}/day</>}
                </div>
                {pr?.pid && <div className="run-meta">pid {pr.pid}{pr.log_file ? ` · ${pr.log_file}` : ""}</div>}
                <button className="my-btn green" disabled={busy === p || portalRunning} onClick={() => runPortal(p)}>
                  <Play size={14} style={{ display: "inline", marginRight: 4 }} />
                  {busy === p ? "Starting…" : portalRunning ? "Running" : CLOUD_RUNNER_MODE ? "Start cloud run" : c?.connected ? "Start agent" : "Launch browser & start"}
                </button>
                {p === "indeed" && !CLOUD_RUNNER_MODE && (
                  <button className="my-btn" disabled={busy === "continue"} onClick={continueIndeed}><RefreshCw size={14} /> Enter / Continue Indeed</button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
