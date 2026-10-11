import { useMemo, useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api, ApiError } from "../api/client";
import { PageHeader, Loading, ErrorBanner, StatusBadge } from "../components/ui";

export default function ResumeTailoring() {
  const { data: jobs, refresh: refreshJobs } = usePolling(() => api.jobs({ limit: 100 }), 20000);
  const { data: master, error: masterError } = usePolling(() => api.masterResume(), 300000);
  const { data: contentBank, error: contentBankError } = usePolling(() => api.resumeContentBank(), 300000);
  const [selectedJob, setSelectedJob] = useState<string | "">("");
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.tailorResume>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshingMetadata, setRefreshingMetadata] = useState(false);
  const [routeFilter, setRouteFilter] = useState<"all" | "native" | "external">("all");
  const [eligibilityFilter, setEligibilityFilter] = useState<"all" | "eligible" | "ineligible">("all");

  const filteredJobs = useMemo(() => {
    return (jobs || []).filter((j) => {
      const routeOk = routeFilter === "all" || j.application_route === routeFilter;
      const eligibleOk =
        eligibilityFilter === "all" ||
        (eligibilityFilter === "eligible" && j.eligible === 1) ||
        (eligibilityFilter === "ineligible" && j.eligible === 0);
      return routeOk && eligibleOk;
    });
  }, [jobs, routeFilter, eligibilityFilter]);

  const refreshMetadata = async () => {
    if (!selectedJob) return;
    setRefreshingMetadata(true);
    setError(null);
    try {
      const r = await api.refreshJobMetadata(String(selectedJob));
      await refreshJobs();
      if (!r.updated) setError(r.message || "No matching open portal job tab was found.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRefreshingMetadata(false);
    }
  };

  const run = async () => {
    if (!selectedJob) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.tailorResume(String(selectedJob));
      setResult(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const job = jobs?.find((j) => (j.job_ref || `${j.source}:${j.id}`) === String(selectedJob));

  return (
    <div>
      <PageHeader
        title="Resume Tailoring"
        subtitle="Master resume is the source of truth -- it is never overwritten. Each build writes a new job-specific version."
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <h2 className="text-sm font-medium text-stone-700 mb-3">1. Pick a job, build the tailored resume</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3">
            <select value={routeFilter} onChange={(e) => setRouteFilter(e.target.value as typeof routeFilter)} className="bg-white border border-stone-200 rounded-lg px-3 py-1.5 text-sm">
              <option value="all">All application types</option>
              <option value="native">Native Apply</option>
              <option value="external">External Apply</option>
            </select>
            <select value={eligibilityFilter} onChange={(e) => setEligibilityFilter(e.target.value as typeof eligibilityFilter)} className="bg-white border border-stone-200 rounded-lg px-3 py-1.5 text-sm">
              <option value="all">All eligibility</option>
              <option value="eligible">Eligible jobs</option>
              <option value="ineligible">Ineligible jobs</option>
            </select>
            <select
              value={selectedJob}
              onChange={(e) => setSelectedJob(e.target.value || "")}
              className="bg-white border border-stone-200 rounded-lg px-3 py-1.5 text-sm"
            >
              <option value="">Select a job…</option>
              {filteredJobs.map((j) => (
                <option key={j.job_ref || `${j.source}:${j.id}`} value={j.job_ref || `${j.source}:${j.id}`}>{j.title} · {j.company} · {j.source}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2 mb-3">
            <button className="btn btn-ghost" disabled={!selectedJob || refreshingMetadata} onClick={refreshMetadata}>
              {refreshingMetadata ? "Refreshing…" : "Refresh Job Data"}
            </button>
            <button className="btn btn-primary" disabled={!selectedJob || busy} onClick={run}>
              {busy ? "Building…" : "Tailor Resume"}
            </button>
            {job?.url && <a href={job.url} target="_blank" rel="noreferrer" className="btn btn-ghost">Open Job Link</a>}
          </div>
          {job && (
            <div className="mt-3 border-t border-stone-200 pt-3 space-y-2">
              <div className="text-sm text-stone-700"><strong>{job.company || "Unknown company"}</strong> · {job.title}</div>
              <div className="text-xs text-stone-500">Portal: {job.source} · Job ref: {job.job_ref} · Route: {job.application_route === "native" ? "Native Apply" : job.application_route === "external" ? "External Apply" : "Unknown"} · Eligibility: {job.eligible === 1 ? "Eligible" : job.eligible === 0 ? "Ineligible" : "Unknown"}</div>
              {job.url && <a href={job.url} target="_blank" rel="noreferrer" className="text-xs text-emerald-700 hover:underline break-all">{job.url}</a>}
              <p className="text-xs text-stone-500 whitespace-pre-wrap line-clamp-6">{job.description || "(no description stored)"}</p>
            </div>
          )}

          {error && <div className="mt-3"><ErrorBanner message={error} /></div>}

          {result && (
            <div className="mt-4 border-t border-stone-200 pt-4 space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-stone-600">Metrics preserved:</span>
                <StatusBadge status={result.metrics_preserved ? "OK" : "FAIL"} />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-stone-600">PDF compiled:</span>
                <StatusBadge status={result.pdf_path ? "OK" : "WARN"} />
              </div>
              <p className="text-stone-600">
                Matched skills: <span className="text-stone-900">{result.matched_skills.join(", ") || "(none)"}</span>
              </p>
              {result.tailoring_report?.content_bank_options?.length ? (
                <details className="text-xs text-emerald-700">
                  <summary className="cursor-pointer">Relevant content-bank options ({result.tailoring_report.content_bank_options.length})</summary>
                  <div className="mt-2 space-y-2">
                    {result.tailoring_report.content_bank_options.map((x: any, i: number) => (
                      <div key={i} className="rounded-lg border border-stone-200 bg-white p-2">
                        <div className="text-stone-900">{x.title}</div>
                        <div className="text-stone-400">{x.type} · {x.source}</div>
                        <div className="text-stone-500">Matched: {(x.matched_signals || []).join(", ")}</div>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
              {result.pdf_path && <a href={api.resumePdfUrl(String(selectedJob))} target="_blank" rel="noreferrer" className="btn btn-primary inline-flex w-fit">Open Stored Tailored PDF</a>}
              {result.tailoring_report && (
                <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">JD keywords</div>
                    <div className="text-stone-900">{result.tailoring_report.keyword_inventory_count ?? 0}</div>
                  </div>
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">JD phrases</div>
                    <div className="text-stone-900">{result.tailoring_report.phrase_inventory_count ?? 0}</div>
                  </div>
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">Actually added</div>
                    <div className="text-stone-900">{result.tailoring_report.added_keywords?.length ?? 0}</div>
                  </div>
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">Bullets rewritten</div>
                    <div className="text-stone-900">{result.tailoring_report.rewritten_bullets?.length ?? 0}</div>
                  </div>
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">Unsupported</div>
                    <div className="text-stone-900">{result.tailoring_report.unsupported_keywords?.length ?? 0}</div>
                  </div>
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">Quantification gaps</div>
                    <div className="text-stone-900">{result.tailoring_report.quantification_gaps?.length ?? 0}</div>
                  </div>
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">Authenticity flags</div>
                    <div className="text-stone-900">{result.tailoring_report.authenticity_flags?.length ?? 0}</div>
                  </div>
                  <div className="rounded-lg border border-stone-200 bg-white p-2">
                    <div className="text-xs text-stone-500">PDF verification</div>
                    <div className="text-stone-900">{result.tailoring_report.verification?.one_page && result.tailoring_report.verification?.hyperlinks_checked ? "PASS" : "CHECK"}</div>
                  </div>
                </div>
              )}
              {result.tailoring_report?.cv_check ? (
                <div className="rounded-lg border border-stone-200 bg-white p-2 text-xs text-stone-600">
                  <div className="text-stone-700">CV keyword check: <span className={result.tailoring_report.cv_check.status === "PASS" ? "text-emerald-700" : "text-amber-700"}>{result.tailoring_report.cv_check.status}</span></div>
                  <div className="mt-1">{result.tailoring_report.cv_check.coverage_percent ?? 0}% coverage · {result.tailoring_report.cv_check.exact_matches ?? 0} exact · {result.tailoring_report.cv_check.near_matches ?? 0} near · {result.tailoring_report.cv_check.missing_matches ?? 0} missing</div>
                </div>
              ) : null}
              {result.tailoring_report?.stronger_bullet_selections?.length ? (
                <details className="text-xs text-emerald-700">
                  <summary className="cursor-pointer">Stronger metric-locked bullets selected ({result.tailoring_report.stronger_bullet_selections.length})</summary>
                  <ul className="mt-1 space-y-1 text-stone-500">
                    {result.tailoring_report.stronger_bullet_selections.map((x, i) => <li key={i}>{x.project} · bullet {x.bullet_index} · metrics locked: {(x.metric_locks || []).join(", ")}</li>)}
                  </ul>
                </details>
              ) : null}
              {result.tailoring_report?.bullet_style_check && !result.tailoring_report.bullet_style_check.pass ? (
                <details className="text-xs text-amber-700">
                  <summary className="cursor-pointer">Bullet style checks needing review ({result.tailoring_report.bullet_style_check.issues?.length ?? 0})</summary>
                  <ul className="mt-1 space-y-1 text-stone-500">
                    {(result.tailoring_report.bullet_style_check.issues || []).map((x, i) => <li key={i}>{x.project} · bullet {x.bullet_index} · {x.issue}</li>)}
                  </ul>
                </details>
              ) : null}
              {result.tailoring_report?.added_keywords?.length ? (
                <p className="text-xs text-emerald-700">
                  Added exact JD wording: {result.tailoring_report.added_keywords.join(", ")}
                </p>
              ) : null}
              {result.tailoring_report?.unsupported_keywords?.length ? (
                <details className="text-xs text-amber-700">
                  <summary className="cursor-pointer">Unsupported JD keywords: {result.tailoring_report.unsupported_keywords.length}</summary>
                  <p className="mt-1 text-stone-500">
                    {result.tailoring_report.unsupported_keywords.map((x) => x.keyword).join(", ")}
                  </p>
                </details>
              ) : null}
              {result.tailoring_report?.authenticity_flags?.length ? (
                <details className="text-xs text-amber-700">
                  <summary className="cursor-pointer">Authenticity review flags</summary>
                  <ul className="mt-1 space-y-1 text-stone-500">
                    {result.tailoring_report.authenticity_flags.map((x, i) => <li key={i}>{x.overlap}</li>)}
                  </ul>
                </details>
              ) : null}
              {result.tailoring_report?.rewritten_bullets?.length ? (
                <details className="text-xs text-emerald-700">
                  <summary className="cursor-pointer">Rewritten project bullets ({result.tailoring_report.rewritten_bullets.length})</summary>
                  <ul className="mt-1 space-y-1 text-stone-500">
                    {result.tailoring_report.rewritten_bullets.map((x, i) => <li key={i}>{x.project} · bullet {x.bullet_index} · {x.keyword}</li>)}
                  </ul>
                </details>
              ) : null}
              {result.tailoring_report?.matched_keywords?.length ? (
                <details className="text-xs text-stone-600">
                  <summary className="cursor-pointer">Keyword match table ({result.tailoring_report.matched_keywords.length})</summary>
                  <div className="mt-2 max-h-64 overflow-y-auto border border-stone-200 rounded-lg">
                    {result.tailoring_report.matched_keywords.map((x, i) => (
                      <div key={i} className="grid grid-cols-3 gap-2 px-2 py-1 border-b border-stone-100">
                        <span className="text-stone-700">{x.keyword}</span>
                        <span className={x.in_resume ? "text-emerald-700" : "text-amber-700"}>{x.in_resume ? x.match_type : "no"}</span>
                        <span className="text-stone-400 break-words">{x.exact_wording_used || "—"}</span>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
              {result.tailoring_report?.quantification_gaps?.length ? (
                <details className="text-xs text-amber-700">
                  <summary className="cursor-pointer">Bullets without measurable data ({result.tailoring_report.quantification_gaps.length})</summary>
                  <ul className="mt-1 space-y-1 text-stone-500">
                    {result.tailoring_report.quantification_gaps.map((x, i) => <li key={i}>{x.project} · bullet {x.bullet_index}</li>)}
                  </ul>
                </details>
              ) : null}
              {result.tailoring_report?.analysis_data_repetition_flags?.length ? (
                <details className="text-xs text-amber-700">
                  <summary className="cursor-pointer">Analysis/data wording flags ({result.tailoring_report.analysis_data_repetition_flags.length})</summary>
                  <ul className="mt-1 space-y-1 text-stone-500">
                    {result.tailoring_report.analysis_data_repetition_flags.map((x, i) => <li key={i}>{x.project} · bullet {x.bullet_index}: {x.text}</li>)}
                  </ul>
                </details>
              ) : null}
              <p className="text-xs text-stone-400 break-all">.tex: {result.tex_path}</p>
              {result.pdf_path && <p className="text-xs text-stone-400 break-all">PDF: {result.pdf_path}</p>}
              {result.compile_error && (
                <details className="text-xs text-amber-700">
                  <summary className="cursor-pointer">Compile warning</summary>
                  <pre className="whitespace-pre-wrap text-stone-500 mt-1">{result.compile_error}</pre>
                </details>
              )}
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="text-sm font-medium text-stone-700 mb-3">Resume Content Bank — source-verified options</h2>
          <p className="text-xs text-stone-500 mb-3">Extracted resume variants are kept as selectable evidence for future tailoring. The master resume is not overwritten by this bank.</p>
          {contentBankError && <ErrorBanner message={String(contentBankError)} />}
          {!contentBank && !contentBankError && <Loading />}
          {contentBank && (
            <div className="space-y-2 text-xs">
              <details open className="rounded-lg border border-stone-200 bg-white p-3">
                <summary className="cursor-pointer text-stone-700">Project options ({contentBank.project_options.length})</summary>
                <div className="mt-2 space-y-2">
                  {contentBank.project_options.map((p) => (
                    <details key={p.id} className="rounded-md border border-stone-100 p-2">
                      <summary className="cursor-pointer text-stone-900">{p.title} <span className="text-stone-400">· {p.tech_stack.join(", ")}</span></summary>
                      <div className="mt-2 space-y-2">
                        <div><span className="text-stone-400">Keywords: </span><span className="text-stone-600">{p.keywords.join(", ")}</span></div>
                        <ul className="list-disc ml-5 space-y-1 text-stone-500">
                          {p.bullets.map((b, i) => <li key={i}>{b}</li>)}
                        </ul>
                        <div><span className="text-stone-400">Metrics: </span><span className="text-stone-600">{p.metrics.join(", ") || "—"}</span></div>
                      </div>
                    </details>
                  ))}
                </div>
              </details>
              <details className="rounded-lg border border-stone-200 bg-white p-3">
                <summary className="cursor-pointer text-stone-700">Professional summary options ({contentBank.professional_summary_options.length})</summary>
                <div className="mt-2 space-y-2">
                  {contentBank.professional_summary_options.map((s) => (
                    <div key={s.id} className="rounded-md border border-stone-100 p-2">
                      <div className="text-stone-500 mb-1">{s.tags.join(" · ")}</div>
                      <div className="text-stone-700">{s.text}</div>
                    </div>
                  ))}
                </div>
              </details>
              <details className="rounded-lg border border-stone-200 bg-white p-3">
                <summary className="cursor-pointer text-stone-700">Keyword options ({Object.keys(contentBank.keyword_options).length} groups)</summary>
                <div className="mt-2 space-y-2">
                  {Object.entries(contentBank.keyword_options).map(([group, items]) => (
                    <div key={group}>
                      <div className="text-stone-500 font-medium">{group}</div>
                      <div className="text-stone-600">{items.join(", ")}</div>
                    </div>
                  ))}
                </div>
              </details>
              <details className="rounded-lg border border-stone-200 bg-white p-3">
                <summary className="cursor-pointer text-stone-700">Skill-set options ({contentBank.skill_options.length})</summary>
                <div className="mt-2 space-y-2">
                  {contentBank.skill_options.map((s) => (
                    <div key={s.id} className="rounded-md border border-stone-100 p-2">
                      <div className="text-stone-700">{s.label}</div>
                      <div className="text-stone-500">{s.items.join(", ")}</div>
                    </div>
                  ))}
                </div>
              </details>
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="text-sm font-medium text-stone-700 mb-3">Master resume (source of truth, read-only)</h2>
          {masterError && <ErrorBanner message={masterError} />}
          {!master && !masterError && <Loading />}
          {master && (
            <>
              <p className="text-xs text-stone-400 mb-2 break-all">{master.path}</p>
              <pre className="text-xs text-stone-600 max-h-96 overflow-y-auto whitespace-pre-wrap bg-white rounded-lg p-3 border border-stone-200">
                {master.content}
              </pre>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
