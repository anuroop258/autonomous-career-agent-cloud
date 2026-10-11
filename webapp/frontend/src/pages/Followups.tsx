import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { PageHeader, Loading, ErrorBanner, EmptyState, StatusBadge } from "../components/ui";

export default function Followups() {
  const { data, error, loading, refresh } = usePolling(() => api.outreachList("sent"), 20000);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [created, setCreated] = useState<number[] | null>(null);

  const run = async () => {
    setBusy(true);
    setActionError(null);
    try {
      const r = await api.runFollowups();
      setCreated(r.created);
      refresh();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const now = Date.now();

  return (
    <div>
      <PageHeader
        title="Follow-ups"
        subtitle="Creates follow-up drafts for sent emails past the configured wait period; drafts still need approval before sending."
        actions={<button className="btn btn-primary" disabled={busy} onClick={run}>{busy ? "Checking…" : "Run Follow-ups"}</button>}
      />
      {actionError && <div className="mb-4"><ErrorBanner message={actionError} /></div>}
      {created && <p className="text-sm text-emerald-700 mb-4">{created.length} follow-up draft(s) created. Approve them on the Approvals page.</p>}

      {error && <ErrorBanner message={error} />}
      {loading && !data && <Loading />}
      {data && data.length === 0 && <EmptyState label="No sent emails awaiting follow-up." />}
      {data && data.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="data">
            <thead><tr><th>Recruiter</th><th>Company</th><th>Job</th><th>Sent</th><th>Days since</th><th>Follow-up due</th></tr></thead>
            <tbody>
              {data.map((o) => {
                const days = o.sent_at ? Math.floor((now - new Date(o.sent_at).getTime()) / 86400000) : null;
                const due = o.follow_up_at && new Date(o.follow_up_at).getTime() <= now;
                return (
                  <tr key={o.id}>
                    <td>{o.recruiter_name || o.recruiter_email || "—"}</td>
                    <td>{o.company || "—"}</td>
                    <td>{o.job_title || "—"}</td>
                    <td className="text-xs text-stone-500">{o.sent_at ? new Date(o.sent_at).toLocaleDateString() : "—"}</td>
                    <td>{days ?? "—"}</td>
                    <td>{o.follow_up_at ? <StatusBadge status={due ? "WARN" : "OK"} /> : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
