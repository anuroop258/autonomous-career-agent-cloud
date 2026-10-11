import { useState } from "react";
import { Play, Square, RefreshCw, ShieldCheck } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { PageHeader, ErrorBanner, Loading, StatusBadge } from "../components/ui";

const PORTALS = ["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"] as const;

export default function JobSearch() {
  const { data: cfg } = usePolling(() => api.config(), 60000);
  const { data: cdp, refresh: refreshCdp } = usePolling(() => api.cdpStatus(), 10000);
  const { data: run, refresh: refreshRun } = usePolling(() => api.automationStatus(), 5000);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // launch the browser session, wait until CDP answers, then start the agent
  const runPortal = async (portal: string) => {
    setBusy(portal); setErr(null); setMsg(null);
    try {
      if (!cdp?.[portal]?.connected) {
        await api.launchPortal(portal);
        let ok = false;
        for (let i = 0; i < 20 && !ok; i++) {
          await sleep(1500);
          ok = (await api.cdpTest(portal)).connected;
        }
        if (!ok) throw new Error(`${portal} browser did not connect. Log in in the opened window and try again.`);
      }
      const r = await api.startAutomation([portal]);
      const selected = r.started?.[0];
      setMsg(selected?.status === "queued" ? `Queued ${portal} in the cloud worker.` : `Started ${r.portals.join(", ")}.`);
      refreshCdp(); refreshRun();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const stopAll = async () => {
    setBusy("stop"); setErr(null); setMsg(null);
    try { await api.stopAutomation(); setMsg("Stop requested."); refreshRun(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const continueIndeed = async () => {
    setBusy("continue"); setErr(null); setMsg(null);
    try { const r = await api.continueIndeedHumanVerification(); setMsg(r.message); refreshRun(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const running = run?.status === "running" || run?.status === "queued" || run?.status === "stopping";
  const indeedWaiting = !!run?.runs?.indeed?.human_verification;

  return (
    <div className="reference-page">
      <PageHeader
        title="Job Search"
        subtitle="Launch a portal's browser session and queue its agent run. The cloud worker processes portal tasks one at a time."
        actions={<>
          <span>Run: <StatusBadge status={run?.status ?? "idle"} /></span>
          <button className="my-btn" disabled={busy === "stop" || !running} onClick={stopAll}><Square size={14} /> Stop</button>
          <button className="my-btn soft" disabled={busy === "continue"} onClick={continueIndeed}><ShieldCheck size={14} /> {indeedWaiting ? "Continue Indeed (waiting for you)" : "Continue Indeed"}</button>
        </>}
      />
      {err && <ErrorBanner message={err} />}
      {msg && <div className="reference-panel" style={{ marginBottom: 14, color: "#0b7d51" }}>{msg}</div>}

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
            const portalRunning = pr?.status === "running";
            const portalActive = portalRunning || pr?.status === "queued";
            return (
              <div key={p} className={`run-card ${portalActive ? "selected" : ""}`}>
                <div className="run-name">{p}<StatusBadge status={pr?.status ?? "idle"} /></div>
                <div className="run-meta">
                  CDP port {c?.port ?? pc?.cdp_port ?? "—"} · {c?.connected ? "browser connected" : "browser not connected"}
                  {pc && <> · {pc.enabled ? "enabled" : "disabled"} · up to {pc.max_per_day}/day</>}
                </div>
                {pr?.pid && <div className="run-meta">pid {pr.pid}{pr.log_file ? ` · ${pr.log_file}` : ""}</div>}
                <button className="my-btn green" disabled={busy === p || portalActive} onClick={() => runPortal(p)}>
                  <Play size={14} style={{ display: "inline", marginRight: 4 }} />
                  {busy === p ? "Starting…" : portalRunning ? "Running" : pr?.status === "queued" ? "Queued" : c?.connected ? "Start agent" : "Launch browser & start"}
                </button>
                {p === "indeed" && (
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
