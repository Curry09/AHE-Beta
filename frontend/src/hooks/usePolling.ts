import { useEffect, useRef, useState } from "react";

// Poll an async fetch function periodically; retain the last data on failure to avoid an empty dashboard during restarts or outages.
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number): T | null {
  const [data, setData] = useState<T | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const next = await fetcherRef.current();
        if (alive) setData(next);
      } catch {
        // Retain previous data.
      }
    };
    tick();
    const timer = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return data;
}
