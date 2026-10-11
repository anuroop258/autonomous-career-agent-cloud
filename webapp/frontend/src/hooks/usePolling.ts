import { useEffect, useRef, useState, useCallback } from "react";
import { ApiError } from "../api/client";

/** Lightweight polling with single-flight requests and tab visibility pausing.
 * This prevents overlapping REST calls from piling up when the backend is busy.
 */
export function usePolling<T>(fn: () => Promise<T>, intervalMs = 15000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  fnRef.current = fn;

  const refresh = useCallback(async () => {
    if (!mounted.current || inFlight.current) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    inFlight.current = true;
    try {
      const result = await fnRef.current();
      if (mounted.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (mounted.current) setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      inFlight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    void refresh();

    const id = window.setInterval(refresh, Math.max(1000, intervalMs));
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refresh };
}
