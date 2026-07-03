// 三房间布局：把「后端 roster（编制）」+「/api/agents 实时 agent」映射成小镇的三个房间
// （用户 / 设计师 / 开发者）与其中的座位。房间容量来自 roster（与后端一致），座位按角色填入实时
// agent，未填满的槽位留空。这是「用我们自己的数据驱动像素小镇」的唯一布局真源。
import type { Agent, AgentRole, Roster } from "../types";
import type { SeatDef } from "@/components/game/utils/MapHelpers";
import type { SeatState } from "@/types/game";

// 地图像素尺寸（office2：27×20 tile @48）。房间叠加在地图之上，不依赖底图可行走区——
// worker 不与地图碰撞体做物理碰撞（见 WorkerManager），故可自由摆放。
const MAP_W = 1296;

const BAND_TOP = 250; // 房间带上沿（留出顶部 UI/相机余量）
const BAND_H = 470; // 房间带高度
const OUTER_MARGIN = 56; // 左右外边距
const ROOM_GAP = 28; // 房间间距
const TITLE_H = 58; // 房间标题区高度（座位从其下开始排）
const SEAT_PAD_X = 26; // 座位区左右内边距
const SEAT_PAD_BOTTOM = 60; // 底部留白：给最下排座位南侧的办公桌（48px 高桌面）留出空间

// 工位网格间距：按房间尺寸铺满工位（比容量多的留空），办公室不显得空旷。
const DESK_PITCH_X = 116; // 一列工位（96px 桌面 + 间隙）所需宽度
const DESK_PITCH_Y = 150; // 一行工位（小人 + 桌面 + 间隙）所需高度
const DESK_MAX_COLS = 4;
const DESK_MAX_ROWS = 3;

export type Room = "user" | "designer" | "developer";

const ROOMS: Room[] = ["user", "designer", "developer"];

export const ROOM_META: Record<Room, { title: string; color: number; sprite: string }> = {
  // color 为房间地面色调（Phaser 十六进制）；sprite 为该角色小人贴图 key（须在 WORKER_SPRITES 内）。
  user: { title: "用户", color: 0x3b82f6, sprite: "character_02" },
  designer: { title: "设计师", color: 0xa855f7, sprite: "character_06" },
  developer: { title: "开发者", color: 0xf59e0b, sprite: "character_04" },
};

// 小人头顶角色徽标：中文角色名 + CSS 颜色（与 ROOM_META.color 同色系，供 Phaser Text 用）。
export const ROLE_TAG: Record<Room, { text: string; css: string }> = {
  user: { text: "用户", css: "#60a5fa" },
  designer: { text: "设计师", css: "#c084fc" },
  developer: { text: "开发者", css: "#fbbf24" },
};

export interface RoomDef {
  room: Room;
  title: string;
  color: number;
  capacity: number;
  filled: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 房间标题栏文案：如「开发者 (2/3)」。 */
export function roomHeadline(def: RoomDef): string {
  return `${def.title} (${def.filled}/${def.capacity})`;
}

// ── 实体墙 + 门几何（B 档）──────────────────────────────────
// 每个房间四面实体墙围合，底墙居中留一道门（缺口）。墙既用于绘制，也用于生成物理碰撞体，
// 让 boss（玩家）无法穿墙、只能从门进出，达成「严格分房间」。门朝下：boss 出生在房间带下方。
export const WALL_THICK = 12; // 墙帽厚（像素）——顶视角下墙的「顶面」
export const WALL_FACE_H = 48; // 顶墙内侧白墙面高度（agent-town/LimeZu 风格：墙帽下露一段墙面）
export const DOOR_W = 76; // 门洞宽（像素）

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface RoomWalls {
  /** 四面墙的实心段（底墙被门洞切成左右两段）——墙帽绘制与碰撞共用（顶墙含墙面高度）。 */
  walls: Rect[];
  /** 顶墙内侧白墙面（视觉层，含在顶墙碰撞体内）——挂牌/黑板等挂墙物挂在这上面。 */
  face: Rect;
  /** 门洞（底墙缺口）——绘制门槛用，无碰撞。 */
  door: Rect;
}

/** 由房间矩形算出四面墙段 + 顶墙白墙面 + 底墙居中门洞。 */
export function roomWalls(def: RoomDef): RoomWalls {
  const t = WALL_THICK;
  const { x, y, w, h } = def;
  const doorX = x + (w - DOOR_W) / 2;
  const walls: Rect[] = [
    { x, y, w, h: t + WALL_FACE_H }, // 顶墙（帽 + 白墙面，一体碰撞：小人不可站上墙面）
    { x, y, w: t, h }, // 左墙
    { x: x + w - t, y, w: t, h }, // 右墙
    { x, y: y + h - t, w: (w - DOOR_W) / 2, h: t }, // 底墙·左段
    { x: doorX + DOOR_W, y: y + h - t, w: (w - DOOR_W) / 2, h: t }, // 底墙·右段
  ];
  return {
    walls,
    face: { x: x + t, y: y + t, w: w - t * 2, h: WALL_FACE_H },
    door: { x: doorX, y: y + h - t, w: DOOR_W, h: t },
  };
}

/** 按 roster 权重把房间带横向切成三块矩形（宽度∝容量，至少占 1 份）。 */
function roomRects(roster: Roster): Record<Room, { x: number; w: number }> {
  const weights: Record<Room, number> = {
    user: Math.max(1, roster.user),
    designer: Math.max(1, roster.designer),
    developer: Math.max(1, roster.developer),
  };
  const totalWeight = weights.user + weights.designer + weights.developer;
  const usable = MAP_W - OUTER_MARGIN * 2 - ROOM_GAP * (ROOMS.length - 1);
  const rects = {} as Record<Room, { x: number; w: number }>;
  let cursor = OUTER_MARGIN;
  for (const room of ROOMS) {
    const w = (usable * weights[room]) / totalWeight;
    rects[room] = { x: cursor, w };
    cursor += w + ROOM_GAP;
  }
  return rects;
}

/** 按房间尺寸铺工位网格（至少放得下 minSlots 个），行优先返回全部工位坐标。 */
function deskGrid(rect: RoomDef, minSlots: number): { x: number; y: number }[] {
  const innerX = rect.x + SEAT_PAD_X;
  const innerW = rect.w - SEAT_PAD_X * 2;
  const innerY = rect.y + TITLE_H;
  const innerH = rect.h - TITLE_H - SEAT_PAD_BOTTOM;
  let cols = Math.max(1, Math.min(DESK_MAX_COLS, Math.floor(innerW / DESK_PITCH_X)));
  let rows = Math.max(1, Math.min(DESK_MAX_ROWS, Math.floor(innerH / DESK_PITCH_Y)));
  // 容量超出网格时扩列/扩行兜底（退化为按容量均分，间距变密）。
  while (cols * rows < minSlots) {
    if (cols <= rows) cols += 1;
    else rows += 1;
  }
  const out: { x: number; y: number }[] = [];
  for (let i = 0; i < cols * rows; i++) {
    const c = i % cols;
    const r = Math.floor(i / cols);
    const x = innerX + innerW * ((c + 0.5) / cols);
    const y = innerY + innerH * ((r + 0.5) / rows);
    out.push({ x, y });
  }
  return out;
}

/** 无人坐的空工位（桌子+椅子照摆，人来即坐）。 */
export interface DeskSpot {
  room: Room;
  x: number;
  y: number;
}

export interface LayoutResult {
  rooms: RoomDef[];
  seatDefs: SeatDef[];
  seats: SeatState[];
  /** 容量之外的空工位（仅绘制家具，不参与座位分配）。 */
  extraDesks: DeskSpot[];
  /** seatId -> agent（点击小人查回是哪个 agent）。 */
  seatAgents: Map<string, Agent>;
}

function agentsByRole(agents: Agent[], role: AgentRole): Agent[] {
  return agents.filter((a) => a.role === role);
}

/** 气泡文案：最新一条非空对话（harness 回复加 🤖 前缀区分说话方），无对话则退到 status。 */
function latestMessage(agent: Agent): string | undefined {
  for (let i = agent.turns.length - 1; i >= 0; i--) {
    const turn = agent.turns[i];
    const content = turn?.content?.trim();
    if (content) return turn.role === "harness" ? `🤖 ${content}` : content;
  }
  return agent.status?.trim() || undefined;
}

/** roster + agents → 三房间 + 座位 + 座位/agent 绑定。座位数=房间容量，按角色顺序填入实时 agent。 */
export function computeLayout(roster: Roster, agents: Agent[]): LayoutResult {
  const rects = roomRects(roster);
  const rooms: RoomDef[] = [];
  const seatDefs: SeatDef[] = [];
  const seats: SeatState[] = [];
  const extraDesks: DeskSpot[] = [];
  const seatAgents = new Map<string, Agent>();

  let seatIndex = 0;
  for (const room of ROOMS) {
    const capacity = roster[room];
    const roleAgents = agentsByRole(agents, room);
    const meta = ROOM_META[room];
    const def: RoomDef = {
      room,
      title: meta.title,
      color: meta.color,
      capacity,
      filled: Math.min(capacity, roleAgents.length),
      x: rects[room].x,
      y: BAND_TOP,
      w: rects[room].w,
      h: BAND_H,
    };
    rooms.push(def);

    // 工位网格铺满房间：前 capacity 个是座位（行优先，先坐前排），其余留作空工位。
    const positions = deskGrid(def, capacity);
    for (const pos of positions.slice(capacity)) {
      extraDesks.push({ room, x: pos.x, y: pos.y });
    }
    for (let i = 0; i < capacity; i++) {
      const seatId = `${room}-${i}`;
      const pos = positions[i];
      seatDefs.push({ seatId, x: pos.x, y: pos.y, facing: "down", index: seatIndex++ });

      const agent = roleAgents[i];
      if (agent) {
        seatAgents.set(seatId, agent);
        seats.push({
          seatId,
          label: agent.label,
          seatType: "agent",
          roleTitle: room,
          assigned: true,
          spriteKey: meta.sprite,
          status: agent.running ? "running" : "done",
          latestMessage: latestMessage(agent),
        });
      } else {
        // 空槽：不派小人，仅由房间标题的 filled/capacity 体现。
        seats.push({ seatId, label: "", seatType: "agent", status: "empty" });
      }
    }
  }

  return { rooms, seatDefs, seats, extraDesks, seatAgents };
}
