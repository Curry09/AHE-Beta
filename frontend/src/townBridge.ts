// 数据适配层：把 backend 的 agents 映射成小镇工位（SeatState），驱动 Phaser 场景。
// 这是「用我们自己的数据喂 agent-town 引擎」的唯一接线点——不接 OpenClaw gateway。
import { gameEvents } from "@/lib/events";
import { WORKER_SPRITES } from "@/components/game/config/animations";
import type { SeatDef } from "@/components/game/utils/MapHelpers";
import type { SeatState } from "@/types/game";
import type { Agent } from "./types";

/** 把 agents 按顺序铺到地图已发现的工位上，产出 Phaser 需要的 SeatState[]。 */
export function agentsToSeats(agents: Agent[], seatDefs: SeatDef[]): SeatState[] {
  return seatDefs.map((seat, i) => {
    const agent = agents[i];
    if (!agent) {
      return { seatId: seat.seatId, label: "", seatType: "agent", status: "empty" };
    }
    return {
      seatId: seat.seatId,
      label: agent.label,
      seatType: "agent",
      assigned: true,
      spriteKey: WORKER_SPRITES[i % WORKER_SPRITES.length].key,
      status: agent.running ? "running" : "done",
    };
  });
}

/** seatId → agent 的绑定，供「点击小人打开对话」查回是哪个 agent。 */
export function seatAgentMap(agents: Agent[], seatDefs: SeatDef[]): Map<string, Agent> {
  const map = new Map<string, Agent>();
  seatDefs.forEach((seat, i) => {
    if (agents[i]) map.set(seat.seatId, agents[i]);
  });
  return map;
}

/** 把最新工位状态推给场景（WorkerManager 据此增删小人）。 */
export function pushSeats(seats: SeatState[]) {
  gameEvents.emit("seat-configs-updated", seats);
}
