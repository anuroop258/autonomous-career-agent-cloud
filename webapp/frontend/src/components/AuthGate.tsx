import { useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api, ApiError, AUTH_EVENT, clearApiKey, getApiKey, setApiKey } from "../api/client";

type Phase = "loading" | "open" | "login";

// Shows a key prompt when the backend runs with CAREER_AGENT_API_KEY. When no key is
// configured (normal local use) or the backend cannot be reached, the app opens as before.
export default function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [required, setRequired] = useState(false);
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    try {
      const status = await api.authStatus();
      setRequired(status.auth_required);
      if (!status.auth_required) return setPhase("open");
      if (!getApiKey()) return setPhase("login");
      try {
        await api.authCheck();
        setPhase("open");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 429)) {
          if (e.status === 401) clearApiKey();
          setPhase("login");
        } else {
          setPhase("open");
        }
      }
    } catch {
      setPhase("open"); // backend unreachable: keep the old behaviour (pages show their own errors)
    }
  }, []);

  useEffect(() => { void check(); }, [check]);
  useEffect(() => {
    const onAuth = () => { setRequired(true); setPhase("login"); };
    window.addEventListener(AUTH_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_EVENT, onAuth);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!key.trim()) return;
    setBusy(true);
    setError("");
    setApiKey(key.trim());
    try {
      await api.authCheck();
      setKey("");
      setPhase("open");
    } catch (err) {
      clearApiKey();
      setError(err instanceof ApiError
        ? (err.status === 429 ? err.message : "That key is not correct.")
        : "Cannot reach the backend. Is it running?");
    } finally {
      setBusy(false);
    }
  }

  if (phase === "loading") return <div style={{ padding: 40, color: "#6f6a60" }}>Connecting…</div>;

  if (phase === "login") {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "#faf8f3", padding: 16 }}>
        <form onSubmit={submit} className="reference-panel" style={{ width: "100%", maxWidth: 380, display: "grid", gap: 14 }}>
          <h1 style={{ margin: 0, fontSize: 22 }}>CareerAgent</h1>
          <p style={{ margin: 0, color: "#6f6a60", lineHeight: 1.5 }}>Enter your access key to continue.</p>
          <input
            type="password" autoFocus autoComplete="current-password" value={key}
            onChange={(e) => setKey(e.target.value)} placeholder="Access key"
            style={{ padding: "12px 14px", borderRadius: 12, border: "1px solid #d9d3c5", fontSize: 16 }}
          />
          {error && <div style={{ color: "#9b3d27", background: "#f7e7e3", padding: "8px 12px", borderRadius: 10, fontSize: 14 }}>{error}</div>}
          <button className="my-btn dark" type="submit" disabled={busy || !key.trim()}>{busy ? "Checking…" : "Unlock"}</button>
        </form>
      </div>
    );
  }

  return (
    <>
      {children}
      {required && (
        <button
          onClick={() => { clearApiKey(); setPhase("login"); }}
          title="Forget the key on this device"
          style={{ position: "fixed", right: 12, bottom: 12, zIndex: 50, fontSize: 12, padding: "6px 10px",
                   borderRadius: 999, border: "1px solid #d9d3c5", background: "#fffdf8", color: "#6f6a60", cursor: "pointer" }}
        >
          Lock
        </button>
      )}
    </>
  );
}
