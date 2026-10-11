import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { PageHeader, Loading, ErrorBanner, EmptyState, StatusBadge } from "../components/ui";

export default function Approvals() {
  const { data, error, loading, refresh } = usePolling(() => api.approvals(), 12000);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const decide = async (id: number, action: "approve" | "reject") => {
    setBusyId(id);
    setActionError(null);
    try {
      if (action === "approve") await api.approve(id);
      else await api.reject(id);
      refresh();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <PageHeader title="Approvals" subtitle="Applications and outreach emails held for approval before anything is submitted or sent." />
      {actionError && <div className="mb-4"><ErrorBanner message={actionError} /></div>}
      {error && <ErrorBanner message={error} />}
      {loading && !data && <Loading />}
      {data && data.length === 0 && <EmptyState label="Nothing pending." />}
      {data && data.length > 0 && (
        <div className="space-y-3">
          {data.map((a) => (
            <div key={a.id} className="card flex items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs text-stone-400">#{a.id}</span>
                  <StatusBadge status={a.kind} />
                </div>
                <p className="text-sm text-stone-900">{a.summary}</p>
                <p className="text-xs text-stone-500">requested {new Date(a.requested_at).toLocaleString()}</p>
              </div>
              <div className="flex gap-2 shrink-0">
                <button className="btn btn-primary" disabled={busyId === a.id} onClick={() => decide(a.id, "approve")}>Approve</button>
                <button className="btn btn-danger" disabled={busyId === a.id} onClick={() => decide(a.id, "reject")}>Reject</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
