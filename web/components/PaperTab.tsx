"use client";

import { useState } from "react";
import { JobState, FigureInfo, ConceptResult, fileUrl, regenerateConcept } from "@/lib/api";

interface Props {
  job: JobState;
  onRegenerated: () => void;  // called after successful regen so parent re-subscribes SSE
}

export default function PaperTab({ job, onRegenerated }: Props) {
  const [selectedFigure, setSelectedFigure] = useState<number | null>(null);
  const [assignTarget, setAssignTarget] = useState<number | null>(null); // concept index
  const [regenPending, setRegenPending] = useState<number | null>(null); // concept index
  const [error, setError] = useState<string | null>(null);

  const pdfUrl = fileUrl(`/api/files/${job.job_id}/upload/${encodeURIComponent(job.pdf_name)}`);
  const [pdfPage, setPdfPage] = useState<number>(1);
  const figures = job.figures;
  const hasFigures = figures.length > 0;

  async function handleRegenerate() {
    if (selectedFigure === null || assignTarget === null) return;
    setRegenPending(assignTarget);
    setError(null);
    try {
      await regenerateConcept(job.job_id, assignTarget, selectedFigure);
      setSelectedFigure(null);
      setAssignTarget(null);
      onRegenerated();
    } catch (e) {
      setError(String(e));
    } finally {
      setRegenPending(null);
    }
  }

  // Which concept currently uses each figure
  const figureAssignments: Record<number, ConceptResult[]> = {};
  for (const c of job.concepts) {
    if (c.figure_index !== null && c.figure_index !== undefined) {
      figureAssignments[c.figure_index] = [...(figureAssignments[c.figure_index] ?? []), c];
    }
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-220px)] min-h-[500px]">
      {/* PDF viewer */}
      <div className="flex-1 min-w-0 flex flex-col gap-2">
        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
          {job.pdf_name}
        </div>
        <embed
          key={pdfPage}
          src={`${pdfUrl}#page=${pdfPage}`}
          type="application/pdf"
          className="flex-1 w-full rounded-lg border border-gray-800 bg-gray-900"
        />
      </div>

      {/* Sidebar: figure gallery + assignment panel */}
      <div className="w-72 shrink-0 flex flex-col gap-3 overflow-y-auto">
        {!hasFigures ? (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-xs text-gray-500">
            No figures extracted. Enable <span className="text-gray-300 font-mono">Figure Mode</span> when
            submitting a job to extract and animate paper figures.
          </div>
        ) : (
          <>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
              Extracted Figures
            </div>

            {figures.map((fig) => {
              const assigned = figureAssignments[fig.index] ?? [];
              const isSelected = selectedFigure === fig.index;
              return (
                <button
                  key={fig.index}
                  onClick={() => {
                    setSelectedFigure(isSelected ? null : fig.index);
                    if (!isSelected) setPdfPage(fig.page);
                  }}
                  className={`w-full text-left rounded-lg border overflow-hidden transition-all ${
                    isSelected
                      ? "border-blue-500 ring-1 ring-blue-500/50"
                      : "border-gray-700 hover:border-gray-500"
                  }`}
                >
                  <img
                    src={fileUrl(fig.url)}
                    alt={`Figure on page ${fig.page}`}
                    className="w-full object-contain max-h-40 bg-white"
                  />
                  <div className="px-2 py-1.5 bg-gray-900 flex items-center justify-between gap-2">
                    <span className="text-[10px] text-gray-500 font-mono">p. {fig.page}</span>
                    <div className="flex gap-1 flex-wrap justify-end">
                      {assigned.map((c) => (
                        <span key={c.index}
                          className="text-[9px] bg-blue-500/20 border border-blue-500/40 text-blue-300 rounded px-1.5 py-0.5 font-mono">
                          #{c.index + 1}
                        </span>
                      ))}
                      {assigned.length === 0 && (
                        <span className="text-[9px] text-gray-700 font-mono">unassigned</span>
                      )}
                    </div>
                  </div>
                </button>
              );
            })}

            {/* Assignment panel — appears when a figure is selected */}
            {selectedFigure !== null && (
              <div className="bg-gray-900 border border-blue-500/40 rounded-lg p-3 space-y-3">
                <div className="text-xs text-blue-300 font-semibold">
                  Figure {selectedFigure} selected
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 uppercase tracking-wide block mb-1">
                    Regenerate concept
                  </label>
                  <select
                    value={assignTarget ?? ""}
                    onChange={(e) => setAssignTarget(e.target.value === "" ? null : parseInt(e.target.value))}
                    className="w-full bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500"
                  >
                    <option value="">Pick a concept…</option>
                    {job.concepts.map((c) => (
                      <option key={c.index} value={c.index}>
                        {c.index + 1}. {c.name}
                        {c.figure_index === selectedFigure ? " (current)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  onClick={handleRegenerate}
                  disabled={assignTarget === null || regenPending !== null}
                  className="w-full py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                >
                  {regenPending !== null ? "Regenerating…" : "Regenerate →"}
                </button>
                {error && (
                  <div className="text-[10px] text-red-400 font-mono break-all">{error}</div>
                )}
              </div>
            )}

            {/* Legend */}
            <div className="text-[10px] text-gray-600 leading-relaxed">
              Click a figure to select it, then choose a concept to regenerate with that figure
              as visual ground truth.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
