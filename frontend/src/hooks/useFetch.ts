import { useEffect, useState } from "react";

// 一次性取数（选中详情用，不轮询）：deps 变化即重取，卸载丢弃迟到结果。
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
          // 详情取失败时留空态，由视图给降级文案
        });
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return data;
}
