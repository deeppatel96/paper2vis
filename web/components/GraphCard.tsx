"use client";
import { useRef, useEffect } from "react";
import { fileUrl } from "@/lib/api";

export default function GraphCard({ videoUrl }: { videoUrl: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = false;
    v.volume = 1;
  }, [videoUrl]);

  return (
    <div className="rounded-xl bg-gray-900 border border-blue-800/40 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-blue-400" />
        <div>
          <h3 className="font-semibold text-white text-sm">Concept Map</h3>
          <p className="text-xs text-gray-500">How all extracted concepts relate to each other</p>
        </div>
      </div>
      <div className="p-3">
        <video
          ref={videoRef}
          key={videoUrl}
          src={fileUrl(videoUrl)}
          controls
          preload="metadata"
          className="rounded w-full bg-black max-h-72"
        >
          Your browser does not support video.
        </video>
      </div>
    </div>
  );
}
