import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";
import { PageHeader, Loading, ErrorBanner, EmptyState } from "../components/ui";

const FILTERS = ["", "naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"];

export default function Logs() {
  const [platform, setPlatform] = useState("");
  const [view, setView] = useState<"structured" | "raw">("structured");
  const { data, error, loading } = usePolling(() => api.logs({ limit: 200, platform: platform || undefined }), 10000, [platform]);
  const { data: raw } = usePolling(() => api.rawLogs(120), 15000, [view]);

  return (
    <div>
      <PageHeader title="Logs / Audit" subtitle="Structured events from the shared database, plus the plaintext run log when present." />
      <div className="flex items-center gap-2 mb-4">
        <div className="flex gap-1">
          <button className={`btn ${view === "structured" ? "btn-primary" : "btn-secondary"}`} onClick={() => setView("structured")}>Structured</button>
          <button className={`btn ${view === "raw" ? "btn-primary" : "btn-secondary"}`} onClick={() => setView("raw")}>Raw file</button>
        </div>
        {view === "structured" && (
          <div className="flex gap-1 ml-4">
            {FILTERS.map((f) => (
              <button key={f} className={`btn ${platform === f ? "btn-primary" : "btn-secondary"} capitalize`} onClick={() => setPlatform(f)}>
                {f || "All"}
              </button>
            ))}
          </div>
        )}
      </div>

      {view === "structured" ? (
        <>
          {error && <ErrorBanner message={error} />}
          {loading && !data && <Loading />}
          {data && data.length === 0 && <EmptyState label="No events recorded yet." />}
          {data && data.length > 0 && (
            <div className="card p-0 max-h-[70vh] overflow-y-auto font-mono text-xs">
              {data.map((e) => (
                <div key={e.id} className="flex gap-3 px-3 py-1.5 border-b border-stone-100 hover:bg-white/50">
                  <span className="text-stone-400 shrink-0 w-44">{new Date(e.created_at).toLocaleString()}</span>
                  <span className="text-stone-500 shrink-0 w-20">{e.platform ?? ""}</span>
                  <span className="text-emerald-700 shrink-0 w-48">{e.event_type}</span>
                  <span className="text-stone-500 truncate">{e.payload_json ?? ""}</span>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="card p-0 max-h-[70vh] overflow-y-auto font-mono text-xs">
          {!raw || raw.tail.length === 0 ? (
            <EmptyState label="No log file found yet (logs/ is created on the first run)." />
          ) : (
            <>
              <p className="px-3 py-2 text-stone-400 border-b border-stone-100">{raw.current_file}</p>
              {raw.tail.map((line, i) => (
                <div key={i} className="px-3 py-0.5 text-stone-600 whitespace-pre-wrap">{line}</div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
