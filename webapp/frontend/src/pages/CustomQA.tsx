import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { PageHeader, Loading, ErrorBanner, EmptyState } from "../components/ui";

export default function CustomQA() {
  const { data, error, loading, refresh } = usePolling(() => api.qaList(), 20000);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const save = async () => {
    if (!question.trim() || !answer.trim()) return;
    setBusy(true); setActionError(null);
    try { await api.qaSave(question, answer); setQuestion(""); setAnswer(""); refresh(); }
    catch (e) { setActionError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const remove = async (id: number) => {
    setBusy(true); setActionError(null);
    try { await api.qaDelete(id); refresh(); }
    catch (e) { setActionError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return <div>
    <PageHeader title="Custom Q&A" subtitle="Persistent answers used by the current agent's deterministic Q&A memory. Exact/owned answers stay separate from generic project reasoning." />
    {actionError && <ErrorBanner message={actionError} />}
    <div className="card max-w-3xl space-y-3 mb-5">
      <input className="w-full bg-white border border-stone-200 rounded-lg px-3 py-2 text-sm" placeholder="Application question" value={question} onChange={e=>setQuestion(e.target.value)} />
      <textarea className="w-full bg-white border border-stone-200 rounded-lg px-3 py-2 text-sm" rows={5} placeholder="Saved answer" value={answer} onChange={e=>setAnswer(e.target.value)} />
      <button className="btn btn-primary" disabled={busy || !question.trim() || !answer.trim()} onClick={save}>{busy ? "Saving…" : "Save Q&A"}</button>
      <p className="text-xs text-stone-500">These entries are written directly to the same root applications.db custom_qa table used by the agent.</p>
    </div>
    {error && <ErrorBanner message={error} />}
    {loading && !data && <Loading />}
    {data && data.length === 0 && <EmptyState label="No saved Q&A entries." />}
    {data && data.length > 0 && <div className="space-y-3">{data.map(q => <div key={q.id} className="card">
      <div className="text-xs text-stone-400 mb-1">#{q.id}</div>
      <div className="text-sm text-stone-700"><b>Q:</b> {q.question}</div>
      <div className="text-sm text-stone-600 mt-2 whitespace-pre-wrap"><b>A:</b> {q.answer}</div>
      <button className="btn btn-danger mt-3 !px-2 !py-1 text-xs" disabled={busy} onClick={()=>remove(q.id)}>Delete</button>
    </div>)}</div>}
  </div>;
}
