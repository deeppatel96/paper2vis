"use client";
import { useState, useEffect } from "react";
import { adminListUsers, AdminUser } from "@/lib/api";

const SESSION_KEY = "admin_secret";

export default function AdminUsersPage() {
  const [secret, setSecret] = useState("");
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function load(s = secret) {
    if (!s) return;
    sessionStorage.setItem(SESSION_KEY, s);
    setLoading(true);
    setError("");
    try {
      const data = await adminListUsers(s);
      setUsers(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (saved) { setSecret(saved); load(saved); }
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        <h1 className="text-xl font-bold">Admin — Users</h1>

        <div className="flex gap-3">
          <input
            type="password"
            placeholder="Admin secret"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-gray-500"
          />
          <button
            onClick={() => load()}
            disabled={!secret || loading}
            className="px-4 py-2 text-sm rounded-lg bg-blue-700 hover:bg-blue-600 disabled:opacity-40 font-medium transition-colors"
          >
            {loading ? "Loading…" : "Load"}
          </button>
        </div>

        {error && <p className="text-red-400 text-sm font-mono">{error}</p>}

        {users && (
          <div className="space-y-2">
            <p className="text-xs text-gray-500">{users.length} user{users.length !== 1 ? "s" : ""}</p>
            <div className="rounded-xl border border-gray-800 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-left">
                    <th className="px-4 py-2.5 text-gray-500 font-medium text-xs uppercase tracking-wide">Clerk ID</th>
                    <th className="px-4 py-2.5 text-gray-500 font-medium text-xs uppercase tracking-wide">Tier</th>
                    <th className="px-4 py-2.5 text-gray-500 font-medium text-xs uppercase tracking-wide">Jobs</th>
                    <th className="px-4 py-2.5 text-gray-500 font-medium text-xs uppercase tracking-wide">Est. Cost</th>
                    <th className="px-4 py-2.5 text-gray-500 font-medium text-xs uppercase tracking-wide">Joined</th>
                    <th className="px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.clerk_id} className="border-b border-gray-800/50 hover:bg-gray-900/50 transition-colors">
                      <td className="px-4 py-3 text-xs">
                        <span className="text-white">{u.email ?? "—"}</span>
                        <span className="block font-mono text-gray-600 text-[10px]">{u.clerk_id}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-semibold uppercase font-mono ${u.tier === "pro" ? "text-blue-400" : "text-gray-500"}`}>
                          {u.tier}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{u.job_count}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs font-mono">
                        {u.estimated_cost_usd != null ? `$${u.estimated_cost_usd.toFixed(3)}` : "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">{new Date(u.created_at).toLocaleDateString()}</td>
                      <td className="px-4 py-3 text-right">
                        <a
                          href={`/admin/users/${u.clerk_id}`}
                          className="text-xs text-blue-400 hover:text-blue-300 underline"
                        >
                          View jobs →
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
