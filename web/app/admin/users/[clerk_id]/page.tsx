"use client";
import { use, useEffect, useState } from "react";
import { adminListUserJobs, AdminJobSummary } from "@/lib/api";

const SESSION_KEY = "admin_secret";

export default function AdminUserJobsPage({ params }: {
  params: Promise<{ clerk_id: string }>;
}) {
  const { clerk_id } = use(params);
  const [jobs, setJobs] = useState<AdminJobSummary[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    function fetchJobs() {
      const secret = sessionStorage.getItem(SESSION_KEY) ?? "";
      if (!secret) { setError("No admin secret — go back and log in."); return; }
      setJobs(null);
      setError("");
      adminListUserJobs(secret, clerk_id)
        .then(setJobs)
        .catch((e) => setError(String(e)));
    }
    fetchJobs();
    window.addEventListener("pageshow", fetchJobs);
    return () => window.removeEventListener("pageshow", fetchJobs);
  }, [clerk_id]);

  const statusColors: Record<string, string> = {
    done: "text-green-400", running: "text-blue-400", queued: "text-yellow-400",
    failed: "text-red-400", cancelled: "text-gray-500",
  };

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-4xl mx-auto space-y-5">
        <div className="flex items-center gap-3">
          <a href="/admin" className="text-gray-500 hover:text-gray-300 text-sm">← Users</a>
          <span className="text-gray-700">·</span>
          <h1 className="text-sm font-mono text-gray-400">{clerk_id}</h1>
        </div>

        {error && <p className="text-red-400 text-sm font-mono">{error}</p>}

        {jobs === null && !error && (
          <div className="animate-pulse text-gray-600 text-sm">Loading…</div>
        )}

        {jobs && (
          <div className="space-y-2">
            <p className="text-xs text-gray-500">{jobs.length} job{jobs.length !== 1 ? "s" : ""}</p>
            <div className="space-y-3">
              {jobs.length === 0 && (
                <p className="text-gray-600 text-sm text-center py-8">No jobs found.</p>
              )}
              {jobs.map((j) => {
                const tags = (j.options as Record<string, unknown>)?.tags as string[] | undefined;
                return (
                  <div key={j.job_id} className="rounded-xl border border-gray-800 bg-gray-900/40 p-4 space-y-2">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 space-y-1">
                        <p className="text-sm font-medium truncate">{j.pdf_name}</p>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-xs font-semibold uppercase font-mono ${statusColors[j.status] ?? "text-gray-400"}`}>
                            {j.status}
                          </span>
                          <span className="text-gray-700 text-xs">·</span>
                          <span className="text-xs text-gray-600 font-mono">{j.job_id}</span>
                          <span className="text-gray-700 text-xs">·</span>
                          <span className="text-xs text-gray-600">{new Date(j.created_at).toLocaleString()}</span>
                          {j.concept_count > 0 && (
                            <>
                              <span className="text-gray-700 text-xs">·</span>
                              <span className="text-xs text-gray-600">{j.concept_count} concept{j.concept_count !== 1 ? "s" : ""}</span>
                            </>
                          )}
                        </div>
                        {tags && tags.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {tags.map((tag) => (
                              <span key={tag} className="text-[10px] px-2 py-0.5 rounded-full bg-gray-800 border border-gray-700 text-gray-400 font-mono">
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <a
                        href={`/jobs/${j.job_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="shrink-0 text-xs px-3 py-1.5 rounded-lg border border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200 transition-colors font-medium"
                      >
                        View job ↗
                      </a>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
