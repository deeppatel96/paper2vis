"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { listJobs, JobState } from "@/lib/api";

const STATUS_DOT: Record<string, string> = {
  done: "bg-green-400",
  running: "bg-blue-400 animate-pulse",
  failed: "bg-red-400",
  queued: "bg-gray-500 animate-pulse",
  cancelled: "bg-gray-600",
};

export default function Sidebar() {
  const pathname = usePathname();
  const [jobs, setJobs] = useState<JobState[]>([]);

  useEffect(() => {
    listJobs().then(setJobs).catch(() => {});
    const id = setInterval(() => listJobs().then(setJobs).catch(() => {}), 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <aside className="w-56 shrink-0 bg-gray-950 border-r border-gray-800 flex flex-col h-screen sticky top-0 overflow-hidden">
      {/* Branding */}
      <div className="px-4 pt-5 pb-4 border-b border-gray-800">
        <Link href="/" className="block">
          <span className="text-base font-bold tracking-tight text-white">paper2vis</span>
          <p className="text-[10px] text-gray-500 mt-0.5 leading-tight">papers → animations</p>
        </Link>
      </div>

      {/* New job button */}
      <div className="px-3 pt-3 pb-2">
        <Link
          href="/"
          className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm font-medium transition-colors
            ${pathname === "/" ? "bg-blue-600 text-white" : "text-gray-400 hover:bg-gray-800 hover:text-white"}`}
        >
          <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New job
        </Link>
      </div>

      {/* Jobs list */}
      <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-0.5">
        {jobs.length > 0 && (
          <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-widest px-1 py-2">
            Recent jobs
          </p>
        )}
        {jobs.map((job) => {
          const active = pathname === `/jobs/${job.job_id}`;
          const done = job.concepts.filter((c) => c.video_url).length;
          const total = job.concepts.length;
          return (
            <Link
              key={job.job_id}
              href={`/jobs/${job.job_id}`}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors group
                ${active ? "bg-gray-800 text-white" : "text-gray-400 hover:bg-gray-900 hover:text-gray-200"}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOT[job.status] ?? "bg-gray-500"}`} />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium truncate leading-tight">{job.pdf_name}</p>
                <p className="text-[10px] text-gray-600 leading-tight mt-0.5">
                  {total > 0 ? `${done}/${total} animated` : new Date(job.created_at).toLocaleDateString()}
                </p>
                {Array.isArray((job.options as Record<string, unknown>)?.tags) && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {((job.options as Record<string, unknown>).tags as string[]).map((tag) => (
                      <span key={tag} className="text-[9px] px-1 py-0.5 rounded bg-gray-800 text-gray-500 font-mono leading-none">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </Link>
          );
        })}
        {jobs.length === 0 && (
          <p className="text-xs text-gray-700 px-1 pt-2">No jobs yet</p>
        )}
      </div>
    </aside>
  );
}
