"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function InvitePage() {
  return (
    <Suspense fallback={
      <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center p-8">
        <div className="w-full max-w-sm text-center">
          <h1 className="text-2xl font-bold">Redeeming invite…</h1>
        </div>
      </main>
    }>
      <InviteInner />
    </Suspense>
  );
}

function InviteInner() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "success" | "error" | "idle">("idle");
  const [message, setMessage] = useState("");

  const code = searchParams.get("code") ?? "";

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      // Redirect to sign-in, then come back here with the code
      router.push(`/sign-in?redirect_url=/invite?code=${encodeURIComponent(code)}`);
      return;
    }
    if (!code) {
      setStatus("error");
      setMessage("No invite code found in the URL.");
      return;
    }
    // Auto-redeem on page load
    setStatus("loading");
    getToken().then((token) =>
      fetch(`${API}/api/invite`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ code }),
      })
    ).then(async (res) => {
      if (res.ok) {
        setStatus("success");
        setMessage("You've been upgraded to Pro!");
        setTimeout(() => router.push("/"), 2500);
      } else {
        const text = await res.text();
        setStatus("error");
        setMessage(text.includes("Invalid") ? "Invalid invite code." : "Something went wrong. Try again.");
      }
    }).catch(() => {
      setStatus("error");
      setMessage("Could not connect to the server.");
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  return (
    <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center p-8">
      <div className="w-full max-w-sm text-center space-y-4">
        <h1 className="text-2xl font-bold">Redeeming invite…</h1>

        {status === "loading" && (
          <p className="text-gray-400">Activating your Pro access…</p>
        )}

        {status === "success" && (
          <div className="rounded-xl bg-green-950 border border-green-700 px-4 py-3 space-y-1">
            <p className="text-green-300 font-semibold">{message}</p>
            <p className="text-green-500 text-sm">Redirecting you to the app…</p>
          </div>
        )}

        {status === "error" && (
          <div className="rounded-xl bg-red-950 border border-red-800 px-4 py-3 space-y-2">
            <p className="text-red-300">{message}</p>
            <button
              onClick={() => router.push("/")}
              className="text-sm text-gray-400 hover:text-white underline"
            >
              Go to app
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
