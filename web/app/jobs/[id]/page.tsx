"use client";
import { use, useEffect, useState, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import { getJob, streamJob, cancelJob, JobState } from "@/lib/api";
import ConceptCard, { ConceptSkeleton } from "@/components/ConceptCard";
import { DashboardStats, PipelineStageTracker, ActivityFeed } from "@/components/Dashboard";
import PaperTab from "@/components/PaperTab";
import InteractiveConceptMap from "@/components/InteractiveConceptMap";
import ConceptSelectionPanel from "@/components/ConceptSelectionPanel";
import LLMPreviewPanel from "@/components/LLMPreviewPanel";

export default function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { getToken } = useAuth();
  const [job, setJob] = useState<JobState | null>(null);
  const [showPaper, setShowPaper] = useState(false);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const [liveOutputs, setLiveOutputs] = useState<Map<string, string>>(new Map());

  const refresh = useCallback(async () => {
    try {
      const token = await getToken();
      const j = await getJob(id, token);
      setJob(j);
    } catch (err) {
      console.error(err);
    }
  }, [id, getToken]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!id) return;
    const stop = streamJob(
      id,
      (event) => {
        if (event.type === "llm_output" && event.index !== undefined && event.stage && event.content !== undefined) {
          setLiveOutputs((prev) => {
            const next = new Map(prev);
            next.set(`${event.index}:${event.stage}`, event.content!);
            return next;
          });
        }
        refresh();
      },
      () => refresh(),
    );
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, streamEpoch]);

  const handleRegenerated = useCallback(() => {
    setStreamEpoch((e) => e + 1);
  }, []);

  const handleCancel = useCallback(async () => {
    try {
      const token = await getToken();
      await cancelJob(id, token);
      refresh();
    } catch (err) { console.error(err); }
  }, [id, getToken, refresh]);

  if (!job) {
    return (
      <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        <div className="animate-pulse text-gray-500">Loading…</div>
      </main>
    );
  }

  const isActive = job.status === "running" || job.status === "queued";
  const stubs = job.concept_stubs.length > 0
    ? job.concept_stubs
    : job.concepts.map((c) => ({ index: c.index, name: c.name, visual_type: c.visual_type, description: c.description }));

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-5xl mx-auto space-y-5">

        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-bold truncate">{job.pdf_name}</h1>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <StatusBadge status={job.status} />
              <span className="text-gray-700 text-xs">·</span>
              <span className="text-xs text-gray-600 font-mono">{job.job_id}</span>
              <span className="text-gray-700 text-xs">·</span>
              <span className="text-xs text-gray-600">{new Date(job.created_at).toLocaleString()}</span>
            </div>
            {Array.isArray((job.options as Record<string, unknown>)?.tags) && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {((job.options as Record<string, unknown>).tags as string[]).map((tag) => (
                  <span key={tag} className="text-[10px] px-2 py-0.5 rounded-full bg-gray-800 border border-gray-700 text-gray-400 font-mono">
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {job.figures.length > 0 && (
              <button
                onClick={() => setShowPaper((v) => !v)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors font-medium ${
                  showPaper
                    ? "border-blue-600 text-blue-300 bg-blue-950"
                    : "border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200"
                }`}
              >
                {showPaper ? "Hide Figures" : `Figures (${job.figures.length})`}
              </button>
            )}
            {isActive && (
              <button
                onClick={handleCancel}
                className="text-xs px-3 py-1.5 rounded-lg border border-red-800 text-red-400 hover:bg-red-950 hover:border-red-600 transition-colors font-medium"
              >
                Cancel
              </button>
            )}
          </div>
        </div>

        {/* ── Stats ──────────────────────────────────────────────────── */}
        <DashboardStats job={job} />

        {/* ── Pipeline stage tracker (while running) ─────────────────── */}
        {(isActive || job.progress.length > 0) && (
          <PipelineStageTracker job={job} />
        )}

        {/* ── Novel contribution banner ───────────────────────────────── */}
        {job.novelty && (
          <div className="rounded-xl border border-blue-800/50 bg-blue-950/20 px-4 py-3 space-y-1.5">
            <p className="text-xs font-bold uppercase tracking-widest text-blue-400">Novel contribution detected</p>
            <p className="text-sm text-white">{job.novelty.contribution}</p>
            {job.novelty.key_mechanism && (
              <p className="text-xs text-gray-400"><span className="text-gray-500">Mechanism:</span> {job.novelty.key_mechanism}</p>
            )}
            {job.novelty.prior_limitation && (
              <p className="text-xs text-gray-400"><span className="text-gray-500">Addresses:</span> {job.novelty.prior_limitation}</p>
            )}
            {job.novelty.focus_keywords?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-0.5">
                {job.novelty.focus_keywords.map((kw) => (
                  <span key={kw} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-900/50 border border-blue-700/50 text-blue-300 font-mono">{kw}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Concept map (shown once concepts are known) ─────────────── */}
        {stubs.length > 0 && (
          <InteractiveConceptMap
            concepts={stubs.map((s) => ({ index: s.index, name: s.name, visual_type: s.visual_type }))}
            edges={job.concept_edges ?? []}
            graphVideoUrl={job.graph_video_url}
          />
        )}

        {/* ── Concept selection gate (when pipeline is paused for user input) ── */}
        {job.awaiting_selection && (
          stubs.length > 0
            ? <ConceptSelectionPanel jobId={job.job_id} stubs={stubs} />
            : <div className="border border-yellow-800 bg-yellow-950/30 rounded-xl p-5 text-center text-yellow-400 text-sm">
                Waiting for concept selection… (no concepts extracted yet — check the activity feed below)
              </div>
        )}

        {/* ── LLM live output preview ─────────────────────────────────── */}
        <LLMPreviewPanel outputs={liveOutputs} stubs={stubs} />

        {/* ── Concept cards — appear live as each finishes ────────────── */}
        {stubs.length === 0 && isActive && !job.awaiting_selection && (
          <div className="text-center py-10 text-gray-600 text-sm animate-pulse">
            Extracting concepts from paper…
          </div>
        )}
        {stubs.length === 0 && !isActive && job.concepts.length === 0 && (
          <div className="text-center py-10 text-gray-600 text-sm">No concepts extracted.</div>
        )}
        {stubs.length > 0 && !job.awaiting_selection && (
          <div className="space-y-4">
            {topoSort(stubs, job.concept_edges ?? []).map((stub) => {
              const full = job.concepts.find((c) => c.index === stub.index);
              return full
                ? <ConceptCard key={stub.index} concept={full} />
                : <ConceptSkeleton key={stub.index} name={stub.name} visual_type={stub.visual_type} hasFigures={!!job.options.figure_context} />;
            })}
          </div>
        )}

        {/* ── Paper figures (toggled) ─────────────────────────────────── */}
        {showPaper && (
          <div className="border-t border-gray-800 pt-5">
            <PaperTab job={job} onRegenerated={handleRegenerated} />
          </div>
        )}

        {/* ── Activity feed ───────────────────────────────────────────── */}
        <ActivityFeed progress={job.progress} error={job.error} />

      </div>
    </main>
  );
}

function topoSort<T extends { index: number }>(
  items: T[],
  edges: Array<{ from: number; to: number; label: string }>,
): T[] {
  // Kahn's algorithm — prerequisites before dependents
  // Only reorder when "prerequisite" edges exist; otherwise preserve original order
  const prereqEdges = edges.filter((e) => e.label === "prerequisite");
  if (prereqEdges.length === 0) return items;

  const indexSet = new Set(items.map((i) => i.index));
  const inDegree = new Map<number, number>();
  const adj = new Map<number, number[]>();
  items.forEach((i) => { inDegree.set(i.index, 0); adj.set(i.index, []); });
  prereqEdges.forEach(({ from, to }) => {
    if (!indexSet.has(from) || !indexSet.has(to)) return;
    // "from is prerequisite" means from → to: from must come before to
    adj.get(from)!.push(to);
    inDegree.set(to, (inDegree.get(to) ?? 0) + 1);
  });

  const queue = items.filter((i) => (inDegree.get(i.index) ?? 0) === 0).map((i) => i.index);
  const result: T[] = [];
  const itemMap = new Map(items.map((i) => [i.index, i]));
  while (queue.length > 0) {
    const idx = queue.shift()!;
    result.push(itemMap.get(idx)!);
    (adj.get(idx) ?? []).forEach((next) => {
      const d = (inDegree.get(next) ?? 1) - 1;
      inDegree.set(next, d);
      if (d === 0) queue.push(next);
    });
  }
  // Append any remaining (cycle or disconnected)
  const seen = new Set(result.map((i) => i.index));
  items.forEach((i) => { if (!seen.has(i.index)) result.push(i); });
  return result;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    queued: "text-yellow-400",
    running: "text-blue-400",
    done: "text-green-400",
    failed: "text-red-400",
    cancelled: "text-gray-400",
  };
  const labels: Record<string, string> = {
    queued: "Queued", running: "Running", done: "Complete",
    failed: "Failed", cancelled: "Cancelled",
  };
  return (
    <span className={`text-xs font-semibold uppercase font-mono flex items-center gap-1.5 ${colors[status] ?? "text-gray-400"}`}>
      {status === "running" && (
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
      )}
      {labels[status] ?? status}
    </span>
  );
}
