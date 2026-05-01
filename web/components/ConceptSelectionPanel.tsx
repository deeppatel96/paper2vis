"use client";
import { useState } from "react";
import { ConceptStub, selectConcepts } from "@/lib/api";

const TYPE_COLOR: Record<string, string> = {
  equation_transform: "text-blue-400 border-blue-700 bg-blue-950/40",
  geometric:          "text-green-400 border-green-700 bg-green-950/40",
  number_flow:        "text-orange-400 border-orange-700 bg-orange-950/40",
  weight_update:      "text-yellow-400 border-yellow-700 bg-yellow-950/40",
  matrix_op:          "text-teal-400 border-teal-700 bg-teal-950/40",
  diagram:            "text-purple-400 border-purple-700 bg-purple-950/40",
  flow:               "text-red-400 border-red-700 bg-red-950/40",
  graph:              "text-blue-300 border-blue-600 bg-blue-950/40",
  timeline:           "text-gray-400 border-gray-600 bg-gray-900/40",
};

interface Props {
  jobId: string;
  stubs: ConceptStub[];
}

export default function ConceptSelectionPanel({ jobId, stubs }: Props) {
  const [selected, setSelected] = useState<Set<number>>(
    new Set(stubs.map((s) => s.index))
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(index: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function selectAll() { setSelected(new Set(stubs.map((s) => s.index))); }
  function selectNone() { setSelected(new Set()); }

  async function handleConfirm() {
    if (selected.size === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const indices = stubs
        .filter((s) => selected.has(s.index))
        .map((s) => s.index);
      await selectConcepts(jobId, indices);
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-xl border border-blue-800/50 bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Select concepts to animate</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {selected.size} of {stubs.length} selected · choose which ones to render
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <button onClick={selectAll} className="hover:text-gray-300 transition-colors">All</button>
          <span>·</span>
          <button onClick={selectNone} className="hover:text-gray-300 transition-colors">None</button>
        </div>
      </div>

      {/* Concept list */}
      <div className="divide-y divide-gray-800">
        {stubs.map((stub) => {
          const isOn = selected.has(stub.index);
          const typeClass = TYPE_COLOR[stub.visual_type] ?? "text-gray-400 border-gray-700 bg-gray-900/40";
          return (
            <button
              key={stub.index}
              onClick={() => toggle(stub.index)}
              className={`w-full text-left flex items-center gap-3 px-4 py-3 transition-colors
                ${isOn ? "bg-blue-950/20" : "hover:bg-gray-800/40"}`}
            >
              {/* Checkbox */}
              <div className={`w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors
                ${isOn ? "bg-blue-600 border-blue-500" : "border-gray-600"}`}>
                {isOn && (
                  <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </div>

              {/* Index */}
              <span className="text-xs font-mono text-gray-600 w-5 shrink-0">{stub.index + 1}</span>

              {/* Name + description */}
              <div className="flex-1 min-w-0">
                <span className={`text-sm font-medium block ${isOn ? "text-white" : "text-gray-400"}`}>
                  {stub.name}
                </span>
                {stub.description && (
                  <span className="text-xs text-gray-500 block mt-0.5 leading-snug">
                    {stub.description.split(".")[0].trim()}.
                  </span>
                )}
              </div>

              {/* Type badge */}
              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${typeClass} shrink-0`}>
                {stub.visual_type.replace(/_/g, " ")}
              </span>
            </button>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-800 flex items-center justify-between gap-3">
        {error && <p className="text-xs text-red-400 flex-1">{error}</p>}
        {!error && <p className="text-xs text-gray-600 flex-1">Pipeline is paused — confirm to start rendering</p>}
        <button
          onClick={handleConfirm}
          disabled={selected.size === 0 || submitting}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
                     disabled:text-gray-500 text-white text-sm font-semibold transition-colors shrink-0"
        >
          {submitting ? "Starting…" : `Animate ${selected.size} concept${selected.size !== 1 ? "s" : ""}`}
        </button>
      </div>
    </div>
  );
}
