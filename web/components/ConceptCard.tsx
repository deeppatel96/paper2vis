"use client";
import { useState, useRef, useEffect } from "react";
import { ConceptResult, VideoHistoryEntry, fileUrl } from "@/lib/api";

interface Props {
  concept: ConceptResult;
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

export function ConceptSkeleton({ name, visual_type }: { name: string; visual_type: string }) {
  return (
    <div className="rounded-xl bg-gray-900 border border-gray-700 overflow-hidden opacity-80">
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-white text-sm truncate">{name}</h3>
            <span className="text-[10px] font-mono bg-blue-500/20 border border-blue-500/40 text-blue-300 rounded px-1.5 py-0.5 animate-pulse shrink-0">
              generating…
            </span>
          </div>
          <span className="text-xs text-gray-400 capitalize">{visual_type.replace("_", " ")}</span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-0 divide-x divide-gray-700">
        <div className="p-3 flex flex-col gap-2">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Paper Figure</p>
          <div className="rounded bg-gray-800 h-40 animate-pulse" />
        </div>
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

export default function ConceptCard({ concept }: Props) {
  const [showStoryboard, setShowStoryboard] = useState(false);
  const [showCritique, setShowCritique] = useState(false);

  const isRegenerating = concept.regen_status === "running";
  const hasStoryboardNoVideo = !concept.video_url && !!concept.storyboard && !isRegenerating;

  return (
    <div id={`concept-${concept.index}`} className="rounded-xl bg-gray-900 border border-gray-700 overflow-hidden transition-shadow duration-500">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between gap-2">
        <div className="min-w-0">
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
          <span className="text-xs text-gray-400 capitalize">
            {concept.visual_type.replace(/_/g, " ")}
            {concept.figure_index !== null && concept.figure_index !== undefined && (
              <span className="ml-2 text-gray-600 font-mono">fig {concept.figure_index}</span>
            )}
          </span>
        </div>
        <div className="flex gap-2 shrink-0">
          {concept.storyboard && (
            <button onClick={() => setShowStoryboard(!showStoryboard)}
              className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors">
              {showStoryboard ? "Hide" : "Storyboard"}
            </button>
          )}
          {concept.critique_md && (
            <button onClick={() => setShowCritique(!showCritique)}
              className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors">
              {showCritique ? "Hide" : "Critique"}
            </button>
          )}
        </div>
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

      {/* Storyboard */}
      {showStoryboard && concept.storyboard && (
        <div className="border-t border-gray-700 px-4 py-3">
          <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-5 max-h-64 overflow-y-auto">
            {concept.storyboard}
          </pre>
        </div>
      )}

      {/* Critique */}
      {showCritique && concept.critique_md && (
        <div className="border-t border-gray-700 px-4 py-3">
          <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-5 max-h-48 overflow-y-auto">
            {concept.critique_md}
          </pre>
        </div>
      )}
    </div>
  );
}
