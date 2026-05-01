"use client";
import { useState } from "react";
import { fileUrl } from "@/lib/api";

const TYPE_COLOR: Record<string, string> = {
  equation_transform: "#3b82f6",
  geometric:          "#22c55e",
  number_flow:        "#f97316",
  weight_update:      "#eab308",
  matrix_op:          "#14b8a6",
  diagram:            "#a855f7",
  flow:               "#ef4444",
  graph:              "#60a5fa",
  timeline:           "#6b7280",
};

interface Edge { from: number; to: number; label: string; }
interface ConceptNode { index: number; name: string; visual_type: string; }

interface Props {
  concepts: ConceptNode[];
  edges: Edge[];
  graphVideoUrl?: string | null;
}

function computePositions(n: number, W: number, H: number): Array<{ x: number; y: number }> {
  if (n === 0) return [];
  const cx = W / 2, cy = H / 2;
  if (n <= 8) {
    const r = Math.min(cx, cy) * 0.70;
    return Array.from({ length: n }, (_, i) => {
      const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
      return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
    });
  }
  // Grid layout for many concepts
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const padX = W / (cols + 1), padY = H / (rows + 1);
  return Array.from({ length: n }, (_, i) => ({
    x: padX * ((i % cols) + 1),
    y: padY * (Math.floor(i / cols) + 1),
  }));
}

function scrollAndHighlight(index: number) {
  const el = document.getElementById(`concept-${index}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.style.boxShadow = "0 0 0 3px #3b82f6";
  setTimeout(() => { el.style.boxShadow = ""; }, 2000);
}

export default function InteractiveConceptMap({ concepts, edges, graphVideoUrl }: Props) {
  const [showVideo, setShowVideo] = useState(false);
  const [hovered, setHovered] = useState<number | null>(null);
  const W = 760, H = 340, NODE_R = 30;
  const positions = computePositions(concepts.length, W, H);

  if (concepts.length === 0) return null;

  return (
    <div className="rounded-xl border border-blue-800/40 bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-blue-400" />
          <div>
            <h3 className="font-semibold text-white text-sm">Concept Map</h3>
            <p className="text-xs text-gray-500">Click any node to jump to its animation</p>
          </div>
        </div>
        {graphVideoUrl && (
          <button
            onClick={() => setShowVideo((v) => !v)}
            className="text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors"
          >
            {showVideo ? "Hide movie" : "Movie mode"}
          </button>
        )}
      </div>

      {/* Interactive SVG map */}
      {!showVideo && (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          style={{ maxHeight: 340, display: "block" }}
        >
          <defs>
            <marker id="cmap-arrow" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto">
              <path d="M0,0 L0,7 L7,3.5 z" fill="#4b5563" />
            </marker>
          </defs>

          {/* Edges */}
          {edges.map((edge, i) => {
            const from = positions[edge.from];
            const to = positions[edge.to];
            if (!from || !to) return null;
            const dx = to.x - from.x, dy = to.y - from.y;
            const dist = Math.hypot(dx, dy);
            if (dist < 1) return null;
            const ux = dx / dist, uy = dy / dist;
            const x1 = from.x + ux * NODE_R;
            const y1 = from.y + uy * NODE_R;
            const x2 = to.x - ux * (NODE_R + 6);
            const y2 = to.y - uy * (NODE_R + 6);
            const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
            const isActive = hovered === edge.from || hovered === edge.to;
            return (
              <g key={i}>
                <line
                  x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke={isActive ? "#6b7280" : "#374151"}
                  strokeWidth={isActive ? 1.8 : 1.2}
                  markerEnd="url(#cmap-arrow)"
                />
                {isActive && (
                  <>
                    <rect
                      x={mx - edge.label.length * 3} y={my - 8}
                      width={edge.label.length * 6} height={12}
                      rx={2} fill="#1f2937" opacity={0.9}
                    />
                    <text x={mx} y={my + 1} textAnchor="middle" fontSize={8} fill="#9ca3af" fontFamily="monospace">
                      {edge.label}
                    </text>
                  </>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {concepts.map((concept) => {
            const pos = positions[concept.index];
            if (!pos) return null;
            const color = TYPE_COLOR[concept.visual_type] ?? "#6b7280";
            const isHov = hovered === concept.index;
            // Split name into up to 2 display lines
            const words = concept.name.split(" ");
            const line1 = words.slice(0, 2).join(" ");
            const line2 = words.length > 2 ? words.slice(2, 4).join(" ") : null;
            return (
              <g
                key={concept.index}
                onClick={() => scrollAndHighlight(concept.index)}
                onMouseEnter={() => setHovered(concept.index)}
                onMouseLeave={() => setHovered(null)}
                style={{ cursor: "pointer" }}
              >
                <circle
                  cx={pos.x} cy={pos.y} r={isHov ? NODE_R + 3 : NODE_R}
                  fill={color + "22"}
                  stroke={color}
                  strokeWidth={isHov ? 2.5 : 1.5}
                  style={{ transition: "all 0.15s" }}
                />
                <text x={pos.x} y={pos.y + (line2 ? -5 : 3)} textAnchor="middle" fontSize={9} fill="white" fontWeight="600" fontFamily="sans-serif">
                  {line1.length > 14 ? line1.slice(0, 12) + "…" : line1}
                </text>
                {line2 && (
                  <text x={pos.x} y={pos.y + 8} textAnchor="middle" fontSize={9} fill="white" fontWeight="600" fontFamily="sans-serif">
                    {line2.length > 14 ? line2.slice(0, 12) + "…" : line2}
                  </text>
                )}
                <text x={pos.x} y={pos.y + NODE_R + 11} textAnchor="middle" fontSize={7.5} fill="#6b7280" fontFamily="monospace">
                  {concept.index + 1}
                </text>
              </g>
            );
          })}
        </svg>
      )}

      {/* Legend */}
      {!showVideo && (
        <div className="px-4 py-2 border-t border-gray-800 flex flex-wrap gap-x-4 gap-y-1">
          {Array.from(new Set(concepts.map((c) => c.visual_type))).map((vt) => (
            <span key={vt} className="flex items-center gap-1 text-[10px] font-mono text-gray-500">
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: TYPE_COLOR[vt] ?? "#6b7280" }} />
              {vt.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {/* Movie mode video */}
      {showVideo && graphVideoUrl && (
        <div className="p-3">
          <video
            key={graphVideoUrl}
            src={fileUrl(graphVideoUrl)}
            controls
            preload="metadata"
            className="rounded w-full bg-black max-h-72"
          >
            Your browser does not support video.
          </video>
        </div>
      )}
    </div>
  );
}
