"use client";
import { JobStatus } from "@/lib/api";

interface Props {
  messages: string[];
  status: JobStatus;
  error: string | null;
}

const statusColors: Record<JobStatus, string> = {
  queued: "text-yellow-400",
  running: "text-blue-400",
  done: "text-green-400",
  failed: "text-red-400",
  cancelled: "text-gray-400",
};

const statusLabels: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Running",
  done: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
};

export default function JobProgress({ messages, status, error }: Props) {
  return (
    <div className="rounded-xl bg-gray-900 border border-gray-700 p-4 space-y-3">
      <div className="flex items-center gap-2">
        {status === "running" && (
          <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
        )}
        <span className={`text-sm font-semibold ${statusColors[status]}`}>
          {statusLabels[status]}
        </span>
      </div>

      <div className="font-mono text-xs text-gray-400 space-y-0.5 max-h-48 overflow-y-auto">
        {messages.map((m, i) => (
          <div key={i} className="leading-5">
            <span className="text-gray-600 select-none mr-2">{String(i + 1).padStart(2, "0")}</span>
            {m}
          </div>
        ))}
        {messages.length === 0 && <div className="text-gray-600 italic">Waiting to start…</div>}
      </div>

      {error && (
        <div className="rounded bg-red-950 border border-red-800 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}
    </div>
  );
}
