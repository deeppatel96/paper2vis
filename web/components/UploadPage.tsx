"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth, UserButton } from "@clerk/nextjs";
import FileUpload from "@/components/FileUpload";
import { submitJob, getUsage, UsageInfo } from "@/lib/api";

type PickerOption = { value: string; label: string; description: string; disabled?: boolean };

function OptionPicker({ value, onChange, options }: {
  value: string;
  onChange: (v: string) => void;
  options: PickerOption[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = options.find(o => o.value === value) ?? options[0];

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={ref} className="relative flex-1">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between bg-gray-800 border border-gray-600 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <span>{selected.label}</span>
        <svg className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[260px] bg-gray-800 border border-gray-600 rounded-lg shadow-xl overflow-hidden">
          {options.map(opt => (
            <button
              key={opt.value}
              type="button"
              disabled={opt.disabled}
              onClick={() => { onChange(opt.value); setOpen(false); }}
              className={`w-full text-left px-3 py-2.5 transition-colors
                ${opt.disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}
                ${opt.value === value ? "bg-blue-600/30 text-blue-300" : "hover:bg-gray-700 text-white"}`}
            >
              <div className="text-sm font-medium">{opt.label}</div>
              <div className="text-xs text-gray-400 mt-0.5">{opt.description}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const TIER_LIMITS = {
  mini: { maxConcepts: 3, qualityLimit: "low_quality", maxRetries: 5 },
  pro:  { maxConcepts: 16, qualityLimit: "high_quality", maxRetries: 10 },
};

export default function UploadPage() {
  const router = useRouter();
  const { getToken } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [maxConcepts, setMaxConcepts] = useState(3);
  const [quality, setQuality] = useState("low_quality");
  const [figureContext, setFigureContext] = useState(false);
  const [parallelConcepts, setParallelConcepts] = useState(4);
  const [maxRetries, setMaxRetries] = useState(5);
  const [voice, setVoice] = useState(true);
  const [generationMode, setGenerationMode] = useState("two_pass");
  const [conceptSelection, setConceptSelection] = useState(false);
  const [useRag, setUseRag] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<UsageInfo | null>(null);

  useEffect(() => {
    getToken().then((token) => getUsage(token)).then((u) => {
      setUsage(u);
      const limits = TIER_LIMITS[u.tier] ?? TIER_LIMITS.mini;
      setMaxConcepts(Math.min(maxConcepts, limits.maxConcepts));
      setMaxRetries(r => Math.min(r, limits.maxRetries));
      if (u.tier === "mini") setQuality("low_quality");
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tierLimits = usage ? (TIER_LIMITS[usage.tier] ?? TIER_LIMITS.mini) : TIER_LIMITS.mini;
  const atLimit = usage ? usage.jobs_used >= usage.jobs_limit : false;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const job = await submitJob(file, { maxConcepts, quality, figureContext, parallelConcepts, maxRetries, voice, generationMode, conceptSelection, useRag }, token);
      router.push(`/jobs/${job.job_id}`);
    } catch (err) {
      setError(String(err));
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center p-8">
      <div className="w-full max-w-lg space-y-6">
        {/* Header with user info */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <h1 className="text-3xl font-bold tracking-tight">New job</h1>
            <p className="text-gray-400 text-sm">Upload a paper PDF to generate animations</p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <UserButton />
            {usage && (
              <div className="text-right">
                <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${usage.tier === "pro" ? "bg-purple-900 text-purple-300" : "bg-gray-800 text-gray-400"}`}>
                  {usage.tier.toUpperCase()}
                </span>
                <p className="text-xs text-gray-500 mt-0.5">
                  {usage.jobs_used}/{usage.jobs_limit} jobs this month
                </p>
              </div>
            )}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <FileUpload onFile={setFile} />

          {file && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800 text-sm">
              <svg className="w-4 h-4 text-red-400 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
              </svg>
              <span className="text-gray-200 truncate">{file.name}</span>
              <span className="text-gray-500 shrink-0 text-xs ml-auto">
                {(file.size / 1024).toFixed(0)} KB
              </span>
            </div>
          )}

          <div className="space-y-3 rounded-xl bg-gray-900 border border-gray-700 p-4">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Options</p>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Concepts</label>
              <input type="range" min={1} max={tierLimits.maxConcepts} value={maxConcepts}
                onChange={(e) => { const v = Number(e.target.value); setMaxConcepts(v); setParallelConcepts(p => Math.min(p, v)); }}
                className="flex-1 accent-blue-500" />
              <span className="text-sm text-white w-6 text-right">{maxConcepts}</span>
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Video quality</label>
              <OptionPicker
                value={quality}
                onChange={setQuality}
                options={[
                  { value: "low_quality",    label: "Low (480p)",    description: "Fastest renders — great for exploring a new paper before committing to a full run." },
                  { value: "medium_quality", label: "Medium (720p)", description: "Best balance of speed and clarity. Recommended for most papers.", disabled: tierLimits.qualityLimit === "low_quality" },
                  { value: "high_quality",   label: "High (1080p)",  description: "Sharpest output — ideal for presentations or sharing. Takes 2–3× longer to render.", disabled: tierLimits.qualityLimit !== "high_quality" },
                ]}
              />
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Parallel concepts</label>
              <input type="range" min={1} max={maxConcepts} value={parallelConcepts}
                onChange={(e) => setParallelConcepts(Number(e.target.value))}
                className="flex-1 accent-blue-500" />
              <span className="text-sm text-white w-4 text-right">{parallelConcepts}</span>
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Render retries</label>
              <input type="range" min={1} max={tierLimits.maxRetries} value={maxRetries}
                onChange={(e) => setMaxRetries(Number(e.target.value))}
                className="flex-1 accent-blue-500" />
              <span className="text-sm text-white w-4 text-right">{maxRetries}</span>
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Generation mode</label>
              <OptionPicker
                value={generationMode}
                onChange={setGenerationMode}
                options={[
                  { value: "two_pass", label: "Two-pass",    description: "Plans a visual storyboard first, then writes animation code from it. Best quality — recommended for most papers." },
                  { value: "dsl",      label: "Typed DSL",   description: "Generates a structured spec that's validated before rendering. Fewer crashes, more predictable output." },
                  { value: "direct",   label: "Direct",      description: "Writes animation code in a single pass with no planning step. Fastest but most variable quality." },
                  { value: "all",      label: "Compare all", description: "Runs all three modes in parallel and keeps the best result. Slowest but highest chance of a great animation." },
                ]}
              />
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Animate figures</label>
              <button type="button" onClick={() => setFigureContext(!figureContext)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors
                  ${figureContext ? "bg-blue-500" : "bg-gray-600"}`}>
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                  ${figureContext ? "translate-x-6" : "translate-x-1"}`} />
              </button>
              <span className="text-xs text-gray-500">
                {figureContext ? "Extract + animate paper figures" : "Generate from scratch"}
              </span>
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Voice narration</label>
              <button type="button" onClick={() => setVoice(!voice)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors
                  ${voice ? "bg-blue-500" : "bg-gray-600"}`}>
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                  ${voice ? "translate-x-6" : "translate-x-1"}`} />
              </button>
              <span className="text-xs text-gray-500">
                {voice ? "AI voiceover + subtitles" : "Silent animation"}
              </span>
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Pick concepts</label>
              <button type="button" onClick={() => setConceptSelection(!conceptSelection)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors
                  ${conceptSelection ? "bg-blue-500" : "bg-gray-600"}`}>
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                  ${conceptSelection ? "translate-x-6" : "translate-x-1"}`} />
              </button>
              <span className="text-xs text-gray-500">
                {conceptSelection ? "Choose which concepts to animate" : "Animate all extracted concepts"}
              </span>
            </div>

            <div className="flex items-center gap-4">
              <label className="text-sm text-gray-300 w-36 shrink-0">Style examples</label>
              <button type="button" onClick={() => setUseRag(!useRag)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors
                  ${useRag ? "bg-blue-500" : "bg-gray-600"}`}>
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                  ${useRag ? "translate-x-6" : "translate-x-1"}`} />
              </button>
              <span className="text-xs text-gray-500">
                {useRag ? "Inject 3b1b-style reference examples" : "No style examples (plain codegen)"}
              </span>
            </div>
          </div>

          {error && (
            <div className="rounded-lg bg-red-950 border border-red-800 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          {atLimit && (
            <div className="rounded-lg bg-yellow-950 border border-yellow-800 px-3 py-2 text-sm text-yellow-300">
              Monthly limit reached ({usage?.jobs_used}/{usage?.jobs_limit} jobs). Contact the admin to upgrade to Pro.
            </div>
          )}

          <button type="submit" disabled={!file || loading || atLimit}
            className="w-full py-3 rounded-xl font-semibold text-sm transition-colors
              bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed">
            {loading ? "Starting…" : "Generate Animations"}
          </button>
        </form>
      </div>
    </main>
  );
}
