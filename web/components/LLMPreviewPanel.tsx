"use client";
import { useState } from "react";

type Stage = "storyboard" | "code" | "critique";

const STAGES: { key: Stage; label: string; color: string }[] = [
  { key: "storyboard", label: "Storyboard", color: "text-purple-300 border-purple-600 bg-purple-600/20" },
  { key: "code",       label: "Code",       color: "text-blue-300 border-blue-600 bg-blue-600/20" },
  { key: "critique",   label: "Critique",   color: "text-yellow-300 border-yellow-600 bg-yellow-600/20" },
];

const INACTIVE = "text-gray-500 border-gray-700 bg-gray-800 hover:text-gray-300";

function OutputBox({ content, stage }: { content: string; stage: Stage }) {
  const [expanded, setExpanded] = useState(false);
  const lines = content.split("\n");
  const LIMIT = 20;
  const isLong = lines.length > LIMIT;
  const shown = expanded || !isLong ? content : lines.slice(0, LIMIT).join("\n");

  return (
    <div>
      <pre
        className={`text-[11px] font-mono text-gray-300 bg-gray-950 border border-gray-800 rounded-lg p-3
          overflow-x-auto whitespace-pre-wrap leading-relaxed
          ${isLong && !expanded ? "max-h-56 overflow-y-hidden" : ""}`}
      >
        {shown}
        {isLong && !expanded && (
          <span className="text-gray-600"> …</span>
        )}
      </pre>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded(e => !e)}
          className="text-[10px] text-blue-400 hover:text-blue-300 mt-1 font-mono transition-colors"
        >
          {expanded ? "▲ Show less" : `▼ Show all (${lines.length} lines)`}
        </button>
      )}
    </div>
  );
}

export default function LLMPreviewPanel({
  outputs,
  stubs,
}: {
  outputs: Map<string, string>;
  stubs: Array<{ index: number; name: string; visual_type: string }>;
}) {
  const [open, setOpen] = useState(true);
  const [activeTabs, setActiveTabs] = useState<Record<number, Stage>>({});

  const conceptsWithOutputs = stubs.filter((s) =>
    STAGES.some(({ key }) => outputs.has(`${s.index}:${key}`))
  );

  if (conceptsWithOutputs.length === 0) return null;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 border-b border-gray-800 hover:bg-gray-800/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">LLM Outputs</span>
          <span className="text-[10px] font-mono text-gray-600">live preview</span>
        </div>
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="divide-y divide-gray-800">
          {conceptsWithOutputs.map((stub) => {
            const available = STAGES.filter(({ key }) => outputs.has(`${stub.index}:${key}`));
            const activeKey: Stage = activeTabs[stub.index] ?? available[0]?.key ?? "storyboard";
            const content = outputs.get(`${stub.index}:${activeKey}`) ?? "";

            return (
              <div key={stub.index} className="p-4 space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-mono text-gray-600">#{stub.index + 1}</span>
                  <span className="text-sm font-medium text-white">{stub.name}</span>
                  <span className="text-[10px] text-gray-600 font-mono capitalize">{stub.visual_type.replace(/_/g, " ")}</span>
                  <div className="flex gap-1 ml-auto">
                    {available.map(({ key, label, color }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setActiveTabs((prev) => ({ ...prev, [stub.index]: key }))}
                        className={`text-[10px] px-2 py-0.5 rounded font-mono border transition-colors
                          ${activeKey === key ? color : INACTIVE}`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <OutputBox content={content} stage={activeKey} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
