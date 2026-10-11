import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { PageHeader, Loading, ErrorBanner, EmptyState, StatusBadge } from "../components/ui";

export default function Recruiters() {
  const { data, error, loading, refresh } = usePolling(() => api.recruiters(), 20000);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const discover = async () => {
    setBusy(true);
    setActionError(null);
    setResult(null);
    try {
      const r = await api.discoverRecruiters();
      setResult(r.discovered);
      refresh();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Recruiters / HR"
        subtitle="Public-search-engine discovery only. A guessed email is never shown as verified."
        actions={
          <button className="btn btn-primary" disabled={busy} onClick={discover}>
            {busy ? "Discovering…" : "Discover Recruiters"}
          </button>
        }
      />
      {actionError && <div className="mb-4"><ErrorBanner message={actionError} /></div>}
      {result && (
        <pre className="text-xs text-stone-500 bg-white border border-stone-200 rounded-lg p-3 mb-4 overflow-x-auto">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}

      {error && <ErrorBanner message={error} />}
      {loading && !data && <Loading />}
      {data && data.length === 0 && <EmptyState label="No recruiter contacts yet." />}
      {data && data.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="data">
            <thead><tr><th>Company</th><th>Name</th><th>Role</th><th>Email</th><th>Source</th><th>Confidence</th><th>Discovered</th></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  <td>{r.company}</td>
                  <td>{r.name || "—"}</td>
                  <td>{r.title || "—"}</td>
                  <td>
                    {r.email ? (
                      <span className="flex items-center gap-1.5">{r.email} <StatusBadge status="OK" /></span>
                    ) : (
                      <span className="text-stone-400">unverified</span>
                    )}
                  </td>
                  <td className="text-xs text-stone-500">{r.source}</td>
                  <td>{r.confidence != null ? r.confidence.toFixed(2) : "—"}</td>
                  <td className="text-xs text-stone-500">{new Date(r.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
