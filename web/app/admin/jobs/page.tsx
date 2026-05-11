"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { adminListAllJobs, listAllJobs, AdminJobSummary } from "@/lib/api";

const SESSION_KEY = "admin_secret";

const STATUS_COLORS: Record<string, string> = {
  done: "text-green-400", running: "text-blue-400", queued: "text-yellow-400",
  failed: "text-red-400", cancelled: "text-gray-500",
};

export default function AdminAllJobsPage() {
  const { getToken } = useAuth();
  const [jobs, setJobs] = useState<AdminJobSummary[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    async function fetchJobs() {
      setJobs(null);
      setError("");
      const secret = sessionStorage.getItem(SESSION_KEY) ?? "";
      if (secret) {
        adminListAllJobs(secret).then(setJobs).catch((e) => setError(String(e)));
        return;
      }
      // Fall back to JWT (pro users)
      try {
        const token = await getToken();
        const data = await listAllJobs(token);
        setJobs(data);
      } catch (e) {
        setError(String(e));
      }
    }
    fetchJobs();
    window.addEventListener("pageshow", fetchJobs);
    return () => window.removeEventListener("pageshow", fetchJobs);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = jobs?.filter((j) => filter === "all" || j.status === filter) ?? [];

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-5xl mx-auto space-y-5">
        <div className="flex items-center gap-3">
          <a href="/admin" className="text-gray-500 hover:text-gray-300 text-sm">← Users</a>
          <span className="text-gray-700">·</span>
          <h1 className="text-lg font-bold">All Jobs</h1>
        </div>

        {error && <p className="text-red-400 text-sm font-mono bg-red-950/30 px-3 py-2 rounded">{error}</p>}

        {jobs === null && !error && (
          <div className="animate-pulse text-gray-600 text-sm">Loading…</div>
        )}

        {jobs && (
          <>
            {/* Filter tabs */}
            <div className="flex items-center gap-2 flex-wrap">
              {["all", "running", "done", "failed", "queued", "cancelled"].map((s) => {
                const count = s === "all" ? jobs.length : jobs.filter((j) => j.status === s).length;
                return (
                  <button
                    key={s}
                    onClick={() => setFilter(s)}
                    className={`text-xs px-3 py-1 rounded-full border font-mono transition-colors ${
                      filter === s
                        ? "border-blue-500 bg-blue-500/20 text-blue-300"
                        : "border-gray-700 text-gray-500 hover:text-gray-300"
                    }`}
                  >
                    {s} <span className="opacity-60">({count})</span>
                  </button>
                );
              })}
            </div>

            <div className="space-y-2">
              {filtered.length === 0 && (
                <p className="text-gray-600 text-sm text-center py-8">No jobs.</p>
              )}
              {filtered.map((j) => (
                <div key={j.job_id} className="rounded-xl border border-gray-800 bg-gray-900/40 px-4 py-3 flex items-center gap-4">
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-xs font-semibold uppercase font-mono ${STATUS_COLORS[j.status] ?? "text-gray-400"}`}>
                        {j.status}
                      </span>
                      <span className="text-sm font-medium text-white truncate">{j.pdf_name}</span>
                      {j.concept_count > 0 && (
                        <span className="text-[10px] text-gray-600 font-mono">{j.concept_count} concepts</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-[10px] text-gray-600 font-mono">
                      <span>{j.job_id}</span>
                      <span>{new Date(j.created_at).toLocaleString()}</span>
                      {j.completed_at && (
                        <span>
                          {Math.round((new Date(j.completed_at).getTime() - new Date(j.created_at).getTime()) / 1000)}s
                        </span>
                      )}
                    </div>
                  </div>
                  <a
                    href={`/jobs/${j.job_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300 shrink-0 transition-colors"
                  >
                    View →
                  </a>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}
