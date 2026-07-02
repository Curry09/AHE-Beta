import type { Agent } from "../types";
import { groupByDept, roleMeta } from "./roles";
import { EmployeeCard } from "./EmployeeCard";

// 左侧部门栏：按部门（用户部/开发部）分组列员工工位卡片。
export function DepartmentRail({
  agents,
  now,
  selectedId,
  onSelect,
}: {
  agents: Agent[];
  now: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const groups = groupByDept(agents);
  return (
    <div className="rail">
      <div className="rail-head">团队 · {agents.length} 人在岗</div>
      {groups.length === 0 ? (
        <p className="empty">暂无在岗员工 —— 跑闭环后员工陆续上岗。</p>
      ) : (
        groups.map((g) => {
          const meta = roleMeta(g.role);
          return (
            <section key={g.role} className="dept">
              <div className="dept-head" style={{ color: meta.accent }}>
                {meta.emoji} {meta.dept}
                <span className="dept-count">{g.agents.length}</span>
              </div>
              <div className="dept-list">
                {g.agents.map((a) => (
                  <EmployeeCard
                    key={a.agent_id}
                    agent={a}
                    now={now}
                    selected={a.agent_id === selectedId}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}
