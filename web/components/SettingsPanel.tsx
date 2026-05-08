"use client";
import { useEffect, useState } from "react";
import { getAdminConfig, saveAdminConfig, TierConfig } from "@/lib/api";

const PROVIDERS = ["anthropic", "openai", "ollama"];
const QUALITY_OPTIONS = ["low_quality", "medium_quality", "high_quality"];

function TierForm({
  tier,
  config,
  onChange,
}: {
  tier: string;
  config: TierConfig;
  onChange: (updated: TierConfig) => void;
}) {
  function set<K extends keyof TierConfig>(key: K, value: TierConfig[K]) {
    onChange({ ...config, [key]: value });
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-bold uppercase tracking-widest text-gray-400 pt-1">
        {tier === "pro" ? "Pro tier" : "Mini tier (free)"}
      </h3>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[11px] text-gray-500 block mb-1">Extraction provider</label>
          <select
            value={config.llm_provider}
            onChange={(e) => set("llm_provider", e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2.5 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[11px] text-gray-500 block mb-1">Extraction model</label>
          <input
            value={config.llm_model}
            onChange={(e) => set("llm_model", e.target.value)}
            placeholder="e.g. gpt-4o-mini"
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2.5 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="text-[11px] text-gray-500 block mb-1">Codegen provider</label>
          <select
            value={config.codegen_provider}
            onChange={(e) => set("codegen_provider", e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2.5 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[11px] text-gray-500 block mb-1">Codegen model</label>
          <input
            value={config.codegen_model}
            onChange={(e) => set("codegen_model", e.target.value)}
            placeholder="e.g. gpt-4o"
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2.5 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="text-[11px] text-gray-500 block mb-1">Quality limit</label>
          <select
            value={config.quality_limit}
            onChange={(e) => set("quality_limit", e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2.5 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {QUALITY_OPTIONS.map((q) => <option key={q} value={q}>{q.replace("_quality", "")}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[11px] text-gray-500 block mb-1">Max concepts</label>
          <input
            type="number" min={1} max={32}
            value={config.max_concepts_limit}
            onChange={(e) => set("max_concepts_limit", Number(e.target.value))}
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2.5 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div className="col-span-2">
          <label className="text-[11px] text-gray-500 block mb-1">Jobs per month</label>
          <input
            type="number" min={1}
            value={config.jobs_per_month}
            onChange={(e) => set("jobs_per_month", Number(e.target.value))}
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-2.5 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>
    </div>
  );
}

interface Props {
  onClose: () => void;
}

export default function SettingsPanel({ onClose }: Props) {
  const [secret, setSecret] = useState(() =>
    typeof window !== "undefined" ? sessionStorage.getItem("admin_secret") ?? "" : ""
  );
  const [configs, setConfigs] = useState<Record<string, TierConfig> | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function load() {
    if (!secret) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getAdminConfig(secret);
      setConfigs(data);
      sessionStorage.setItem("admin_secret", secret);
    } catch {
      setError("Wrong secret or server unreachable.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!configs) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await saveAdminConfig(configs, secret);
      setConfigs(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  // Auto-load if secret is already in session
  useEffect(() => { if (secret) load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-gray-950 border-l border-gray-800 h-full overflow-y-auto flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 shrink-0">
          <h2 className="text-base font-semibold text-white">Settings</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 px-5 py-4 space-y-5">
          {/* Auth */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Admin secret</label>
            <div className="flex gap-2">
              <input
                type="password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && load()}
                placeholder="Enter admin secret…"
                className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button
                onClick={load}
                disabled={!secret || loading}
                className="px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 disabled:opacity-40 text-sm text-white transition-colors"
              >
                {loading ? "…" : "Load"}
              </button>
            </div>
            {error && <p className="text-xs text-red-400">{error}</p>}
          </div>

          {configs && (
            <>
              <div className="border-t border-gray-800" />
              {(["mini", "pro"] as const).map((tier) => (
                <TierForm
                  key={tier}
                  tier={tier}
                  config={configs[tier]}
                  onChange={(updated) => setConfigs((prev) => prev ? { ...prev, [tier]: updated } : prev)}
                />
              ))}
            </>
          )}
        </div>

        {/* Footer */}
        {configs && (
          <div className="px-5 py-4 border-t border-gray-800 shrink-0">
            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full py-2.5 rounded-xl font-semibold text-sm transition-colors
                bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white"
            >
              {saving ? "Saving…" : saved ? "Saved ✓" : "Save changes"}
            </button>
            <p className="text-[11px] text-gray-600 text-center mt-2">
              Changes apply to new jobs immediately. Persisted to disk.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
