// 公司抬头栏：品牌 + 三指标 + live 状态 + 暂停/继续。紧凑单行（窄屏换行）。
export function Header({
  openIssues,
  sessions,
  feeling,
  running,
  updatedAt,
  paused,
  onTogglePause,
}: {
  openIssues: number | string;
  sessions: number | string;
  feeling: number | string;
  running: number;
  updatedAt: number | null;
  paused: boolean;
  onTogglePause: () => void;
}) {
  const clock = updatedAt ? new Date(updatedAt).toLocaleTimeString() : "—";
  return (
    <header className="hdr">
      <div className="hdr-brand">
        <span className="hdr-logo">◆</span>
        <div>
          <div className="hdr-name">auto-designer Inc.</div>
          <div className="hdr-tag">harness 自进化观测看板</div>
        </div>
      </div>

      <div className="hdr-metrics">
        <span className="metric">
          <em>📋 open issue</em>
          <b>{openIssues}</b>
        </span>
        <span className="metric">
          <em>💬 会话</em>
          <b>{sessions}</b>
        </span>
        <span className="metric">
          <em>😊 体感</em>
          <b>{feeling}</b>
        </span>
      </div>

      <div className="hdr-right">
        <span className={`live ${paused ? "off" : "on"}`}>
          <i className="dot" />
          {paused ? "已暂停" : `live · ${running} 在岗`}
        </span>
        <span className="hdr-clock">{clock}</span>
        <button className="btn" onClick={onTogglePause}>
          {paused ? "继续" : "暂停"}
        </button>
      </div>
    </header>
  );
}
