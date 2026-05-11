"use client";

import { JobState, ConceptResult } from "@/lib/api";

// ── Parsing helpers ──────────────────────────────────────────────────────────

function parseCritiqueScore(md: string | null): { score: number | null; passes: boolean | null } {
  if (!md) return { score: null, passes: null };
  const s = md.match(/\*\*Score:\*\* (\d+)\/10/);
  const p = md.match(/\*\*(PASS|FAIL)\*\*/);
  return {
    score: s ? parseInt(s[1]) : null,
    passes: p ? p[1] === "PASS" : null,
  };
}

function escRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

interface ConceptMetrics {
  index: number;
  name: string;
  visual_type: string;
  score: number | null;
  passes: boolean | null;
  renderAttempts: number;
  visualDiffRuns: number;
  visualDiffImproved: boolean;
  hasVideo: boolean;
  hasFigure: boolean;
  stages: StageStatus[];
  duration_ms: number | null;
}

type StageState = "done" | "running" | "failed" | "skip" | "pending";
interface StageStatus { label: string; state: StageState }

function buildConceptMetrics(concept: ConceptResult, progress: string[]): ConceptMetrics {
  const { score, passes } = parseCritiqueScore(concept.critique_md);
  const name = concept.name;
  const re = (pat: string) => new RegExp(pat.replace("NAME", escRe(name)));

  let renderAttempts = concept.video_url ? 1 : 0;
  let visualDiffRuns = 0;
  let visualDiffImproved = false;

  for (const msg of progress) {
    const attemptMatch = msg.match(re("\\[NAME\\] Rendering \\(attempt (\\d+)"));
    if (attemptMatch) renderAttempts = Math.max(renderAttempts, parseInt(attemptMatch[1]));

    const vdMatch = msg.match(re("\\[NAME\\] Visual diff pass (\\d+)"));
    if (vdMatch) visualDiffRuns = Math.max(visualDiffRuns, parseInt(vdMatch[1]));

    if (re("\\[NAME\\] Visual diff pass \\d+: re-rendered").test(msg)) {
      visualDiffImproved = true;
    }
  }

  // Build stage pipeline
  const codegenDone = progress.some((m) => re("\\[NAME\\] (Generating code|Planning storyboard)").test(m));
  const renderDone = !!concept.video_url;
  const criticDone = score !== null;
  const vdDone = visualDiffRuns > 0;

  const stages: StageStatus[] = [
    { label: "Codegen", state: codegenDone ? "done" : "pending" },
    { label: `Render${renderAttempts > 1 ? ` ×${renderAttempts}` : ""}`, state: renderDone ? "done" : (renderAttempts > 0 ? "failed" : "pending") },
    { label: `Diff${visualDiffRuns > 0 ? ` ×${visualDiffRuns}` : ""}`, state: visualDiffRuns > 0 ? (visualDiffImproved ? "done" : "skip") : "skip" },
    { label: "Critic", state: criticDone ? (passes ? "done" : "failed") : "pending" },
  ];

  return {
    index: concept.index,
    name,
    visual_type: concept.visual_type,
    score,
    passes,
    renderAttempts,
    visualDiffRuns,
    visualDiffImproved,
    hasVideo: !!concept.video_url,
    hasFigure: !!concept.figure_url,
    stages,
    duration_ms: concept.duration_ms ?? null,
  };
}

// ── Timing + cost helpers ────────────────────────────────────────────────────

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

// GPT-4o cost model ($/1M tokens): input $2.50, output $10.00
// Per concept: validate ~1.5k in/750 out, storyboard ~1k in/400 out, codegen ~1.5k in/750 out
// Critic: ~750 in/250 out; apply_instruction: ~2k in/750 out
// Per error fix: ~2k in/750 out; per visual diff: ~1.5k in/600 out
const GPT4O_IN = 2.50 / 1e6;
const GPT4O_OUT = 10.0 / 1e6;
function estConceptCost(renderAttempts: number, visualDiffRuns: number, hasVideo: boolean, criticPasses: boolean | null): number {
  // Calls always made: validate_code + storyboard + codegen
  const base = (1500 + 1000 + 1500) * GPT4O_IN + (750 + 400 + 750) * GPT4O_OUT;
  // fix_code per failed render attempt
  const fixes = Math.max(0, renderAttempts - 1) * (2000 * GPT4O_IN + 750 * GPT4O_OUT);
  const diffs = visualDiffRuns * (1500 * GPT4O_IN + 600 * GPT4O_OUT);
  // Critic only runs when a video was produced
  const criticBase = hasVideo ? (750 * GPT4O_IN + 250 * GPT4O_OUT) : 0;
  // If critic fails, a fix pass also ran
  const criticFix = (hasVideo && criticPasses === false) ? (2000 + 750) * GPT4O_IN + (750 + 250) * GPT4O_OUT : 0;
  return base + fixes + diffs + criticBase + criticFix;
}

// ── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-1">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold font-mono ${color ?? "text-white"}`}>{value}</div>
      {sub && <div className="text-xs text-gray-600">{sub}</div>}
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = (score / 10) * 100;
  const color = score >= 7 ? "bg-green-500" : score >= 5 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-300">{score}/10</span>
    </div>
  );
}

function StagePip({ label, state }: StageStatus) {
  const styles: Record<StageState, string> = {
    done: "bg-green-500/20 border-green-500 text-green-400",
    running: "bg-blue-500/20 border-blue-500 text-blue-300 animate-pulse",
    failed: "bg-red-500/20 border-red-500 text-red-400",
    skip: "bg-gray-800 border-gray-700 text-gray-600",
    pending: "bg-gray-900 border-gray-700 text-gray-600",
  };
  const dot: Record<StageState, string> = {
    done: "✓", running: "◌", failed: "✗", skip: "—", pending: "·",
  };
  return (
    <div className={`border rounded px-2 py-0.5 text-[10px] font-mono flex items-center gap-1 ${styles[state]}`}>
      <span>{dot[state]}</span>
      <span>{label}</span>
    </div>
  );
}

function ConceptRow({ m }: { m: ConceptMetrics }) {
  const passBadge = m.passes === null
    ? null
    : m.passes
      ? <span className="text-[10px] font-mono bg-green-500/15 border border-green-500/40 text-green-400 rounded px-1.5 py-0.5">PASS</span>
      : <span className="text-[10px] font-mono bg-red-500/15 border border-red-500/40 text-red-400 rounded px-1.5 py-0.5">FAIL</span>;

  return (
    <div className="grid grid-cols-[1.5rem_1fr_auto_auto_auto_auto] items-center gap-4 py-3 border-b border-gray-800/60 last:border-0">
      <div className="text-gray-600 text-xs font-mono text-right">{m.index + 1}</div>
      <div>
        <div className="text-sm text-white truncate">{m.name}</div>
        <div className="text-[10px] text-gray-600 mt-0.5 font-mono">{m.visual_type}</div>
      </div>
      <div className="flex gap-1 flex-wrap justify-end">
        {m.stages.map((s) => <StagePip key={s.label} {...s} />)}
      </div>
      <div className="min-w-[80px]">
        {m.score !== null ? <ScoreBar score={m.score} /> : <span className="text-xs text-gray-700">—</span>}
      </div>
      <div className="w-16 text-right text-[10px] font-mono text-gray-500">
        {m.duration_ms !== null ? fmtDuration(m.duration_ms) : "—"}
      </div>
      <div className="w-12 text-right">
        {passBadge ?? <span className="text-gray-700 text-xs">—</span>}
      </div>
    </div>
  );
}

export function ActivityFeed({ progress, error }: { progress: string[]; error?: string | null }) {
  // Show last 20 messages, most-recent at top
  const items = [...progress].reverse().slice(0, 20);
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-gray-800 text-xs font-semibold text-gray-400 uppercase tracking-wide">
        Activity
      </div>
      {error && (
        <div className="px-4 py-2 bg-red-950 border-b border-red-800 text-xs text-red-300 font-mono">
          {error}
        </div>
      )}
      <div className="divide-y divide-gray-800/50 max-h-64 overflow-y-auto">
        {items.length === 0 ? (
          <div className="px-4 py-3 text-xs text-gray-700">No activity yet</div>
        ) : items.map((msg, i) => {
          const isError = msg.toLowerCase().includes("fail") || msg.toLowerCase().includes("error");
          const isSuccess = msg.toLowerCase().includes("pass") || msg.toLowerCase().includes("complete") || msg.toLowerCase().includes("done");
          const color = isError ? "text-red-400" : isSuccess ? "text-green-400" : "text-gray-400";
          return (
            <div key={i} className="px-4 py-1.5 flex items-start gap-2">
              <span className="text-gray-700 text-[10px] font-mono mt-0.5 shrink-0">{progress.length - i}</span>
              <span className={`text-xs font-mono ${color}`}>{msg}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function PipelineStageTracker({ job }: { job: JobState }) {
  const progress = job.progress;
  const hasParsed = progress.some((m) => m.startsWith("Parsed"));
  const hasFigures = progress.some((m) => m.startsWith("Extracted"));
  const foundMsg = progress.find((m) => m.startsWith("Found"));
  const hasConcepts = !!foundMsg;
  // Parse total from "Found N concepts" so it's stable even before animations complete
  const conceptsFoundCount = foundMsg ? (foundMsg.match(/Found (\d+)/) ?? [])[1] : null;
  const isDone = job.status === "done";
  const maxConcepts = job.options.max_concepts as number;

  const globalStages: Array<{ label: string; state: StageState; sub?: string }> = [
    { label: "Parse PDF", state: hasParsed ? "done" : (job.status === "running" ? "running" : "pending") },
    ...(job.options.figure_context ? [{
      label: "Extract Figures",
      state: (hasFigures ? "done" : (hasParsed ? "running" : "pending")) as StageState,
    }] : []),
    {
      label: "Find Concepts",
      state: hasConcepts ? "done" : (hasParsed ? "running" : "pending"),
      sub: conceptsFoundCount ? `${conceptsFoundCount} found` : undefined,
    },
    {
      label: "Animate",
      state: isDone ? "done" : (hasConcepts ? "running" : "pending"),
      sub: hasConcepts ? `${job.concepts.length}/${maxConcepts} done` : undefined,
    },
  ];

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Pipeline Stages</div>
      <div className="flex items-center gap-2 flex-wrap">
        {globalStages.map((s, i) => (
          <div key={s.label} className="flex items-center gap-2">
            <div className="flex flex-col items-center gap-0.5">
              <StagePip label={s.label} state={s.state} />
              {s.sub && <span className="text-[9px] text-gray-600 font-mono">{s.sub}</span>}
            </div>
            {i < globalStages.length - 1 && (
              <span className="text-gray-700 text-xs">→</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Exported stats-only strip (used by the unified job page) ─────────────────

export function DashboardStats({ job }: { job: JobState }) {
  const metrics = job.concepts.map((c) => buildConceptMetrics(c, job.progress));
  const scores = metrics.map((m) => m.score).filter((s): s is number => s !== null);
  const avgScore = scores.length > 0
    ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1) : "—";
  const passCount = metrics.filter((m) => m.passes === true).length;
  const gradedCount = metrics.filter((m) => m.passes !== null).length;
  const passRate = gradedCount > 0 ? `${Math.round((passCount / gradedCount) * 100)}%` : "—";
  const totalRenderRetries = metrics.reduce((sum, m) => sum + Math.max(0, m.renderAttempts - 1), 0);
  const totalMs = job.completed_at
    ? new Date(job.completed_at).getTime() - new Date(job.created_at).getTime() : null;
  const totalCost = metrics.reduce(
    (sum, m) => sum + estConceptCost(m.renderAttempts, m.visualDiffRuns, m.hasVideo, m.passes), 0
  );
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <StatCard
        label="Avg Score" value={avgScore === "—" ? "—" : `${avgScore}/10`}
        sub={scores.length > 0 ? `${scores.length} graded` : "pending"}
        color={scores.length > 0 ? (parseFloat(avgScore) >= 7 ? "text-green-400" : parseFloat(avgScore) >= 5 ? "text-yellow-400" : "text-red-400") : "text-gray-600"}
      />
      <StatCard
        label="Pass Rate" value={passRate}
        sub={gradedCount > 0 ? `${passCount}/${gradedCount} passed` : "pending"}
        color={gradedCount > 0 ? (passCount === gradedCount ? "text-green-400" : passCount > 0 ? "text-yellow-400" : "text-red-400") : "text-gray-600"}
      />
      <StatCard
        label="Concepts" value={`${job.concepts.length}/${job.options.max_concepts as number}`}
        sub={job.status === "running" ? "in progress" : job.status === "done" ? "complete" : ""}
        color={job.status === "done" ? "text-green-400" : "text-blue-400"}
      />
      <StatCard
        label="Retries" value={String(totalRenderRetries)}
        sub={totalRenderRetries > 0 ? "render fixes" : "clean renders"}
        color={totalRenderRetries > 0 ? "text-yellow-400" : "text-gray-400"}
      />
      <StatCard
        label="Total Time" value={totalMs !== null ? fmtDuration(totalMs) : "—"}
        sub={totalMs !== null ? "wall clock" : job.status === "running" ? "in progress" : "pending"}
        color={totalMs !== null ? "text-purple-400" : "text-gray-600"}
      />
      <StatCard
        label="Est. Cost" value={metrics.length > 0 ? `$${totalCost.toFixed(3)}` : "—"}
        sub={metrics.length > 0 ? "GPT-4o" : "pending"}
        color={metrics.length > 0 ? "text-orange-400" : "text-gray-600"}
      />
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────

export default function Dashboard({ job }: { job: JobState }) {
  const metrics = job.concepts.map((c) => buildConceptMetrics(c, job.progress));

  const scores = metrics.map((m) => m.score).filter((s): s is number => s !== null);
  const avgScore = scores.length > 0
    ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1)
    : "—";

  const passCount = metrics.filter((m) => m.passes === true).length;
  const gradedCount = metrics.filter((m) => m.passes !== null).length;
  const passRate = gradedCount > 0 ? `${Math.round((passCount / gradedCount) * 100)}%` : "—";

  const totalVdRuns = metrics.reduce((sum, m) => sum + m.visualDiffRuns, 0);
  const totalRenderRetries = metrics.reduce((sum, m) => sum + Math.max(0, m.renderAttempts - 1), 0);

  const totalMs = job.completed_at
    ? new Date(job.completed_at).getTime() - new Date(job.created_at).getTime()
    : null;

  const totalCost = metrics.reduce((sum, m) => sum + estConceptCost(m.renderAttempts, m.visualDiffRuns, m.hasVideo, m.passes), 0);

  const statusColors: Record<string, string> = {
    queued: "text-yellow-400",
    running: "text-blue-400",
    done: "text-green-400",
    failed: "text-red-400",
    cancelled: "text-gray-400",
  };

  return (
    <div className="space-y-4">
      {/* Status row */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`text-sm font-mono font-bold uppercase ${statusColors[job.status]}`}>
          {job.status === "running" && <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full mr-1.5 animate-pulse align-middle" />}
          {job.status}
        </span>
        <span className="text-gray-600 text-xs">·</span>
        <span className="text-xs text-gray-500 font-mono">{job.job_id}</span>
        <span className="text-gray-600 text-xs">·</span>
        <span className="text-xs text-gray-500">{new Date(job.created_at).toLocaleString()}</span>
        <div className="flex gap-2 ml-auto flex-wrap">
          {[
            `${job.options.max_concepts} concepts`,
            job.options.quality as string,
            job.options.figure_context ? "figure mode" : "text mode",
            (job.options.parallel_concepts as number) > 1 ? `${job.options.parallel_concepts}× parallel` : null,
          ].filter(Boolean).map((chip) => (
            <span key={chip as string} className="text-[10px] font-mono bg-gray-800 text-gray-500 border border-gray-700 rounded px-2 py-0.5">
              {chip as string}
            </span>
          ))}
        </div>
      </div>

      {/* Metrics cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard
          label="Avg Critic Score"
          value={avgScore === "—" ? "—" : `${avgScore}/10`}
          sub={scores.length > 0 ? `${scores.length} graded` : "pending"}
          color={scores.length > 0 ? (parseFloat(avgScore) >= 7 ? "text-green-400" : parseFloat(avgScore) >= 5 ? "text-yellow-400" : "text-red-400") : "text-gray-600"}
        />
        <StatCard
          label="Pass Rate"
          value={passRate}
          sub={gradedCount > 0 ? `${passCount} of ${gradedCount} passed` : "pending"}
          color={gradedCount > 0 ? (passCount === gradedCount ? "text-green-400" : passCount > 0 ? "text-yellow-400" : "text-red-400") : "text-gray-600"}
        />
        <StatCard
          label="Visual Diff Runs"
          value={String(totalVdRuns)}
          sub={totalVdRuns > 0 ? `${metrics.filter((m) => m.visualDiffImproved).length} improved` : "no runs yet"}
          color={totalVdRuns > 0 ? "text-blue-400" : "text-gray-600"}
        />
        <StatCard
          label="Render Retries"
          value={String(totalRenderRetries)}
          sub={totalRenderRetries > 0 ? "syntax errors fixed" : "clean renders"}
          color={totalRenderRetries > 0 ? "text-yellow-400" : "text-gray-400"}
        />
        <StatCard
          label="Total Time"
          value={totalMs !== null ? fmtDuration(totalMs) : "—"}
          sub={totalMs !== null ? "wall clock" : job.status === "running" ? "in progress" : "pending"}
          color={totalMs !== null ? "text-purple-400" : "text-gray-600"}
        />
        <StatCard
          label="Est. GPT-4o Cost"
          value={metrics.length > 0 ? `$${totalCost.toFixed(3)}` : "—"}
          sub={metrics.length > 0 ? `${metrics.length} concepts` : "pending"}
          color={metrics.length > 0 ? "text-orange-400" : "text-gray-600"}
        />
      </div>

      {/* Global pipeline tracker */}
      <PipelineStageTracker job={job} />

      {/* Per-concept scorecard */}
      {metrics.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-800 flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Concepts</span>
            <span className="text-[10px] font-mono text-gray-600">stage pipeline · critic score · duration · pass/fail</span>
          </div>
          <div className="px-4 divide-y-0">
            {metrics
              .sort((a, b) => a.index - b.index)
              .map((m) => <ConceptRow key={m.index} m={m} />)}
          </div>
        </div>
      )}

      {/* Activity feed */}
      <ActivityFeed progress={job.progress} />
    </div>
  );
}
