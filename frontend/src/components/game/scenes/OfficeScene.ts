import * as Phaser from "phaser";
import { Player } from "../entities/Player";
import { resetWanderClock } from "../entities/Worker";
import { SPRITE_KEY, SPRITE_PATH, WORKER_SPRITES } from "../config/animations";
import { EMOTE_SHEET_KEY, EMOTE_SHEET_PATH, EMOTE_FRAME_SIZE } from "../config/emotes";
import { Pathfinder } from "../utils/Pathfinder";
import { buildSpriteFrames, parseSpawns, type SeatDef } from "../utils/MapHelpers";
import { gameEvents } from "@/lib/events";
import {
  WALL_THICK,
  roomHeadline,
  roomWalls,
  type DeskSpot,
  type Room,
  type RoomDef,
} from "@/lib/roomLayout";
import type { SeatState } from "@/types/game";
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
  private propGroup!: Phaser.Physics.Arcade.StaticGroup; // 走廊道具碰撞体（一次性，不随 roster 重建）
  private offRoomsUpdated: (() => void) | null = null;

  constructor() {
    super({ key: "OfficeScene" });
  }

  preload() {
    // 地图 JSON 只用于取 boss 出生点与地图尺寸；瓦片图层不再渲染（场景改为自绘三房间）。
    this.load.tilemapTiledJSON("office", "/maps/office2.json");

    // 办公家具贴图（桌子/电脑/绿植等按 48px tile 索引切帧，见 tileImg）。
    this.load.image("office-tiles", "/tilesets/Modern_Office_48x48.png");
    // 地板贴图（agent-town 同款 Room_Builder 地砖/木条地板）+ 教室贴图（黑板/地球仪/软木板）。
    this.load.image("room-tiles", "/tilesets/Room_Builder_Office_48x48.png");
    this.load.image("class-tiles", "/tilesets/5_Classroom_and_library_48x48.png");

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

    this.propGroup = this.physics.add.staticGroup();
    this.drawBuildingFloor(map.widthInPixels);

    // 无瓦片碰撞：可行走性只由三房间实体墙约束（见 drawRooms）。
    const pathfinder = new Pathfinder(map.widthInPixels, map.heightInPixels, [], PF_PADDING);

    const { bossSpawn } = parseSpawns(map);

    this.player = new Player(this, bossSpawn.x, bossSpawn.y, bossSpawn.facing);

    // 三房间实体墙：碰撞体在 rooms-updated 时按房间矩形重建，玩家撞墙、只能走门。
    this.roomWallGroup = this.physics.add.staticGroup();
    this.physics.add.collider(this.player.sprite, this.roomWallGroup);
    this.physics.add.collider(this.player.sprite, this.propGroup);

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
    this.offRoomsUpdated = gameEvents.on("rooms-updated", (rooms, seatDefs, seats, extraDesks) => {
      this.drawRooms(rooms, seatDefs, seats, extraDesks);
      this.workerManager.setSeatDefs(seatDefs);
      this.workerManager.syncWorkers(seats, (w) => this.interactionManager.clearIfNearest(w));
    });

    gameEvents.emit("scene-ready");

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.cleanup());
    this.events.once(Phaser.Scenes.Events.DESTROY, () => this.cleanup());
  }

  // ── 自绘三房间（瓦片地板 + 白墙深蓝墙帽 + 门 + 挂墙铭牌/装饰 + 工位/道具）──────
  // 视觉参考 agent-town（LimeZu Modern Interiors）：白墙面 + 深蓝墙帽 + Room_Builder 地砖。

  // 深度：走廊地板(0) < 房间地板(1) < 门槛(2) < 墙/墙面/挂墙物/立式黑板(4) < 角色·空位椅(5)
  //       < 家具/道具(6)。墙低于角色，角色贴墙时始终可见；同深度按创建顺序叠放。
  private static readonly SLAB_DEPTH = 0;
  private static readonly FLOOR_DEPTH = 1;
  private static readonly DOOR_DEPTH = 2;
  private static readonly WALL_DEPTH = 4;
  private static readonly CHAR_DEPTH = 5; // 与 Worker/Player 的 setDepth(5) 一致
  private static readonly WALL_CAP = 0x3a3a50; // 墙帽深蓝（取自 Room_Builder tile 8）
  private static readonly WALL_CAP_EDGE = 0x2a2a3c; // 墙帽描边
  private static readonly WALL_FACE = 0xf8f8f8; // 顶墙内侧白墙面（取自 Room_Builder 墙面 tile）
  private static readonly WALL_FACE_SHADE = 0xc9c9d4; // 墙面落地阴影线

  // Room_Builder_Office_48x48 地板 tile（16 列，id = row*16+col；经贴图目检确认）。
  private static readonly FLOOR_TILES: Record<Room, number> = {
    user: 107, // 素灰
    designer: 193, // 淡紫拼花（呼应设计师紫色系）
    developer: 141, // 橄榄细格
  };
  private static readonly CORRIDOR_TILE = 110; // 走廊浅色木条地板

  /** 楼层底板：木条地砖铺满房间带与下方走廊（boss 活动区），加走廊固定道具。仅绘制一次。 */
  private drawBuildingFloor(mapW: number) {
    const x = 24;
    const y = 220;
    const w = mapW - 48;
    const h = 640; // 覆盖房间带（250~720）+ 底部走廊（boss 出生于 y≈753）
    const frame = this.ensureFrame("room-tiles", OfficeScene.CORRIDOR_TILE);
    this.add
      .tileSprite(x + w / 2, y + h / 2, w, h, "room-tiles", frame)
      .setDepth(OfficeScene.SLAB_DEPTH);
    const g = this.add.graphics().setDepth(OfficeScene.SLAB_DEPTH);
    g.lineStyle(4, OfficeScene.WALL_CAP_EDGE, 0.5);
    g.strokeRect(x, y, w, h);
    this.drawCorridorProps();
  }

  // Modern_Office_48x48 内的家具 tile 索引（16 列；经贴图目检确认）。
  private static readonly TILESET_COLS = 16;
  private static readonly TILE = 48;
  private static readonly DESK_TOP: [number, number] = [504, 505]; // 木纹桌面（左/右）
  private static readonly MONITOR = 588; // 蓝屏显示器
  private static readonly CHAIR_GRAY: [number, number] = [129, 145]; // 办公椅背视（上/下）
  private static readonly CHAIR_ORANGE: [number, number] = [161, 177];
  private static readonly PLANTS: [number, number][] = [
    // [叶, 盆]：竖向两 tile 的盆栽，三种样式轮换
    [134, 150],
    [166, 182],
    [214, 230],
  ];
  private static readonly FURNITURE_DEPTH = 6; // 家具盖在墙(4)/角色(5)之上；名牌(20)不受影响

  /** 确保贴图 key 中第 lid 块 tile 的切帧存在，返回帧名。 */
  private ensureFrame(key: string, lid: number): string {
    const frame = `t${lid}`;
    const tex = this.textures.get(key);
    if (!tex.has(frame)) {
      const T = OfficeScene.TILE;
      const sx = (lid % OfficeScene.TILESET_COLS) * T;
      const sy = Math.floor(lid / OfficeScene.TILESET_COLS) * T;
      tex.add(frame, 0, sx, sy, T, T);
    }
    return frame;
  }

  /** 单块 tile 的 image（不入重绘清理列表，调用方自行决定是否 track）。 */
  private tileImg(key: string, lid: number, x: number, y: number, depth: number) {
    return this.add.image(x, y, key, this.ensureFrame(key, lid)).setDepth(depth);
  }

  /** 铺一个多 tile 道具块（x,y 为左上角 tile 的中心）；track 时纳入房间重绘清理。 */
  private drawTileBlock(
    key: string,
    rows: number[][],
    x: number,
    y: number,
    depth: number,
    track: boolean,
  ) {
    rows.forEach((row, r) =>
      row.forEach((lid, c) => {
        const img = this.tileImg(key, lid, x + c * 48, y + r * 48, depth);
        if (track) this.roomObjects.push(img);
      }),
    );
  }

  /** 走廊固定道具：沙发/绿植/饮水机/复印机/地球仪/售货机，带静态碰撞体（boss 不可穿过）。 */
  private drawCorridorProps() {
    const D = OfficeScene.FURNITURE_DEPTH;
    const top = 776; // 道具首行 tile 中心（走廊带 720~860 的下半，避开房门通道）
    const place = (key: string, rows: number[][], x: number) => {
      this.drawTileBlock(key, rows, x, top, D, false);
      const w = rows[0].length * 48;
      const h = rows.length * 48;
      const body = this.add.rectangle(x - 24 + w / 2, top - 24 + h / 2, w, h, 0, 0);
      this.physics.add.existing(body, true);
      this.propGroup.add(body);
    };
    place("office-tiles", [[272, 273, 274], [288, 289, 290]], 126); // 休息区沙发
    place("office-tiles", [[134], [150]], 262); // 绿植
    place("office-tiles", [[268], [284]], 358); // 饮水机
    place("office-tiles", [[362], [378]], 442); // 复印机
    place("class-tiles", [[30], [46]], 526); // 地球仪
    place("office-tiles", [[386, 387], [402, 403]], 1108); // 自动售货机
    place("office-tiles", [[214], [230]], 1222); // 绿植
  }

  /** 工位：两块桌面 tile + 显示器；空工位（无人坐）再摆一把办公椅占位。 */
  private drawWorkstation(x: number, y: number, room: Room, withChair: boolean) {
    const D = OfficeScene.FURNITURE_DEPTH;
    const yTop = y + 72; // 桌面行中心：紧贴小人脚下往南一格（小人帧高 96，脚在 y+48）
    this.roomObjects.push(
      this.tileImg("office-tiles", OfficeScene.DESK_TOP[0], x - 24, yTop, D),
      this.tileImg("office-tiles", OfficeScene.DESK_TOP[1], x + 24, yTop, D),
      // 显示器立在桌面上，只压小人腿部（工位朝下的经典画法）
      this.tileImg("office-tiles", OfficeScene.MONITOR, x, yTop - 12, D + 1),
    );
    if (withChair) {
      // 椅子占小人位（同层 5）——有人时不画椅，二者互斥不会重叠。
      const [chairTop, chairBottom] =
        room === "developer" ? OfficeScene.CHAIR_ORANGE : OfficeScene.CHAIR_GRAY;
      this.roomObjects.push(
        this.tileImg("office-tiles", chairTop, x, y - 24, OfficeScene.CHAR_DEPTH),
        this.tileImg("office-tiles", chairBottom, x, y + 24, OfficeScene.CHAR_DEPTH),
      );
    }
  }

  /** 房间绿植：宽房间摆底部两角（避开中央门洞），窄房间只在右上角放一盆。 */
  private drawPlants(room: RoomDef, index: number) {
    const spots: { x: number; y: number }[] =
      room.w > 320
        ? [
            { x: room.x + 40, y: room.y + room.h - 44 },
            { x: room.x + room.w - 40, y: room.y + room.h - 44 },
          ]
        : [{ x: room.x + room.w - 40, y: room.y + 108 }];
    for (let i = 0; i < spots.length; i++) {
      const [leaf, pot] = OfficeScene.PLANTS[(index + i) % OfficeScene.PLANTS.length];
      const s = spots[i];
      this.roomObjects.push(
        this.tileImg("office-tiles", pot, s.x, s.y, OfficeScene.FURNITURE_DEPTH),
        this.tileImg("office-tiles", leaf, s.x, s.y - 48, OfficeScene.FURNITURE_DEPTH),
      );
    }
  }

  /** 挂墙装饰：按职能从房间右缘往左排（照片/证书/便签板/白板），避让中央铭牌，窄房间自动不挂。 */
  private drawWallHangings(room: RoomDef) {
    const cy = room.y + WALL_THICK + 24; // 白墙面行中心
    const cx = room.x + room.w / 2;
    const plaqueHalf = 90; // 铭牌避让半宽（含余量）
    const items: Record<Room, { key: string; tiles: number[] }[]> = {
      user: [
        { key: "office-tiles", tiles: [197] }, // 人像照片
        { key: "office-tiles", tiles: [151] }, // 奖状证书
      ],
      designer: [
        { key: "office-tiles", tiles: [194] }, // 小幅彩画
        { key: "office-tiles", tiles: [31] }, // 便签板
      ],
      developer: [
        { key: "office-tiles", tiles: [63] }, // 软木钉板
        { key: "office-tiles", tiles: [201, 202] }, // 写满红字的白板
      ],
    };
    let cursor = room.x + room.w - 40; // 从右缘往左排
    for (const item of items[room.room]) {
      const w = item.tiles.length * 48;
      const center = cursor - w / 2;
      if (center - w / 2 < cx + plaqueHalf) break; // 排到铭牌附近就停
      this.drawTileBlock(item.key, [item.tiles], center - w / 2 + 24, cy, OfficeScene.WALL_DEPTH, true);
      cursor -= w + 10;
    }
  }

  /** 立式黑板/图表板：靠顶墙站在房间左上角，深度低于小人（人可站在板前）。 */
  private drawStandingProp(room: RoomDef) {
    if (room.w < 300) return; // 窄房间放不下
    const defs: Record<Room, { key: string; rows: number[][] }> = {
      user: { key: "office-tiles", rows: [[233, 234], [249, 250]] }, // 图表翻页架
      designer: { key: "class-tiles", rows: [[90, 91], [106, 107]] }, // 画架绿黑板
      developer: { key: "class-tiles", rows: [[93, 94], [109, 110]] }, // 木框黑板
    };
    const def = defs[room.room];
    this.drawTileBlock(def.key, def.rows, room.x + 52, room.y + 64, OfficeScene.WALL_DEPTH, true);
  }

  /** 重绘三房间：瓦片地板 + 白墙深蓝墙帽（底墙留门）+ 门槛 + 铭牌/挂饰/黑板 + 工位，并重建墙碰撞体。 */
  private drawRooms(
    rooms: RoomDef[],
    seatDefs: SeatDef[],
    seats: SeatState[],
    extraDesks: DeskSpot[],
  ) {
    for (const obj of this.roomObjects) obj.destroy();
    this.roomObjects = [];
    // 清空并重建墙碰撞体（房间尺寸随 roster 变化）。
    this.roomWallGroup.clear(true, true);

    // 编制内但暂无 agent 的座位：工位照画，并摆空椅。
    const emptySeatIds = new Set(seats.filter((s) => s.status === "empty").map((s) => s.seatId));

    for (const room of rooms) {
      // 房间地板：按职能取不同 Room_Builder 地砖纹理。
      const floorFrame = this.ensureFrame("room-tiles", OfficeScene.FLOOR_TILES[room.room]);
      const floor = this.add
        .tileSprite(room.x + room.w / 2, room.y + room.h / 2, room.w, room.h, "room-tiles", floorFrame)
        .setDepth(OfficeScene.FLOOR_DEPTH);
      this.roomObjects.push(floor);

      // 四面墙帽（底墙被门洞切成两段）：矩形即视觉 + 物理体（顶墙含白墙面高度）。
      const { walls, face, door } = roomWalls(room);
      for (const wr of walls) {
        const wall = this.add
          .rectangle(wr.x + wr.w / 2, wr.y + wr.h / 2, wr.w, wr.h, OfficeScene.WALL_CAP, 1)
          .setDepth(OfficeScene.WALL_DEPTH);
        wall.setStrokeStyle(2, OfficeScene.WALL_CAP_EDGE, 1);
        this.physics.add.existing(wall, true);
        this.roomWallGroup.add(wall);
        this.roomObjects.push(wall);
      }

      // 顶墙内侧白墙面 + 落地阴影线（盖在墙帽矩形之上，挂墙物再盖其上）。
      this.roomObjects.push(
        this.add
          .rectangle(face.x + face.w / 2, face.y + face.h / 2, face.w, face.h, OfficeScene.WALL_FACE, 1)
          .setDepth(OfficeScene.WALL_DEPTH),
        this.add
          .rectangle(face.x + face.w / 2, face.y + face.h - 2, face.w, 4, OfficeScene.WALL_FACE_SHADE, 1)
          .setDepth(OfficeScene.WALL_DEPTH),
      );

      // 门槛（门洞地面，房间色高亮，无碰撞）——标示可通行入口。
      const sill = this.add
        .rectangle(door.x + door.w / 2, door.y + door.h / 2, door.w, door.h + 4, room.color, 0.55)
        .setDepth(OfficeScene.DOOR_DEPTH);
      this.roomObjects.push(sill);

      this.drawPlaque(room);
      this.drawWallHangings(room);
      this.drawStandingProp(room);
      this.drawPlants(room, rooms.indexOf(room));

      // 工位铺满房间：座位（空缺摆椅）+ 容量之外的空工位。
      for (const seat of seatDefs) {
        if (!seat.seatId.startsWith(`${room.room}-`)) continue;
        this.drawWorkstation(seat.x, seat.y, room.room, emptySeatIds.has(seat.seatId));
      }
      for (const desk of extraDesks) {
        if (desk.room === room.room) this.drawWorkstation(desk.x, desk.y, room.room, true);
      }
    }
  }

  /** 房间铭牌：挂在顶墙白墙面正中（深蓝牌面 + 房间色条），写角色名与在岗数（如「用户 (2/3)」）。 */
  private drawPlaque(room: RoomDef) {
    const cx = room.x + room.w / 2;
    const boardCy = room.y + WALL_THICK + 24; // 白墙面行中心

    const text = this.add
      .text(cx, boardCy, roomHeadline(room), {
        fontFamily: '"Press Start 2P", monospace',
        fontSize: "12px",
        color: "#fdf6e3",
        align: "center",
      })
      .setOrigin(0.5)
      // 高于牌面（后创建的同深度 graphics 会盖住文字），墙面区无小人、不会遮挡角色。
      .setDepth(OfficeScene.CHAR_DEPTH)
      .setResolution(window.devicePixelRatio * 2);

    const bw = Math.ceil(text.width) + 28;
    const bh = 32;

    const g = this.add.graphics().setDepth(OfficeScene.WALL_DEPTH);
    g.fillStyle(OfficeScene.WALL_CAP, 1);
    g.fillRect(cx - bw / 2, boardCy - bh / 2, bw, bh);
    g.lineStyle(2, OfficeScene.WALL_CAP_EDGE, 1);
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
