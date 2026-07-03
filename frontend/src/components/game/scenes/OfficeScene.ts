import * as Phaser from "phaser";
import { Player } from "../entities/Player";
import { resetWanderClock } from "../entities/Worker";
import { SPRITE_KEY, SPRITE_PATH, WORKER_SPRITES } from "../config/animations";
import { EMOTE_SHEET_KEY, EMOTE_SHEET_PATH, EMOTE_FRAME_SIZE } from "../config/emotes";
import { Pathfinder } from "../utils/Pathfinder";
import { buildSpriteFrames, parseSpawns } from "../utils/MapHelpers";
import { gameEvents } from "@/lib/events";
import { roomHeadline, roomWalls, type RoomDef } from "@/lib/roomLayout";
import {
  BOSS_INTERACT_DISTANCE,
  PF_PADDING,
  PRESS_E_STYLE,
  BOSS_PROMPT_OFFSET_X,
  BOSS_PROMPT_OFFSET_Y,
} from "@/lib/constants";

import { CameraController } from "../systems/CameraController";
import { WorkerManager } from "../systems/WorkerManager";
import { InteractionManager } from "../systems/InteractionManager";
import { initSceneEventBridge } from "../systems/SceneEventBridge";

function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || (el as HTMLElement).isContentEditable;
}

export class OfficeScene extends Phaser.Scene {
  private player!: Player;
  private terminalZone: { x: number; y: number } | null = null;
  private promptText: Phaser.GameObjects.Text | null = null;
  private eKey!: Phaser.Input.Keyboard.Key;
  private terminalOpen = false;

  /** sessionKey -> seatId: when a character executes a task, that session binds to the character */
  private sessionBindings = new Map<string, string>();

  private cameraController!: CameraController;
  private workerManager!: WorkerManager;
  private interactionManager!: InteractionManager;
  private cleanupEventBridge: (() => void) | null = null;
  private roomObjects: Phaser.GameObjects.GameObject[] = [];
  private roomWallGroup!: Phaser.Physics.Arcade.StaticGroup;
  private offRoomsUpdated: (() => void) | null = null;

  constructor() {
    super({ key: "OfficeScene" });
  }

  preload() {
    // 地图 JSON 只用于取 boss 出生点与地图尺寸；瓦片图层不再渲染（场景改为自绘三房间）。
    this.load.tilemapTiledJSON("office", "/maps/office2.json");

    this.load.image(SPRITE_KEY, SPRITE_PATH);

    for (const ws of WORKER_SPRITES) {
      this.load.image(ws.key, ws.path);
    }

    this.load.spritesheet(EMOTE_SHEET_KEY, EMOTE_SHEET_PATH, {
      frameWidth: EMOTE_FRAME_SIZE,
      frameHeight: EMOTE_FRAME_SIZE,
    });

    this.load.spritesheet("boss-arrow", "/sprites/arrow_down_48x48.png", {
      frameWidth: 48,
      frameHeight: 48,
    });
  }

  create() {
    buildSpriteFrames(this, SPRITE_KEY);
    for (const ws of WORKER_SPRITES) {
      buildSpriteFrames(this, ws.key);
    }

    // 地图仅提供尺寸与 boss 出生点；瓦片图层（原 4 房间办公室）不再渲染，场景改为自绘三房间。
    const map = this.make.tilemap({ key: "office" });

    this.drawBuildingFloor(map.widthInPixels);

    // 无瓦片碰撞：可行走性只由三房间实体墙约束（见 drawRooms）。
    const pathfinder = new Pathfinder(map.widthInPixels, map.heightInPixels, [], PF_PADDING);

    const { bossSpawn } = parseSpawns(map);

    this.player = new Player(this, bossSpawn.x, bossSpawn.y, bossSpawn.facing);

    // 三房间实体墙：碰撞体在 rooms-updated 时按房间矩形重建，玩家撞墙、只能走门。
    this.roomWallGroup = this.physics.add.staticGroup();
    this.physics.add.collider(this.player.sprite, this.roomWallGroup);

    this.physics.world.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    this.player.sprite.setCollideWorldBounds(true);

    this.input.keyboard?.disableGlobalCapture();

    // ── Systems ───────────────────────────────────────────
    this.cameraController = new CameraController(
      this,
      this.player.sprite,
      map.widthInPixels,
      map.heightInPixels,
    );
    this.cameraController.init();

    // 座位由 App 依 roster/agents 计算的三房间布局注入（rooms-updated），初始为空；
    // pois 传空 → 小人只在各自房间原地做 idle 动作，不跨图游走（保持「房间」隔离感）。
    this.workerManager = new WorkerManager(this, [], [], pathfinder);

    this.interactionManager = new InteractionManager(
      this,
      this.player,
      this.workerManager,
      this.cameraController,
    );
    this.interactionManager.initInteractionUI();

    resetWanderClock();
    this.initBossSeat(bossSpawn);

    this.cleanupEventBridge = initSceneEventBridge(
      this.workerManager,
      this.interactionManager,
      this.sessionBindings,
      (open) => {
        this.terminalOpen = open;
      },
    );

    // 三房间布局更新：重绘房间叠加层 + 替换座位定义 + 增删小人。App 在场景就绪后按 roster/agents 推送。
    this.offRoomsUpdated = gameEvents.on("rooms-updated", (rooms, seatDefs, seats) => {
      this.drawRooms(rooms);
      this.workerManager.setSeatDefs(seatDefs);
      this.workerManager.syncWorkers(seats, (w) => this.interactionManager.clearIfNearest(w));
    });

    gameEvents.emit("scene-ready");

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.cleanup());
    this.events.once(Phaser.Scenes.Events.DESTROY, () => this.cleanup());
  }

  // ── 自绘三房间（地板 + 实体墙 + 门 + 职能立牌）───────────

  // 深度：地板(0) < 房间地板(1) < 门槛(2) < 墙(4) < 角色(5) < 立牌(6)。
  // 墙低于角色，角色贴墙时始终可见；立牌立在房间上部空档（座位区之上），不与小人重叠。
  private static readonly SLAB_DEPTH = 0;
  private static readonly FLOOR_DEPTH = 1;
  private static readonly DOOR_DEPTH = 2;
  private static readonly WALL_DEPTH = 4;
  private static readonly SIGN_DEPTH = 6;
  private static readonly WALL_FILL = 0x2b3448; // 墙体主色（深板岩）
  private static readonly WALL_TOP = 0x475569; // 墙顶高光
  private static readonly ROOM_FLOOR = 0xd6c49a; // 房间木地板
  private static readonly SLAB_FLOOR = 0xb9a67e; // 楼层底板（房间外走廊，色略深）
  private static readonly GRID = 0x8a7a58; // 地板网格线
  private static readonly SIGN_BOARD = 0x8a5f36; // 牌面木色
  private static readonly SIGN_EDGE = 0x4e3319; // 牌子描边/柱脚
  private static readonly SIGN_POST = 0x6b4a2c; // 立柱

  /** 楼层底板：覆盖房间带与下方走廊（boss 活动区），带 48px 瓦片网格。仅绘制一次。 */
  private drawBuildingFloor(mapW: number) {
    const x = 24;
    const y = 220;
    const w = mapW - 48;
    const h = 640; // 覆盖房间带（250~720）+ 底部走廊（boss 出生于 y≈753）
    const g = this.add.graphics().setDepth(OfficeScene.SLAB_DEPTH);
    g.fillStyle(OfficeScene.SLAB_FLOOR, 1);
    g.fillRect(x, y, w, h);
    g.lineStyle(1, OfficeScene.GRID, 0.18);
    for (let gx = x; gx <= x + w; gx += 48) g.lineBetween(gx, y, gx, y + h);
    for (let gy = y; gy <= y + h; gy += 48) g.lineBetween(x, gy, x + w, gy);
    g.lineStyle(3, OfficeScene.SIGN_EDGE, 0.35);
    g.strokeRect(x, y, w, h);
  }

  /** 重绘三房间：木地板 + 四面实体墙（底墙留门）+ 门槛 + 职能立牌，并重建墙碰撞体。 */
  private drawRooms(rooms: RoomDef[]) {
    for (const obj of this.roomObjects) obj.destroy();
    this.roomObjects = [];
    // 清空并重建墙碰撞体（房间尺寸随 roster 变化）。
    this.roomWallGroup.clear(true, true);

    for (const room of rooms) {
      // 房间木地板（统一米色 + 瓦片网格），不再用彩色覆盖框。
      const g = this.add.graphics().setDepth(OfficeScene.FLOOR_DEPTH);
      g.fillStyle(OfficeScene.ROOM_FLOOR, 1);
      g.fillRect(room.x, room.y, room.w, room.h);
      g.lineStyle(1, OfficeScene.GRID, 0.22);
      for (let gx = room.x + 48; gx < room.x + room.w; gx += 48) {
        g.lineBetween(gx, room.y, gx, room.y + room.h);
      }
      for (let gy = room.y + 48; gy < room.y + room.h; gy += 48) {
        g.lineBetween(room.x, gy, room.x + room.w, gy);
      }
      this.roomObjects.push(g);

      // 四面实体墙（底墙被门洞切成两段）：矩形即视觉 + 物理体。
      const { walls, door } = roomWalls(room);
      for (const wr of walls) {
        const wall = this.add
          .rectangle(wr.x + wr.w / 2, wr.y + wr.h / 2, wr.w, wr.h, OfficeScene.WALL_FILL, 1)
          .setDepth(OfficeScene.WALL_DEPTH);
        wall.setStrokeStyle(2, OfficeScene.WALL_TOP, 1);
        this.physics.add.existing(wall, true);
        this.roomWallGroup.add(wall);
        this.roomObjects.push(wall);
      }

      // 门槛（门洞地面，房间色高亮，无碰撞）——标示可通行入口。
      const sill = this.add
        .rectangle(door.x + door.w / 2, door.y + door.h / 2, door.w, door.h + 4, room.color, 0.55)
        .setDepth(OfficeScene.DOOR_DEPTH);
      this.roomObjects.push(sill);

      this.drawSign(room);
    }
  }

  /** 房间职能立牌：木牌 + 立柱，牌面写角色名与在岗数（如「用户 (2/3)」），顶部镶房间色条。 */
  private drawSign(room: RoomDef) {
    const cx = room.x + room.w / 2;
    const boardCy = room.y + 44; // 牌面中心（房间上部空档，座位区从 y+58 起）

    const text = this.add
      .text(cx, boardCy, roomHeadline(room), {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: "12px",
        color: "#fdf6e3",
        align: "center",
      })
      .setOrigin(0.5)
      .setDepth(OfficeScene.SIGN_DEPTH + 1)
      .setResolution(window.devicePixelRatio * 2);

    const bw = Math.ceil(text.width) + 28;
    const bh = 32;

    const g = this.add.graphics().setDepth(OfficeScene.SIGN_DEPTH);
    // 立柱（牌面下方两条腿）
    g.fillStyle(OfficeScene.SIGN_POST, 1);
    g.fillRect(cx - bw / 2 + 8, boardCy + bh / 2 - 2, 8, 22);
    g.fillRect(cx + bw / 2 - 16, boardCy + bh / 2 - 2, 8, 22);
    // 牌面
    g.fillStyle(OfficeScene.SIGN_BOARD, 1);
    g.fillRect(cx - bw / 2, boardCy - bh / 2, bw, bh);
    g.lineStyle(2, OfficeScene.SIGN_EDGE, 1);
    g.strokeRect(cx - bw / 2, boardCy - bh / 2, bw, bh);
    // 顶部房间色条（职能配色）
    g.fillStyle(room.color, 1);
    g.fillRect(cx - bw / 2, boardCy - bh / 2, bw, 4);

    this.roomObjects.push(g, text);
  }

  // ── Boss seat ──────────────────────────────────────────

  private initBossSeat(bossSpawn: { x: number; y: number }) {
    this.terminalZone = { x: bossSpawn.x, y: bossSpawn.y };

    this.promptText = this.add
      .text(
        bossSpawn.x + BOSS_PROMPT_OFFSET_X,
        bossSpawn.y - BOSS_PROMPT_OFFSET_Y,
        "Press E",
        PRESS_E_STYLE as Phaser.Types.GameObjects.Text.TextStyle,
      )
      .setResolution(window.devicePixelRatio * 2)
      .setOrigin(0, 0)
      .setDepth(20)
      .setVisible(false);
    this.promptText.texture.setFilter(Phaser.Textures.FilterMode.LINEAR);

    const kb = this.input.keyboard;
    if (!kb) return;
    this.eKey = kb.addKey(Phaser.Input.Keyboard.KeyCodes.E, false);
  }

  // ── Cleanup ────────────────────────────────────────────

  private cleanup() {
    this.cleanupEventBridge?.();
    this.cleanupEventBridge = null;
    this.offRoomsUpdated?.();
    this.offRoomsUpdated = null;

    for (const obj of this.roomObjects) obj.destroy();
    this.roomObjects = [];
    this.roomWallGroup?.clear(true, true);

    this.workerManager?.destroyAll();
    this.interactionManager?.destroy();
  }

  // ── Update ─────────────────────────────────────────────

  update() {
    if (this.interactionManager.interactionMenu.visible) {
      this.interactionManager.interactionMenu.update();
      this.workerManager.updateAll();
      return;
    }

    if (this.terminalOpen || isInputFocused()) {
      this.workerManager.updateAll();
      return;
    }

    this.player.update();
    if (!this.cameraController.cameraFollowing && this.player.isMoving()) {
      this.cameraController.resumeCameraFollow();
    }
    this.workerManager.updateAll();

    // Worker proximity + E-key interaction
    if (this.interactionManager.updateProximity(this.eKey)) {
      return;
    }

    // Boss terminal interaction (only when no worker is nearby)
    if (!this.interactionManager.nearestWorker && this.terminalZone && this.promptText) {
      const dist = Phaser.Math.Distance.Between(
        this.player.sprite.x,
        this.player.sprite.y,
        this.terminalZone.x,
        this.terminalZone.y,
      );
      const near = dist < BOSS_INTERACT_DISTANCE;
      this.promptText.setVisible(near);

      if (near && Phaser.Input.Keyboard.JustDown(this.eKey)) {
        this.terminalOpen = true;
        this.promptText.setVisible(false);
        gameEvents.emit("open-terminal");
      }
    } else if (this.promptText) {
      this.promptText.setVisible(false);
    }
  }
}
