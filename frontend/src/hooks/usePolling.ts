import { useEffect, useRef, useState } from "react";

// 定时轮询一个异步取数函数；失败保留上次数据（后端重启/断网时看板不闪空）。
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
        // 保留旧数据
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
