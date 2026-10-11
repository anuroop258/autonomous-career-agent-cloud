import { useState } from "react";
import { CheckCircle2, Circle, ExternalLink, Link2, Play, RefreshCw } from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { ErrorBanner, Loading } from "../components/ui";

const PORTALS = ["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"] as const;

export default function Browser() {
  const { data: cdp, error: cdpError, loading, refresh } = usePolling(() => api.cdpStatus(), 10000);
  const { data: cfg } = usePolling(() => api.config(), 60000);
  const [testing, setTesting] = useState<string | null>(null);
  const [launching, setLaunching] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runTest = async (portal: string) => {
    setTesting(portal); setError(null); setMessage(null);
    try { const r = await api.cdpTest(portal); setMessage(`${portal} connection: ${r.connected ? "connected" : "not connected"}`); refresh(); }
    catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setTesting(null); }
  };
  const launch = async (portal: string) => {
    const password = window.prompt("Enter the automation password configured by the site owner to launch a browser action.");
    if (password === null || !password.trim()) return;
    setLaunching(portal); setError(null); setMessage(null);
    try { const r = await api.launchPortal(portal, password); setMessage(`${r.portal} browser session launched on port ${r.port}.`); setTimeout(refresh, 1200); }
    catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setLaunching(null); }
  };

  const connected = PORTALS.filter(p => cdp?.[p]?.connected).length;
  return <div className="my-page">
    <div className="my-section-head" style={{marginTop:0}}>
      <div><h2>Integrations</h2><div style={{color:"#817b71",marginTop:4}}>Your V44 agent connects to the same logged-in browser sessions you already use.</div></div>
      <button className="my-btn" onClick={()=>refresh()}><RefreshCw size={15}/> Refresh</button>
    </div>
    {error && <ErrorBanner message={error}/>} {cdpError && <ErrorBanner message={cdpError}/>} {message && <div className="reference-panel" style={{marginBottom:14, color:"#0b7d51"}}>{message}</div>}
    <div className="reference-panel" style={{marginBottom:16}}>
      <div className="my-label">Connection status</div>
      <div style={{display:"flex",alignItems:"center",gap:12,marginTop:8}}>
        <div style={{font:"600 31px Fraunces,serif"}}>{connected}/{PORTALS.length}</div>
        <div style={{color:"#77736b"}}>boards currently connected</div>
      </div>
      <div className="tag-row" style={{marginBottom:0,marginTop:14}}>
        {PORTALS.map(p=><span key={p} className={`tag ${cdp?.[p]?.connected?"green":""}`}>
          {cdp?.[p]?.connected?<CheckCircle2 size={12}/>:<Circle size={12}/>} {p}
        </span>)}
      </div>
    </div>
    {loading && !cdp ? <Loading/> : <div className="ref-grid-3">
      {PORTALS.map(portal=>{
        const c=cdp?.[portal]; const pc=cfg?.portals?.[portal];
        return <div key={portal} className="reference-panel">
          <div style={{display:"flex",justifyContent:"space-between",gap:10,alignItems:"center"}}>
            <div style={{fontWeight:600,textTransform:"capitalize"}}>{portal}</div>
            <span className={`status-pill ${c?.connected?"good":"warn"}`}>{c?.connected?"Connected":"Not connected"}</span>
          </div>
          <div style={{marginTop:10,fontSize:12,color:"#827c72"}}>CDP port {c?.port ?? pc?.cdp_port ?? "—"} · {pc?.mode ?? "deterministic"}</div>
          <div style={{display:"flex",gap:8,marginTop:16}}>
            <button className="my-btn" disabled={launching===portal} onClick={()=>launch(portal)}><Play size={14}/>{launching===portal?"Launching…":"Launch"}</button>
            <button className="my-btn soft" disabled={testing===portal} onClick={()=>runTest(portal)}><Link2 size={14}/>{testing===portal?"Testing…":"Test"}</button>
            {c?.connected && <a className="my-btn" href={`http://127.0.0.1:${c.port}`} target="_blank" rel="noreferrer"><ExternalLink size={14}/>Open</a>}
          </div>
        </div>
      })}
    </div>}
    <div className="reference-panel" style={{marginTop:16}}>
      <div className="my-label">How this maps to V44</div>
      <p style={{margin:"8px 0 0",color:"#77736b",lineHeight:1.65}}>Naukri, Indeed, Shine, TimesJobs and Glassdoor use the shared 9222 browser session. LinkedIn uses 9232. Launch/Test calls above go directly to the existing FastAPI endpoints; no mock connection state is used.</p>
    </div>
  </div>;
}
