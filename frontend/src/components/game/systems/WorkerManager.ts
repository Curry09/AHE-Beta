import * as Phaser from "phaser";
import { Worker, type POI, type WorkerStatus } from "../entities/Worker";
import type { Direction } from "../config/animations";
import type { Pathfinder } from "../utils/Pathfinder";
import type { SeatDef } from "../utils/MapHelpers";
import type { SeatState, SeatStatus } from "@/types/game";
import type { Room } from "@/lib/roomLayout";

/** 座位状态（后端 /api/agents 投影）→ 小人可视状态（状态点颜色 / 是否游走）。 */
function toWorkerStatus(status: SeatStatus): WorkerStatus {
  if (status === "running" || status === "returning") return "working";
  if (status === "done") return "done";
  if (status === "failed") return "failed";
  return "idle";
}

export class WorkerManager {
  private scene: Phaser.Scene;
  private pois: POI[];
  private pathfinder: Pathfinder;

  workers: Worker[] = [];
  runWorkerMap = new Map<string, Worker>();
  seatDefs: SeatDef[] = [];

  constructor(scene: Phaser.Scene, seatDefs: SeatDef[], pois: POI[], pathfinder: Pathfinder) {
    this.scene = scene;
    this.seatDefs = seatDefs;
    this.pois = pois;
    this.pathfinder = pathfinder;
  }

  /** 房间布局变化（roster/agents 更新）时替换座位定义，供 syncWorkers 据此增删小人。 */
  setSeatDefs(seatDefs: SeatDef[]) {
    this.seatDefs = seatDefs;
  }

  spawnWorker(seatDef: SeatDef, seat: SeatState): Worker | null {
    if (!seat.spriteKey) return null;
    const initialFacing: Direction = seatDef.facing;
    const worker = new Worker(
      this.scene,
      seatDef.x,
      seatDef.y,
      seat.spriteKey,
      seatDef.seatId,
      seat.label,
      initialFacing,
      (seat.roleTitle as Room | undefined) ?? null,
    );
    worker.setPOIs(this.pois);
    worker.setPathfinder(this.pathfinder);
    worker.sprite.setCollideWorldBounds(true);
    return worker;
  }

  syncWorkers(seats: SeatState[], clearNearest: (worker: Worker) => void) {
    const nextBySeatId = new Map(
      seats.filter((seat) => seat.assigned && seat.spriteKey).map((seat) => [seat.seatId, seat]),
    );
    const existingBySeatId = new Map(this.workers.map((worker) => [worker.seatId, worker]));
    const nextWorkers: Worker[] = [];

    for (const seatDef of this.seatDefs) {
      const seat = nextBySeatId.get(seatDef.seatId);
      const existing = existingBySeatId.get(seatDef.seatId);

      if (!seat) {
        if (existing) {
          this.cleanupWorkerRunIds(existing);
          clearNearest(existing);
          existing.destroy();
          existingBySeatId.delete(seatDef.seatId);
        }
        continue;
      }

      const needsRecreate =
        !existing || existing.spriteKey !== seat.spriteKey || existing.label !== seat.label;

      if (needsRecreate) {
        if (existing) {
          this.cleanupWorkerRunIds(existing);
          clearNearest(existing);
          existing.destroy();
          existingBySeatId.delete(seatDef.seatId);
        }
        const created = this.spawnWorker(seatDef, seat);
        if (created) {
          created.syncLive(toWorkerStatus(seat.status), seat.latestMessage ?? null);
          nextWorkers.push(created);
        }
        continue;
      }

      // 每次轮询把后端实时状态同步到小人：状态点 + 最新对话气泡。
      existing.syncLive(toWorkerStatus(seat.status), seat.latestMessage ?? null);
      nextWorkers.push(existing);
      existingBySeatId.delete(seatDef.seatId);
    }

    for (const stale of existingBySeatId.values()) {
      this.cleanupWorkerRunIds(stale);
      clearNearest(stale);
      stale.destroy();
    }

    this.workers = nextWorkers;
  }

  cleanupWorkerRunIds(worker: Worker) {
    if (worker.assignedRunId) this.runWorkerMap.delete(worker.assignedRunId);
    for (const task of worker.taskQueue) {
      this.runWorkerMap.delete(task.runId);
    }
  }

  findBySeatId(seatId?: string): Worker | null {
    if (!seatId) return null;
    return this.workers.find((worker) => worker.seatId === seatId) ?? null;
  }

  findIdle(): Worker | null {
    return this.workers.find((worker) => worker.status === "idle") ?? null;
  }

  updateAll() {
    for (const worker of this.workers) worker.update();
  }

  destroyAll() {
    for (const worker of this.workers) worker.destroy();
    this.workers = [];
    this.runWorkerMap.clear();
  }
}
