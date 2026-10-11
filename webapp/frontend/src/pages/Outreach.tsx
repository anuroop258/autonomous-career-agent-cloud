import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { PageHeader, Loading, ErrorBanner, EmptyState, StatusBadge } from "../components/ui";

export default function Outreach() {
  const { data, error, loading, refresh } = usePolling(() => api.outreachList(), 20000);
  const { data: jobs } = usePolling(() => api.jobs({ limit: 100 }), 30000);
  const { data: recruiters } = usePolling(() => api.recruiters(), 30000);

  const [jobId, setJobId] = useState<number | "">("");
  const [recruiterId, setRecruiterId] = useState<number | "">("");
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error2, setError2] = useState<string | null>(null);

  const generate = async () => {
    if (!jobId || !recruiterId) return;
    setBusy(true);
    setError2(null);
    setDraft(null);
    try {
      const r = await api.draftOutreach(Number(jobId), Number(recruiterId));
      setDraft(r);
      refresh();
    } catch (e) {
      setError2(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const sendApproved = async () => {
    setBusy(true);
    setError2(null);
    try {
      const r = await api.sendOutreach();
      setDraft({ send_result: r });
      refresh();
    } catch (e) {
      setError2(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Outreach"
        subtitle="Emails are job/company specific and reuse the tailored resume version built for that job."
        actions={<button className="btn btn-secondary" disabled={busy} onClick={sendApproved}>Send Approved</button>}
      />

      <div className="card mb-6">
        <h2 className="text-sm font-medium text-stone-700 mb-3">Generate Personalized Email</h2>
        <div className="flex flex-wrap gap-2 mb-3">
          <select value={jobId} onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : "")} className="bg-white border border-stone-200 rounded-lg px-3 py-1.5 text-sm">
            <option value="">Select job…</option>
            {jobs?.map((j) => <option key={j.id} value={j.id}>{j.title} · {j.company}</option>)}
          </select>
          <select value={recruiterId} onChange={(e) => setRecruiterId(e.target.value ? Number(e.target.value) : "")} className="bg-white border border-stone-200 rounded-lg px-3 py-1.5 text-sm">
            <option value="">Select recruiter…</option>
            {recruiters?.filter((r) => r.email).map((r) => <option key={r.id} value={r.id}>{r.name || r.email} ({r.company})</option>)}
          </select>
          <button className="btn btn-primary" disabled={!jobId || !recruiterId || busy} onClick={generate}>
            {busy ? "Generating…" : "Generate Email"}
          </button>
        </div>
        {recruiters && recruiters.filter((r) => r.email).length === 0 && (
          <p className="text-xs text-amber-700">No recruiters with a verified email yet -- discover contacts first on the Recruiters page.</p>
        )}
        {error2 && <ErrorBanner message={error2} />}
        {draft && (
          <pre className="text-xs text-stone-600 bg-white border border-stone-200 rounded-lg p-3 mt-3 overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(draft, null, 2)}
          </pre>
        )}
      </div>

      {error && <ErrorBanner message={error} />}
      {loading && !data && <Loading />}
      {data && data.length === 0 && <EmptyState label="No outreach drafts or emails yet." />}
      {data && data.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="data">
            <thead><tr><th>Company</th><th>Job</th><th>Recruiter</th><th>Subject</th><th>Status</th><th>Sent</th><th>Follow-up</th></tr></thead>
            <tbody>
              {data.map((o) => (
                <tr key={o.id}>
                  <td>{o.company || "—"}</td>
                  <td>{o.job_title || "—"}</td>
                  <td>{o.recruiter_name || o.recruiter_email || "—"}</td>
                  <td className="max-w-xs truncate">{o.subject}</td>
                  <td><StatusBadge status={o.status} /></td>
                  <td className="text-xs text-stone-500">{o.sent_at ? new Date(o.sent_at).toLocaleDateString() : "—"}</td>
                  <td className="text-xs text-stone-500">{o.follow_up_at ? new Date(o.follow_up_at).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
