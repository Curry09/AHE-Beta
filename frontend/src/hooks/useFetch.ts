import { useEffect, useState } from "react";

// One-time fetch for selected details (no polling): refetch when deps change; discard late results after unmount.
export function useFetch<T>(fn: (() => Promise<T>) | null, deps: unknown[]): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    setData(null);
    if (fn) {
      fn()
        .then((d) => {
          if (alive) setData(d);
        })
        .catch(() => {
          // Leave an empty state on detail fetch failures; the view supplies fallback text.
        });
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return data;
}
