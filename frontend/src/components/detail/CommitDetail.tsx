import { getCommit } from "../../api";
import { useFetch } from "../../hooks/useFetch";
import { fmtDate } from "../../lib/format";
import { Diff } from "../Stream";

// commit 全量：message 全文 + 作者/时间/tags + 文件级统计 + 行级着色 diff。
export function CommitDetailView(props: { sha: string; onBack: () => void }) {
  const { sha, onBack } = props;
  const data = useFetch(() => getCommit(sha), [sha]);
  const commit = data?.commit ?? null;

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ 返回
        </button>
        <span className="detail-title" style={{ fontFamily: "var(--mono)" }}>
          {sha.slice(0, 7)}
        </span>
        {commit?.tags.map((t) => (
          <span key={t} className="chip tag">
            {t}
          </span>
        ))}
      </div>
      <div className="detail-body">
        {!data && <div className="empty">加载中…</div>}
        {data && !data.connected && (
          <div className="disconnected">未连接 Gitea，看不到 commit 详情。</div>
        )}
        {commit && (
          <>
            <dl className="kv">
              <dt>作者</dt>
              <dd>{commit.author}</dd>
              <dt>时间</dt>
              <dd>{fmtDate(commit.date)}</dd>
              <dt>变更</dt>
              <dd className="stats">
                <span className="add">+{commit.stats.additions}</span>{" "}
                <span className="del">−{commit.stats.deletions}</span> · {commit.files.length} 个文件
              </dd>
              {commit.url && (
                <>
                  <dt>Gitea</dt>
                  <dd>
                    <a className="link" href={commit.url} target="_blank" rel="noreferrer">
                      打开 ↗
                    </a>
                  </dd>
                </>
              )}
            </dl>
            <div className="block">
              <div className="block-title">提交信息</div>
              <div className="prose">{commit.message}</div>
            </div>
            {commit.files.length > 0 && (
              <div className="block">
                <div className="block-title">文件</div>
                <div className="file-list">
                  {commit.files.map((f) => (
                    <span key={f.filename}>
                      {f.filename} <span style={{ color: "var(--text-faint)" }}>{f.status}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <Diff diff={commit.diff} />
          </>
        )}
      </div>
    </div>
  );
}
