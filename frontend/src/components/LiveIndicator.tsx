export function LiveIndicator({ updatedAt }: { updatedAt: number | null }) {
  return (
    <span className="live" title="每 5 秒自动刷新">
      ● 实时 · 更新于 {updatedAt ? new Date(updatedAt).toLocaleTimeString() : "…"}
    </span>
  );
}
