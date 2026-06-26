import { useEffect, useRef, useState } from "react";

// 实时：挂载即拉一次，之后每 intervalMs 轮询一次（文件存储下即可看到新会话/新 issue）。
// fetcher 用 ref 持有，避免每次渲染重建 fetcher 导致定时器反复重启。
export function useLiveData<T>(fetcher: () => Promise<T>, intervalMs = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetcherRef
        .current()
        .then((d) => {
          if (!alive) return;
          setData(d);
          setError(null);
          setUpdatedAt(Date.now());
        })
        .catch((e) => {
          if (alive) setError(String(e));
        });
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  return { data, error, updatedAt };
}
