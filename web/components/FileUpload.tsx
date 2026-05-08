"use client";
import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  onFile: (f: File) => void;
}

export default function FileUpload({ onFile }: Props) {
  const [dragging, setDragging] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const accept = useCallback(
    (file: File) => {
      if (file.type !== "application/pdf") return;
      setPreviewUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(file); });
      onFile(file);
    },
    [onFile]
  );

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) accept(file);
    },
    [accept]
  );

  if (previewUrl) {
    return (
      <div className="relative w-full h-72 rounded-xl overflow-hidden border border-gray-600 bg-gray-900 group">
        <iframe src={previewUrl} className="w-full h-full border-0" />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="absolute inset-0 flex items-end justify-center pb-3 bg-black/0 group-hover:bg-black/40 transition-colors"
        >
          <span className="opacity-0 group-hover:opacity-100 transition-opacity text-xs bg-gray-900 border border-gray-600 text-gray-200 px-3 py-1.5 rounded-lg font-medium">
            Change PDF
          </span>
        </button>
        <input ref={inputRef} type="file" accept=".pdf" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) accept(f); }} />
      </div>
    );
  }

  return (
    <label
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`flex flex-col items-center justify-center w-full h-52 border-2 border-dashed rounded-xl cursor-pointer transition-colors
        ${dragging ? "border-blue-400 bg-blue-950/30" : "border-gray-600 bg-gray-900 hover:border-gray-400"}`}
    >
      <svg className="w-10 h-10 mb-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
      <p className="text-sm text-gray-300">Drop a PDF here or <span className="text-blue-400 underline">browse</span></p>
      <p className="text-xs text-gray-500 mt-1">Academic papers work best</p>
      <input type="file" accept=".pdf" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) accept(f); }} />
    </label>
  );
}
