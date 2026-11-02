import type { ReactNode } from "react";
import { fmtDate } from "../../lib/format";
import type {
  CommitsResponse,
  DeliveryResponse,
  IssuesResponse,
  OverviewResponse,
  RunState,
  Selection,
} from "../../types";
import {
  buildOpenAgentsSnapshot,
  type CommitCardModel,
  type IssueCardModel,
  type PullCardModel,
  type SourceState,
} from "./openAgentsModel";

export function OpenAgentsView(props: {
  issues: IssuesResponse | null;
  delivery: DeliveryResponse | null;
  commits: CommitsResponse | null;
  state: RunState | null;
  overview: OverviewResponse | null;
  round: "all" | number;
  onSelect: (sel: Selection) => void;
}) {
  const snapshot = buildOpenAgentsSnapshot(props);
  const openagentsIssues = snapshot.readyIssues.filter((item) => item.stage === "openagents");
  const readyIssues = snapshot.readyIssues.filter((item) => item.stage !== "openagents");
  const funnelReady = props.overview?.funnel?.ready ?? null;
  return (
    <main className="openagents-view warehouse-view">
      <section className="openagents-hero warehouse-hero">
        <div>
          <div className="openagents-kicker">OpenAgents delivery</div>
          <h2>OpenAgents</h2>
          <p>
            openagents → ready → PR → needs-human / conflict → main。这里保持只读，展示
            AHE-Beta 已暴露的 Gitea 观测数据。
          </p>
        </div>
        <div className="openagents-source-grid" aria-label="数据源状态">
          <SourceChip source={snapshot.sources.issues} />
          <SourceChip source={snapshot.sources.delivery} />
          <SourceChip source={snapshot.sources.commits} />
          <SourceChip source={snapshot.sources.state} />
          <span className="openagents-source-chip muted">{snapshot.currentRound}</span>
          <span className="openagents-source-chip muted">
            main {snapshot.latestRoundSha ? snapshot.latestRoundSha.slice(0, 7) : "—"}
          </span>
        </div>
      </section>

      <section className="openagents-kpis warehouse-signboard" aria-label="OpenAgents 状态">
        <Kpi label="openagents handoff" value={snapshot.kpis.handoff} hint="awaiting vigil intake" />
        <Kpi label="PR" value={snapshot.kpis.pulls} hint="/api/delivery open PR" />
        <Kpi label="needs-human" value={snapshot.kpis.needsHuman} hint="PR + issue" tone="danger" />
        <Kpi label="main commits" value={snapshot.kpis.commits} hint="recent commits" />
      </section>

      <section className="openagents-warehouse" aria-label="OpenAgents flow">
        <div className="warehouse-roof">
          <div>
            <span>OpenAgents flow</span>
            <b>openagents → ready → PR → needs-human / conflict → main</b>
          </div>
          <p>每张卡片都对应真实 issue / PR / commit；没有真实数据时只显示空态，不造 mock。</p>
        </div>
        <div className="warehouse-round-strip" aria-label="轮次状态">
          <span>
            <b>当前轮次</b>
            {snapshot.currentRound}
          </span>
          <span>
            <b>round sha</b>
            {snapshot.latestRoundSha ? snapshot.latestRoundSha.slice(0, 12) : "—"}
          </span>
          <span>
            <b>ready funnel</b>
            {funnelReady === null ? "—" : funnelReady}
          </span>
        </div>
        <div className="warehouse-conveyor" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="warehouse-stations">
          <Station
            title="openagents"
            subtitle="Owner admit"
            count={openagentsIssues.length}
            source={snapshot.sources.issues}
            empty="暂无 openagents issue。"
          >
            {openagentsIssues.map((item) => (
              <IssueCard key={item.issue.number} item={item} onSelect={props.onSelect} />
            ))}
          </Station>
          <Station
            title="ready"
            subtitle="vigil intake"
            count={readyIssues.length}
            source={snapshot.sources.issues}
            empty="暂无 ready issue。"
          >
            {readyIssues.map((item) => (
              <IssueCard key={item.issue.number} item={item} onSelect={props.onSelect} />
            ))}
          </Station>
          <Station
            title="PR"
            subtitle="branch / review / merge"
            count={snapshot.pulls.length}
            source={snapshot.stationSources.pulls}
            empty="暂无 open PR。"
          >
            {snapshot.pulls.map((item) => (
              <PullCard key={item.pull.number} item={item} />
            ))}
          </Station>
          <GateStation
            issueSource={snapshot.sources.issues}
            deliverySource={snapshot.stationSources.pulls}
            issues={snapshot.needsHumanIssues}
            pulls={snapshot.needsHumanPulls}
            conflicts={snapshot.conflictPulls}
            onSelect={props.onSelect}
          />
          <Station
            title="main"
            subtitle="commit / round anchor"
            count={snapshot.commits.length}
            source={snapshot.stationSources.commits}
            empty="暂无 main commit。"
          >
            {snapshot.commits.map((item) => (
              <CommitCard key={item.commit.sha} item={item} onSelect={props.onSelect} />
            ))}
          </Station>
        </div>
      </section>

      <section className="openagents-footnote warehouse-footnote">
        <div>
          <b>数据来源</b>
          <span>/api/issues</span>
          <span>/api/delivery</span>
          <span>/api/commits</span>
          <span>/api/state</span>
        </div>
        <p>
          当前 demo 不读取 OpenAgents 内部 work_queue / timing / stream。需求漏斗 ready：
          {funnelReady === null ? "—" : funnelReady}。
        </p>
      </section>
    </main>
  );
}

function SourceChip({ source }: { source: SourceState }) {
  return <span className={`openagents-source-chip ${source.status}`}>{source.label}</span>;
}

function Kpi(props: { label: string; value: number | null; hint: string; tone?: "danger" }) {
  return (
    <div className={props.tone === "danger" ? "openagents-kpi danger" : "openagents-kpi"}>
      <div className="openagents-kpi-label">{props.label}</div>
      <div className="openagents-kpi-value">{props.value === null ? "—" : props.value}</div>
      <div className="openagents-kpi-hint">{props.hint}</div>
    </div>
  );
}

function Station(props: {
  title: string;
  subtitle: string;
  count: number;
  source: SourceState;
  empty: string;
  children: ReactNode;
}) {
  return (
    <section className="warehouse-station">
      <div className="warehouse-station-head">
        <div>
          <h3>{props.title}</h3>
          <span>{props.subtitle}</span>
        </div>
        <b>{props.count}</b>
      </div>
      <div className="warehouse-station-body">
        {props.count === 0 ? <SourceEmpty source={props.source} empty={props.empty} /> : props.children}
      </div>
    </section>
  );
}

function SourceEmpty(props: { source: SourceState; empty: string }) {
  if (props.source.status === "loading") return <div className="empty">{props.source.label}</div>;
  if (props.source.status === "disconnected" || props.source.status === "unavailable") {
    return <div className="disconnected">{props.source.label}</div>;
  }
  return <div className="empty">{props.empty}</div>;
}

function IssueCard(props: { item: IssueCardModel; onSelect: (sel: Selection) => void }) {
  const { issue } = props.item;
  return (
    <button
      className="openagents-card issue-card work-order-card"
      onClick={() => props.onSelect({ type: "issue", number: issue.number })}
    >
      <div className="openagents-card-top">
        <span className="num">#{issue.number}</span>
        <span className={`chip ${props.item.stage === "openagents" ? "tag" : "open"}`}>
          {stageLabel(props.item.stage)}
        </span>
      </div>
      <div className="openagents-card-title">{issue.title}</div>
      <IssueMeta item={props.item} />
    </button>
  );
}

function IssueMeta({ item }: { item: IssueCardModel }) {
  return (
    <div className="openagents-meta-row">
      <span>{item.kind}</span>
      {item.priority && <span>{item.priority}</span>}
      {item.round !== null && <span>round-{item.round}</span>}
      {item.age !== null && <span>{item.age}d</span>}
    </div>
  );
}

function PullCard({ item }: { item: PullCardModel }) {
  const { pull } = item;
  return (
    <a className="openagents-card pr-card work-order-card" href={pull.url} target="_blank" rel="noreferrer">
      <div className="openagents-card-top">
        <span className="num">PR #{pull.number}</span>
        <span className={`chip ${pullChipClass(item.status)}`}>{pullStatusLabel(item.status)}</span>
      </div>
      <div className="openagents-card-title">{pull.title}</div>
      <div className="openagents-meta-row">
        <span>{pull.head_branch || "branch —"}</span>
        <span>{fmtDate(pull.updated_at) || "updated —"}</span>
      </div>
      {pull.closes_issues.length > 0 && (
        <div className="openagents-linked-issues">
          closes {pull.closes_issues.map((n) => `#${n}`).join(", ")}
        </div>
      )}
    </a>
  );
}

function GateStation(props: {
  issueSource: SourceState;
  deliverySource: SourceState;
  issues: IssueCardModel[];
  pulls: PullCardModel[];
  conflicts: PullCardModel[];
  onSelect: (sel: Selection) => void;
}) {
  const loading = props.issueSource.status === "loading" || props.deliverySource.status === "loading";
  const unavailableSources = [props.issueSource, props.deliverySource].filter(
    (source) => source.status === "disconnected" || source.status === "unavailable",
  );
  const blockedPullCount = new Set(
    [...props.pulls, ...props.conflicts].map((item) => item.pull.number),
  ).size;
  const count = props.issues.length + blockedPullCount;
  return (
    <section className="warehouse-station gate-station">
      <div className="warehouse-station-head">
        <div>
          <h3>needs-human / conflict</h3>
          <span>OpenAgents gate</span>
        </div>
        <b>{count}</b>
      </div>
      <div className="warehouse-station-body">
        {count === 0 && loading ? <div className="empty">读取 needs-human / conflict…</div> : null}
        {count === 0 && unavailableSources.length > 0 ? (
          <div className="disconnected">
            {[...new Set(unavailableSources.map((source) => source.label))].join("；")}
          </div>
        ) : null}
        {count === 0 && !loading && unavailableSources.length === 0 ? (
          <div className="empty">暂无 needs-human / conflict。</div>
        ) : null}
        {props.pulls.length > 0 && <GateGroup title="PR needs-human" pulls={props.pulls} />}
        {props.issues.length > 0 && (
          <GateGroup title="Issue needs-human" issues={props.issues} onSelect={props.onSelect} />
        )}
        {props.conflicts.length > 0 && <GateGroup title="PR conflict" pulls={props.conflicts} />}
      </div>
    </section>
  );
}

function GateGroup(props: {
  title: string;
  pulls?: PullCardModel[];
  issues?: IssueCardModel[];
  onSelect?: (sel: Selection) => void;
}) {
  return (
    <div className="openagents-needs-group gate-group">
      <div className="openagents-needs-title">{props.title}</div>
      {props.pulls?.map((item) => <PullCard key={`${props.title}-${item.pull.number}`} item={item} />)}
      {props.issues?.map((item) =>
        props.onSelect ? (
          <IssueCard key={`${props.title}-${item.issue.number}`} item={item} onSelect={props.onSelect} />
        ) : null,
      )}
    </div>
  );
}

function CommitCard(props: { item: CommitCardModel; onSelect: (sel: Selection) => void }) {
  const { commit } = props.item;
  return (
    <button
      className="openagents-card commit-card shipping-card"
      onClick={() => props.onSelect({ type: "commit", sha: commit.sha })}
    >
      <div className="openagents-card-top">
        <span className="num">{commit.short_sha || commit.sha.slice(0, 7)}</span>
        {props.item.roundAnchor && <span className="chip open">round anchor</span>}
      </div>
      <div className="openagents-card-title">{commit.message}</div>
      <div className="openagents-meta-row">
        <span>{commit.author || "author —"}</span>
        <span>{fmtDate(commit.date) || "date —"}</span>
      </div>
    </button>
  );
}

function stageLabel(stage: IssueCardModel["stage"]): string {
  if (stage === "openagents") return "openagents";
  if (stage === "ready") return "ready";
  return "ready";
}

function pullStatusLabel(status: PullCardModel["status"]): string {
  if (status === "needs-human-conflict") return "needs-human + conflict";
  if (status === "needs-human") return "needs-human";
  if (status === "conflict") return "conflict";
  if (status === "mergeable") return "mergeable";
  return "unknown";
}

function pullChipClass(status: PullCardModel["status"]): string {
  if (status === "needs-human-conflict") return "danger";
  if (status === "needs-human") return "danger";
  if (status === "conflict") return "warn";
  if (status === "mergeable") return "open";
  return "";
}
