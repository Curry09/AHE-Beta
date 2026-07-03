// 数据适配层：把 backend 的 roster（编制）+ agents（实时）映射成小镇的三个房间与座位，驱动 Phaser 场景。
// 这是「用我们自己的数据喂 agent-town 引擎」的唯一接线点——房间容量与后端 roster 一致。
import { gameEvents } from "@/lib/events";
import { computeLayout, type LayoutResult } from "@/lib/roomLayout";
import type { Agent, Roster } from "./types";

/** roster + agents → 三房间布局（房间矩形 + 座位定义 + 座位状态 + seatId→agent 绑定）。 */
export function buildLayout(roster: Roster, agents: Agent[]): LayoutResult {
  return computeLayout(roster, agents);
}

/** 把房间布局推给场景（OfficeScene 据此重绘房间、增删小人）。 */
export function pushLayout(layout: LayoutResult) {
  gameEvents.emit("rooms-updated", layout.rooms, layout.seatDefs, layout.seats, layout.extraDesks);
}
