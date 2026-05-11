"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { listJobs, getUsage, JobState, UsageInfo } from "@/lib/api";

const STATUS_DOT: Record<string, string> = {
  done: "bg-green-400",
  running: "bg-blue-400 animate-pulse",
  failed: "bg-red-400",
  queued: "bg-gray-500 animate-pulse",
  cancelled: "bg-gray-600",
};

function NavLink({ href, icon, label, active }: { href: string; icon: React.ReactNode; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-sm font-medium transition-colors
        ${active ? "bg-gray-800 text-white" : "text-gray-400 hover:bg-gray-900 hover:text-gray-200"}`}
    >
      <span className="w-4 h-4 shrink-0 flex items-center justify-center">{icon}</span>
      {label}
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const { getToken } = useAuth();
  const [jobs, setJobs] = useState<JobState[]>([]);
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [hasAdminSecret, setHasAdminSecret] = useState(false);

  useEffect(() => {
    setHasAdminSecret(!!sessionStorage.getItem("admin_secret"));
  }, []);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const [j, u] = await Promise.all([
          listJobs(token),
          getUsage(token).catch(() => null),
        ]);
        setJobs(j);
        setUsage(u);
      } catch {}
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [getToken]);

  const isPro = usage?.tier === "pro";
  const isAdmin = hasAdminSecret || pathname.startsWith("/admin") || isPro;

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
      <div className="px-3 pt-3 pb-1">
        <NavLink
          href="/"
          active={pathname === "/"}
          label="New job"
          icon={
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          }
        />
      </div>

      {/* Usage pill */}
      {usage && (
        <div className="px-4 pb-2">
          <div className="flex items-center justify-between text-[10px] font-mono text-gray-600">
            <span className={isPro ? "text-blue-400/70" : "text-gray-500"}>{usage.tier}</span>
            <span>{usage.jobs_used}/{usage.jobs_limit} jobs</span>
          </div>
          <div className="h-0.5 bg-gray-800 rounded-full mt-1 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${isPro ? "bg-blue-500/50" : "bg-gray-600"}`}
              style={{ width: `${Math.min(100, (usage.jobs_used / usage.jobs_limit) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Jobs list */}
      <div className="flex-1 overflow-y-auto px-3 pb-2 space-y-0.5">
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

      {/* Bottom nav */}
      <div className="px-3 pb-4 pt-2 border-t border-gray-800 space-y-0.5">
        {(isPro || isAdmin) && (
          <>
            <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-widest px-1 py-1.5">
              {isAdmin ? "Admin" : "Pro"}
            </p>
            {isAdmin && (
              <NavLink
                href="/admin"
                active={pathname === "/admin"}
                label="Users"
                icon={
                  <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                }
              />
            )}
            {isAdmin && (
              <NavLink
                href="/admin/jobs"
                active={pathname === "/admin/jobs"}
                label="All jobs"
                icon={
                  <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                  </svg>
                }
              />
            )}
          </>
        )}
      </div>
    </aside>
  );
}
