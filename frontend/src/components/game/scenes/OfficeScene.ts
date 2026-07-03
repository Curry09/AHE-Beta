import * as Phaser from "phaser";
import { Player } from "../entities/Player";
import { resetWanderClock } from "../entities/Worker";
import { SPRITE_KEY, SPRITE_PATH, WORKER_SPRITES } from "../config/animations";
import { EMOTE_SHEET_KEY, EMOTE_SHEET_PATH, EMOTE_FRAME_SIZE } from "../config/emotes";
import { Pathfinder } from "../utils/Pathfinder";
import {
  buildSpriteFrames,
  parseSpawns,
  parsePOIs,
  buildCollisionRects,
  renderTileObjectLayer,
  type AnimatedProp,
} from "../utils/MapHelpers";
import { gameEvents } from "@/lib/events";
import { roomHeadline, roomWalls, type RoomDef } from "@/lib/roomLayout";
import { createLogger } from "@/lib/logger";
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
import { DoorManager } from "../systems/DoorManager";
import { initSceneEventBridge } from "../systems/SceneEventBridge";

const log = createLogger("OfficeScene");

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
  private doorManager!: DoorManager;
  private cleanupEventBridge: (() => void) | null = null;
  private roomObjects: Phaser.GameObjects.GameObject[] = [];
  private roomWallGroup!: Phaser.Physics.Arcade.StaticGroup;
  private offRoomsUpdated: (() => void) | null = null;

  constructor() {
    super({ key: "OfficeScene" });
  }

  preload() {
    this.load.tilemapTiledJSON("office", "/maps/office2.json");

    this.load.once("filecomplete-tilemapJSON-office", () => {
      const cached = this.cache.tilemap.get("office");
      if (!cached?.data?.tilesets) return;
      for (const ts of cached.data.tilesets) {
        const basename = (ts.image as string).split("/").pop()!;
        this.load.image(ts.name, `/tilesets/${basename}`);
      }
    });

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

    this.load.spritesheet("anim-cauldron", "/sprites/animated_witch_cauldron_48x48.png", {
      frameWidth: 96,
      frameHeight: 96,
    });

    this.load.spritesheet("anim-door", "/sprites/animated_door_big_4_48x48.png", {
      frameWidth: 48,
      frameHeight: 144,
    });
  }

  create() {
    buildSpriteFrames(this, SPRITE_KEY);
    for (const ws of WORKER_SPRITES) {
      buildSpriteFrames(this, ws.key);
    }

    const map = this.make.tilemap({ key: "office" });

    const allTilesets: Phaser.Tilemaps.Tileset[] = [];
    for (const ts of map.tilesets) {
      const added = map.addTilesetImage(ts.name, ts.name);
      if (added) allTilesets.push(added);
    }
    if (allTilesets.length === 0) {
      log.error("No tilesets loaded");
      return;
    }

    map.createLayer("floor", allTilesets);
    map.createLayer("walls", allTilesets);
    map.createLayer("ground", allTilesets);
    map.createLayer("furniture", allTilesets);
    map.createLayer("objects", allTilesets);

    const animatedProps: AnimatedProp[] = [
      {
        tilesetName: "11_Halloween_48x48",
        anchorLocalId: 130,
        skipLocalIds: new Set([130, 131, 146, 147]),
        spriteKey: "anim-cauldron",
        frameWidth: 96,
        frameHeight: 96,
        endFrame: 11,
        frameRate: 8,
      },
    ];
    renderTileObjectLayer(this, map, "props", allTilesets, 5, animatedProps);
    renderTileObjectLayer(this, map, "props-over", allTilesets, 11);

    const overheadLayer = map.createLayer("overhead", allTilesets);
    if (overheadLayer) overheadLayer.setDepth(10);

    const collisionGroup = this.physics.add.staticGroup();
    const collisionRects = buildCollisionRects(map, collisionGroup);

    const pathfinder = new Pathfinder(
      map.widthInPixels,
      map.heightInPixels,
      collisionRects,
      PF_PADDING,
    );

    const { bossSpawn, workerSpawns } = parseSpawns(map);
    const pois = parsePOIs(map);

    this.player = new Player(this, bossSpawn.x, bossSpawn.y, bossSpawn.facing);
    this.physics.add.collider(this.player.sprite, collisionGroup);

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
    void workerSpawns;
    void pois;
    this.workerManager = new WorkerManager(this, [], [], pathfinder);

    this.interactionManager = new InteractionManager(
      this,
      this.player,
      this.workerManager,
      this.cameraController,
    );
    this.interactionManager.initInteractionUI();

    this.doorManager = new DoorManager(this, this.player, () => this.workerManager.workers);
    this.doorManager.initDoors();

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

  // ── Room overlays（实体墙 + 门）──────────────────────────

  // 墙深度低于角色（5），角色始终在墙之上；门槛更低，压在地面色块上。
  private static readonly FLOOR_DEPTH = 1;
  private static readonly DOOR_DEPTH = 2;
  private static readonly WALL_DEPTH = 4;
  private static readonly WALL_FILL = 0x2b3448; // 墙体主色（深板岩）
  private static readonly WALL_TOP = 0x475569; // 墙顶高光

  /** 重绘三房间：地面色块 + 标题栏 + 四面实体墙（底墙留门）+ 门槛，并重建墙的物理碰撞体。 */
  private drawRooms(rooms: RoomDef[]) {
    for (const obj of this.roomObjects) obj.destroy();
    this.roomObjects = [];
    // 清空并重建墙碰撞体（房间尺寸随 roster 变化）。
    this.roomWallGroup.clear(true, true);

    const TITLE_H = 40;
    for (const room of rooms) {
      const g = this.add.graphics().setDepth(OfficeScene.FLOOR_DEPTH);
      // 地面色块（房间底色）
      g.fillStyle(room.color, 0.14);
      g.fillRect(room.x, room.y, room.w, room.h);
      // 标题栏
      g.fillStyle(room.color, 0.3);
      g.fillRect(room.x, room.y, room.w, TITLE_H);
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

      const title = this.add
        .text(room.x + 14, room.y + TITLE_H / 2, roomHeadline(room), {
          fontFamily: '"Press Start 2P", monospace',
          fontSize: "12px",
          color: "#f8fafc",
          align: "left",
        })
        .setOrigin(0, 0.5)
        .setDepth(15)
        .setResolution(window.devicePixelRatio * 2);
      this.roomObjects.push(title);
    }
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
      this.doorManager.updateDoors();
      return;
    }

    this.player.update();
    if (!this.cameraController.cameraFollowing && this.player.isMoving()) {
      this.cameraController.resumeCameraFollow();
    }
    this.workerManager.updateAll();
    this.doorManager.updateDoors();

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
