import { getCommit } from "../../api";
import { useFetch } from "../../hooks/useFetch";
import { fmtDate } from "../../lib/format";
import { Diff } from "../Stream";

// Full commit: complete message + author/time/tags + per-file statistics + line-colored diff.
export function CommitDetailView(props: { sha: string; onBack: () => void }) {
  const { sha, onBack } = props;
  const data = useFetch(() => getCommit(sha), [sha]);
  const commit = data?.commit ?? null;

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ‹ Back
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
        {!data && <div className="empty">Loading…</div>}
        {data && !data.connected && (
          <div className="disconnected">Gitea is disconnected; commit details are unavailable.</div>
        )}
        {commit && (
          <>
            <dl className="kv">
              <dt>Author</dt>
              <dd>{commit.author}</dd>
              <dt>Time</dt>
              <dd>{fmtDate(commit.date)}</dd>
              <dt>Changes</dt>
              <dd className="stats">
                <span className="add">+{commit.stats.additions}</span>{" "}
                <span className="del">−{commit.stats.deletions}</span> · {commit.files.length} files
              </dd>
              {commit.url && (
                <>
                  <dt>Gitea</dt>
                  <dd>
                    <a className="link" href={commit.url} target="_blank" rel="noreferrer">
                      Open ↗
                    </a>
                  </dd>
                </>
              )}
            </dl>
            <div className="block">
              <div className="block-title">Commit message</div>
              <div className="prose">{commit.message}</div>
            </div>
            {commit.files.length > 0 && (
              <div className="block">
                <div className="block-title">File</div>
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
