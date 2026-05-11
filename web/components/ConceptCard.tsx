"use client";
import { useState, useRef, useEffect } from "react";
import { ConceptResult, VideoHistoryEntry, fileUrl } from "@/lib/api";
import type { ConceptStageInfo } from "@/app/jobs/[id]/page";

const STAGES = ["codegen", "validate", "render", "critic", "narration"] as const;
type StageName = typeof STAGES[number];

const STAGE_LABELS: Record<StageName, string> = {
  codegen: "Codegen", validate: "Validate", render: "Render", critic: "Critic", narration: "Narrate",
};

function ConceptPipelineTracker({ stageInfo }: { stageInfo?: ConceptStageInfo }) {
  if (!stageInfo) return null;

  const currentIdx = STAGES.indexOf(stageInfo.stage as StageName);

  return (
    <div className="flex items-center gap-0 text-[10px] font-mono select-none overflow-x-auto">
      {STAGES.map((s, i) => {
        const isCurrent = s === stageInfo.stage;
        const isPast = currentIdx > i || stageInfo.stage === "done";
        const isFailed = isCurrent && stageInfo.status === "error";
        const isRunning = isCurrent && stageInfo.status === "running";

        let dotClass = "w-1.5 h-1.5 rounded-full border shrink-0 ";
        let labelClass = "px-1 ";
        if (isFailed) {
          dotClass += "bg-red-500 border-red-500";
          labelClass += "text-red-400";
        } else if (isRunning) {
          dotClass += "bg-blue-400 border-blue-400 animate-pulse";
          labelClass += "text-blue-400";
        } else if (isPast) {
          dotClass += "bg-green-500 border-green-500";
          labelClass += "text-gray-500";
        } else {
          dotClass += "border-gray-700";
          labelClass += "text-gray-700";
        }

        const label = isCurrent && stageInfo.status === "running" && stageInfo.attempt
          ? `${STAGE_LABELS[s]} ${stageInfo.attempt}/${stageInfo.maxAttempts ?? "?"}`
          : isCurrent && stageInfo.status === "done" && stageInfo.score != null
          ? `${STAGE_LABELS[s]} ${stageInfo.score}/10`
          : STAGE_LABELS[s];

        return (
          <div key={s} className="flex items-center gap-0 shrink-0">
            {i > 0 && <span className="text-gray-800 px-0.5">—</span>}
            <div className="flex items-center gap-1">
              <span className={dotClass} />
              <span className={labelClass} title={isFailed ? stageInfo.detail : undefined}>
                {label}
                {isFailed && " ✗"}
              </span>
            </div>
          </div>
        );
      })}
      {stageInfo.status === "error" && stageInfo.detail && (
        <span className="ml-2 text-red-400/70 truncate max-w-48" title={stageInfo.detail}>
          {stageInfo.detail}
        </span>
      )}
    </div>
  );
}

interface ModeOutputs {
  storyboard?: string | null;
  code?: string | null;
  critique?: string | null;
  logs?: string[];
}

interface Props {
  concept: ConceptResult;
  stageInfo?: ConceptStageInfo;
  // Per-mode live data. Key is mode key ("two_pass", "direct", etc.)
  modeData?: Record<string, ModeOutputs>;
  activeModes?: string[];
}

const MODE_LABELS: Record<string, string> = {
  two_pass: "Two-pass", dsl: "Typed DSL", direct: "Direct", lean: "Lean/Mathlib", default: "Output",
};

const CONTENT_TABS = [
  { key: "storyboard", label: "Storyboard", active: "text-purple-300 border-purple-500 bg-purple-500/20", text: "text-purple-300", dot: "bg-purple-400" },
  { key: "code",       label: "Code",       active: "text-blue-300 border-blue-500 bg-blue-500/20",       text: "text-blue-300",   dot: "bg-blue-400" },
  { key: "critique",   label: "Critique",   active: "text-yellow-300 border-yellow-500 bg-yellow-500/20", text: "text-yellow-300", dot: "bg-yellow-400" },
  { key: "logs",       label: "Logs",       active: "text-gray-300 border-gray-500 bg-gray-700/50",       text: "text-gray-400",   dot: "bg-gray-400" },
] as const;
type ContentTabKey = typeof CONTENT_TABS[number]["key"];

function ContentPane({ data, isLive }: { data: ModeOutputs; isLive?: boolean }) {
  const logsText = data.logs && data.logs.length > 0 ? data.logs.join("\n") : null;
  const contents: Record<ContentTabKey, string | null | undefined> = {
    storyboard: data.storyboard,
    code: data.code,
    critique: data.critique,
    logs: logsText,
  };
  const available = CONTENT_TABS.filter((t) => contents[t.key]);
  const [active, setActive] = useState<ContentTabKey | null>(null);

  if (available.length === 0) return null;

  const activeKey: ContentTabKey = active && contents[active] ? active : available[0].key;
  const content = contents[activeKey] ?? "";
  const tabDef = CONTENT_TABS.find((t) => t.key === activeKey)!;

  return (
    <>
      <div className="flex items-center gap-1 px-3 pt-1.5 pb-1 flex-wrap">
        {available.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActive(t.key)}
            className={`text-[10px] px-2 py-0.5 rounded font-mono border transition-colors ${
              activeKey === t.key ? t.active : "text-gray-600 border-gray-700 bg-gray-800 hover:text-gray-300"
            }`}
          >
            {t.label}
            {isLive && activeKey === t.key && t.key !== "logs" && (
              <span className={`inline-block w-1 h-1 rounded-full ml-1 animate-pulse ${t.dot}`} />
            )}
          </button>
        ))}
        {isLive && (
          <span className="ml-auto text-[9px] font-mono text-gray-600 animate-pulse">live</span>
        )}
      </div>
      <pre className={`mx-3 mb-3 text-[11px] font-mono whitespace-pre-wrap leading-relaxed rounded border border-gray-800 bg-gray-950 px-3 py-2 max-h-64 overflow-y-auto ${tabDef.text}`}>
        {content}
      </pre>
    </>
  );
}

function LLMOutputTabs({
  modeData, activeModes, concept, isLive,
}: {
  modeData?: Record<string, ModeOutputs>;
  activeModes?: string[];
  concept: ConceptResult;
  isLive?: boolean;
}) {
  // Build effective data: live modeData takes priority, fallback to concept fields for finished jobs
  const modes: string[] = activeModes && activeModes.length > 0 ? activeModes : [];
  const effectiveData: Record<string, ModeOutputs> = { ...modeData };

  // For finished jobs with no live data, synthesize a "default" entry from concept fields
  if (modes.length === 0) {
    const fallback: ModeOutputs = {
      storyboard: concept.storyboard,
      code: undefined,
      critique: concept.critique_md,
      logs: [],
    };
    if (fallback.storyboard || fallback.critique) {
      effectiveData["default"] = fallback;
      modes.push("default");
    }
  }

  const [activeMode, setActiveMode] = useState<string | null>(null);

  if (modes.length === 0) return null;

  const currentMode = activeMode && modes.includes(activeMode) ? activeMode : modes[0];
  const currentData = effectiveData[currentMode] ?? {};
  const showModeTabs = modes.length > 1;

  return (
    <div className="border-t border-gray-700">
      {showModeTabs && (
        <div className="flex items-center gap-1 px-3 pt-2 pb-1 border-b border-gray-800 flex-wrap">
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setActiveMode(m)}
              className={`text-[10px] px-2.5 py-1 rounded-md font-mono font-medium border transition-colors ${
                currentMode === m
                  ? "text-white border-gray-500 bg-gray-700"
                  : "text-gray-500 border-gray-700 bg-gray-800/50 hover:text-gray-300"
              }`}
            >
              {MODE_LABELS[m] ?? m}
            </button>
          ))}
        </div>
      )}
      <ContentPane data={currentData} isLive={isLive && currentMode === modes[modes.length - 1]} />
    </div>
  );
}

function HistoryTimeline({ history, currentVideoUrl, subtitleUrl }: {
  history: VideoHistoryEntry[];
  currentVideoUrl: string | null;
  subtitleUrl: string | null;
}) {
  const entries: VideoHistoryEntry[] = history.length > 0
    ? history
    : currentVideoUrl
      ? [{ label: "Animation", video_url: currentVideoUrl, trigger: null, critic_score: null }]
      : [];

  const [active, setActive] = useState(entries.length - 1);
  const videoRef = useRef<HTMLVideoElement>(null);

  const isComparison = entries.some(e => e.mode);

  const idx = Math.min(active, entries.length - 1);
  const shown = entries[idx];
  const isFinal = idx === entries.length - 1;

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = false;
    v.volume = 1;
  }, [shown?.video_url]);

  if (entries.length === 0) return null;

  if (isComparison) {
    const cols = entries.length <= 2 ? "grid-cols-2" : entries.length === 3 ? "grid-cols-3" : "grid-cols-2";
    return (
      <div className={`grid ${cols} gap-2`}>
        {entries.map((entry, i) => {
          const modeLabel = entry.mode ? (MODE_LABELS[entry.mode] ?? entry.mode) : entry.label;
          const isRunning = !entry.video_url && !entry.failed;
          return (
            <div key={i} className="flex flex-col gap-1">
              <p className={`text-[10px] font-mono font-semibold truncate ${
                entry.failed ? "text-red-400" : isRunning ? "text-yellow-400" : "text-blue-300/80"
              }`}>
                {entry.failed ? "✗ " : isRunning ? "⟳ " : ""}{modeLabel}
              </p>
              {entry.failed ? (
                <div className="rounded bg-red-950/40 border border-red-800/40 flex items-center justify-center min-h-24 p-2">
                  <span className="text-xs text-red-400 text-center leading-snug" title={entry.trigger ?? undefined}>
                    {entry.trigger ?? "Render failed"}
                  </span>
                </div>
              ) : isRunning ? (
                <div className="rounded bg-yellow-950/40 border border-yellow-800/40 flex items-center justify-center min-h-24 animate-pulse">
                  <span className="text-xs text-yellow-500">Rendering…</span>
                </div>
              ) : (
                <video
                  src={fileUrl(entry.video_url)}
                  controls
                  preload="metadata"
                  className="rounded w-full bg-black"
                >
                  Your browser does not support video.
                </video>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Video player */}
      <video
        ref={videoRef}
        key={shown.video_url}
        src={fileUrl(shown.video_url)}
        controls
        preload="metadata"
        className="rounded w-full max-h-56 bg-black"
      >
        {subtitleUrl && isFinal && (
          <track kind="subtitles" src={fileUrl(subtitleUrl)} srcLang="en" label="English" default />
        )}
        Your browser does not support video.
      </video>

      {/* Step timeline — only shown when multiple attempts */}
      {entries.length > 1 && (
        <div className="flex flex-col gap-0 text-[10px] font-mono select-none">
          {entries.map((entry, i) => {
            const isActive = i === idx;
            const isLast = i === entries.length - 1;
            const score = entry.critic_score;
            const scoreColor = score == null ? "" :
              score >= 8 ? "text-green-400" :
              score >= 6 ? "text-yellow-400" : "text-red-400";
            return (
              <div key={i}>
                {entry.trigger && (
                  <div className="flex items-start gap-1 px-1 py-0.5 ml-3">
                    <span className="text-gray-700 shrink-0 leading-tight">↳</span>
                    <span className="text-amber-600/80 leading-tight break-words min-w-0">
                      {entry.trigger}
                    </span>
                  </div>
                )}
                <button
                  onClick={() => setActive(i)}
                  className={`w-full text-left flex items-center gap-2 px-2 py-1 rounded transition-colors ${
                    isActive
                      ? "bg-blue-500/20 text-blue-300"
                      : "text-gray-500 hover:text-gray-300 hover:bg-gray-800/60"
                  }`}
                >
                  <span className={`w-4 h-4 rounded-full border flex items-center justify-center text-[8px] leading-none shrink-0 ${
                    isActive ? "border-blue-400 text-blue-400" : "border-gray-700 text-gray-600"
                  }`}>
                    {i + 1}
                  </span>
                  <span className="flex-1 truncate">{entry.label}</span>
                  {score != null && (
                    <span className={`shrink-0 ${scoreColor}`}>
                      {score}/10
                    </span>
                  )}
                  {isLast && <span className="text-green-500 shrink-0">★</span>}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ConceptSkeleton({ name, visual_type, hasFigures = false, stageInfo }: {
  name: string; visual_type: string; hasFigures?: boolean; stageInfo?: ConceptStageInfo;
}) {
  return (
    <div className="rounded-xl bg-gray-900 border border-gray-700 overflow-hidden opacity-80">
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between gap-2">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-white text-sm truncate">{name}</h3>
            <span className="text-[10px] font-mono bg-blue-500/20 border border-blue-500/40 text-blue-300 rounded px-1.5 py-0.5 animate-pulse shrink-0">
              generating…
            </span>
          </div>
          <span className="text-xs text-gray-400 capitalize">{visual_type.replace("_", " ")}</span>
          <ConceptPipelineTracker stageInfo={stageInfo} />
        </div>
      </div>
      <div className={`grid gap-0 divide-x divide-gray-700 ${hasFigures ? "grid-cols-2" : "grid-cols-1"}`}>
        {hasFigures && (
          <div className="p-3 flex flex-col gap-2">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Paper Figure</p>
            <div className="rounded bg-gray-800 h-40 animate-pulse" />
          </div>
        )}
        <div className="p-3 flex flex-col gap-2">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Animation</p>
          <div className="rounded bg-gray-800 flex items-center justify-center h-40">
            <span className="text-gray-600 text-xs animate-pulse">Rendering…</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ConceptCard({ concept, stageInfo, modeData, activeModes }: Props) {
  const isRegenerating = concept.regen_status === "running";
  const hasStoryboardNoVideo = !concept.video_url && !!concept.storyboard && !isRegenerating;

  const isLive = !!(activeModes && activeModes.length > 0 &&
    activeModes.some(m => modeData?.[m]?.storyboard || modeData?.[m]?.code || modeData?.[m]?.critique));

  return (
    <div id={`concept-${concept.index}`} className="rounded-xl bg-gray-900 border border-gray-700 overflow-hidden transition-shadow duration-500">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-semibold text-white text-sm truncate">{concept.name}</h3>
          {isRegenerating && (
            <span className="text-[10px] font-mono bg-blue-500/20 border border-blue-500/40 text-blue-300 rounded px-1.5 py-0.5 animate-pulse shrink-0">
              regenerating…
            </span>
          )}
          {concept.duration_ms != null && (
            <span className="text-[10px] font-mono text-gray-600 shrink-0">
              {(concept.duration_ms / 1000).toFixed(0)}s
            </span>
          )}
        </div>
        <ConceptPipelineTracker stageInfo={stageInfo} />
        <span className="text-xs text-gray-400 capitalize">
          {concept.visual_type.replace(/_/g, " ")}
          {concept.figure_index !== null && concept.figure_index !== undefined && (
            <span className="ml-2 text-gray-600 font-mono">fig {concept.figure_index}</span>
          )}
        </span>
      </div>

      {/* Figure + Animation */}
      <div className="grid grid-cols-2 gap-0 divide-x divide-gray-700">
        {/* Paper figure or description */}
        <div className="p-3 flex flex-col gap-2">
          {concept.figure_url ? (
            <>
              <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Paper Figure</p>
              <img src={fileUrl(concept.figure_url)} alt="Paper figure"
                className="rounded w-full object-contain max-h-64 bg-white" />
            </>
          ) : (
            <>
              <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Description</p>
              <p className="text-xs text-gray-300 leading-relaxed">
                {concept.description ?? "No description available."}
              </p>
            </>
          )}
        </div>

        {/* Animation with history timeline */}
        <div className="p-3 flex flex-col gap-2">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Animation</p>
          {(concept.history?.length > 0 || concept.video_url) ? (
            <HistoryTimeline history={concept.history ?? []} currentVideoUrl={concept.video_url} subtitleUrl={concept.subtitle_url} />
          ) : (
            <div className="rounded bg-gray-800 flex flex-col gap-2 min-h-40">
              <div className="flex items-center justify-center flex-1 p-4">
                <span className={`text-xs ${isRegenerating ? "text-gray-500 animate-pulse" : "text-gray-600"}`}>
                  {isRegenerating ? "Regenerating…" : "Render failed"}
                </span>
              </div>
              {hasStoryboardNoVideo && concept.storyboard && (
                <div className="border-t border-gray-700 px-3 py-2">
                  <p className="text-[10px] text-gray-600 font-semibold uppercase tracking-wide mb-1">Storyboard</p>
                  <pre className="text-[10px] text-gray-400 whitespace-pre-wrap font-mono leading-4 max-h-40 overflow-y-auto">
                    {concept.storyboard}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* LLM Output Tabs */}
      <LLMOutputTabs modeData={modeData} activeModes={activeModes} concept={concept} isLive={isLive} />
    </div>
  );
}
