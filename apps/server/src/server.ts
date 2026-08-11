import { randomBytes, randomInt, randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import Fastify, { type FastifyInstance } from "fastify";
import cors from "@fastify/cors";
import fastifyStatic from "@fastify/static";
import websocket from "@fastify/websocket";
import { z } from "zod";
import {
  applyAction,
  createInitialState,
  legalActions,
  otherPlayer,
  type GameAction,
  type GameState,
  type PlayerId,
} from "@quoridor/game-engine";

type ClientType = "HUMAN" | "BOT";
type RoomStatus = "WAITING" | "PLAYING" | "FINISHED";

type Player = {
  id: PlayerId;
  nickname: string;
  clientType: ClientType;
  token: string;
  connected: boolean;
  rematchReady: boolean;
  sockets: Set<{ send: (data: string) => void; readyState: number }>;
};

type Room = {
  code: string;
  status: RoomStatus;
  players: Player[];
  gameId: string | null;
  game: GameState | null;
  firstPlayer: PlayerId;
  turnDeadline: string | null;
  finishReason: "GOAL" | "TIMEOUT" | null;
  timer: NodeJS.Timeout | null;
};

const createRoomSchema = z.object({
  nickname: z.string().trim().min(1).max(20),
  clientType: z.enum(["HUMAN", "BOT"]).default("HUMAN"),
});
const actionSchema = z.object({
  expectedVersion: z.number().int().nonnegative(),
  action: z.discriminatedUnion("type", [
    z.object({
      type: z.literal("MOVE_PAWN"),
      to: z.object({ row: z.number().int(), col: z.number().int() }),
    }),
    z.object({
      type: z.literal("PLACE_WALL"),
      orientation: z.enum(["HORIZONTAL", "VERTICAL"]),
      row: z.number().int(),
      col: z.number().int(),
    }),
  ]),
});

const TURN_TIME_MS = Number(process.env.TURN_TIME_MS ?? 60_000);
const rooms = new Map<string, Room>();
const tokenToRoom = new Map<string, Room>();
const gameToRoom = new Map<string, Room>();
const idempotencyCache = new Map<string, unknown>();

function makeToken(): string {
  return randomBytes(32).toString("base64url");
}

function makeRoomCode(): string {
  const alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
  for (;;) {
    let code = "";
    for (let index = 0; index < 6; index += 1) code += alphabet[randomInt(alphabet.length)];
    if (!rooms.has(code)) return code;
  }
}

function publicSnapshot(room: Room, viewer?: Player) {
  const game = room.game;
  return {
    roomCode: room.code,
    status: room.status,
    gameId: room.gameId,
    me: viewer?.id ?? null,
    players: room.players.map((player) => ({
      id: player.id,
      nickname: player.nickname,
      clientType: player.clientType,
      connected: player.connected,
      rematchReady: player.rematchReady,
    })),
    game: game
      ? {
          ...game,
          turnDeadline: room.turnDeadline,
          finishReason: room.finishReason,
          legalActions: viewer && room.status === "PLAYING" && game.turn === viewer.id
            ? legalActions(game, viewer.id)
            : [],
        }
      : null,
  };
}

function playerByToken(room: Room, token: string | undefined): Player | undefined {
  return token ? room.players.find((player) => player.token === token) : undefined;
}

function bearerToken(header: string | undefined): string | undefined {
  return header?.startsWith("Bearer ") ? header.slice(7) : undefined;
}

function broadcast(room: Room): void {
  for (const player of room.players) {
    const message = JSON.stringify({ type: "room.snapshot", payload: publicSnapshot(room, player) });
    for (const socket of player.sockets) {
      if (socket.readyState === 1) socket.send(message);
    }
  }
}

function clearTurnTimer(room: Room): void {
  if (room.timer) clearTimeout(room.timer);
  room.timer = null;
}

function armTurnTimer(room: Room): void {
  clearTurnTimer(room);
  if (!room.game || room.status !== "PLAYING" || TURN_TIME_MS <= 0) {
    room.turnDeadline = null;
    return;
  }
  room.turnDeadline = new Date(Date.now() + TURN_TIME_MS).toISOString();
  const expectedVersion = room.game.version;
  room.timer = setTimeout(() => {
    if (!room.game || room.status !== "PLAYING" || room.game.version !== expectedVersion) return;
    room.game = { ...room.game, winner: otherPlayer(room.game.turn) };
    room.status = "FINISHED";
    room.finishReason = "TIMEOUT";
    room.turnDeadline = null;
    broadcast(room);
  }, TURN_TIME_MS);
  room.timer.unref();
}

function startGame(room: Room): void {
  room.gameId = randomUUID();
  room.game = createInitialState(room.firstPlayer);
  room.status = "PLAYING";
  room.finishReason = null;
  room.players.forEach((player) => { player.rematchReady = false; });
  gameToRoom.set(room.gameId, room);
  armTurnTimer(room);
  broadcast(room);
}

function addPlayer(room: Room, nickname: string, clientType: ClientType): Player {
  const player: Player = {
    id: room.players.length === 0 ? "P1" : "P2",
    nickname,
    clientType,
    token: makeToken(),
    connected: clientType === "BOT",
    rematchReady: false,
    sockets: new Set(),
  };
  room.players.push(player);
  tokenToRoom.set(player.token, room);
  return player;
}

function error(reply: { code: (status: number) => { send: (body: unknown) => unknown } }, status: number, code: string) {
  return reply.code(status).send({ error: { code } });
}

export async function buildServer(): Promise<FastifyInstance> {
  const app = Fastify({ logger: process.env.NODE_ENV !== "test" });
  await app.register(cors, { origin: true });
  await app.register(websocket);

  app.get("/health/live", async () => ({ status: "ok" }));
  app.get("/health/ready", async () => ({ status: "ready" }));

  app.post("/api/v1/rooms", async (request, reply) => {
    const parsed = createRoomSchema.safeParse(request.body);
    if (!parsed.success) return error(reply, 400, "INVALID_REQUEST");
    const room: Room = {
      code: makeRoomCode(), status: "WAITING", players: [], gameId: null, game: null,
      firstPlayer: "P1", turnDeadline: null, finishReason: null, timer: null,
    };
    rooms.set(room.code, room);
    const player = addPlayer(room, parsed.data.nickname, parsed.data.clientType);
    return reply.code(201).send({
      roomCode: room.code,
      playerToken: player.token,
      playerId: player.id,
      snapshot: publicSnapshot(room, player),
    });
  });

  app.post("/api/v1/rooms/:code/join", async (request, reply) => {
    const parsed = createRoomSchema.safeParse(request.body);
    if (!parsed.success) return error(reply, 400, "INVALID_REQUEST");
    const { code } = request.params as { code: string };
    const room = rooms.get(code.toUpperCase());
    if (!room) return error(reply, 404, "ROOM_NOT_FOUND");
    if (room.players.length >= 2) return error(reply, 409, "ROOM_FULL");
    const player = addPlayer(room, parsed.data.nickname, parsed.data.clientType);
    const response = {
      roomCode: room.code,
      playerToken: player.token,
      playerId: player.id,
      snapshot: publicSnapshot(room, player),
    };
    startGame(room);
    return reply.code(201).send(response);
  });

  app.get("/api/v1/session", async (request, reply) => {
    const token = bearerToken(request.headers.authorization);
    const room = token ? tokenToRoom.get(token) : undefined;
    const player = room ? playerByToken(room, token) : undefined;
    if (!room || !player) return error(reply, 401, "INVALID_TOKEN");
    return publicSnapshot(room, player);
  });

  app.get("/api/v1/games/:gameId/state", async (request, reply) => {
    const { gameId } = request.params as { gameId: string };
    const room = gameToRoom.get(gameId);
    const token = bearerToken(request.headers.authorization);
    const player = room ? playerByToken(room, token) : undefined;
    if (!room) return error(reply, 404, "GAME_NOT_FOUND");
    if (!player) return error(reply, 403, "NOT_YOUR_SEAT");
    return publicSnapshot(room, player);
  });

  app.post("/api/v1/games/:gameId/actions", async (request, reply) => {
    const { gameId } = request.params as { gameId: string };
    const room = gameToRoom.get(gameId);
    const token = bearerToken(request.headers.authorization);
    const player = room ? playerByToken(room, token) : undefined;
    if (!room) return error(reply, 404, "GAME_NOT_FOUND");
    if (!player) return error(reply, 403, "NOT_YOUR_SEAT");
    if (!room.game || room.status === "FINISHED") return error(reply, 409, "GAME_ALREADY_FINISHED");

    const parsed = actionSchema.safeParse(request.body);
    if (!parsed.success) return error(reply, 400, "INVALID_ACTION");
    const idempotencyKey = request.headers["idempotency-key"];
    const cacheKey = typeof idempotencyKey === "string" ? `${player.token}:${idempotencyKey}` : null;
    if (cacheKey && idempotencyCache.has(cacheKey)) return idempotencyCache.get(cacheKey);
    if (parsed.data.expectedVersion !== room.game.version) return error(reply, 409, "STALE_VERSION");

    const result = applyAction(room.game, player.id, parsed.data.action as GameAction);
    if (!result.ok) return error(reply, 409, result.reason);
    room.game = result.state;
    if (room.game.winner) {
      room.status = "FINISHED";
      room.finishReason = "GOAL";
      room.turnDeadline = null;
      clearTurnTimer(room);
    } else {
      armTurnTimer(room);
    }
    const response = { ok: true, version: room.game.version, snapshot: publicSnapshot(room, player) };
    if (cacheKey) idempotencyCache.set(cacheKey, response);
    broadcast(room);
    return response;
  });

  app.post("/api/v1/rooms/:code/rematch", async (request, reply) => {
    const { code } = request.params as { code: string };
    const room = rooms.get(code.toUpperCase());
    const token = bearerToken(request.headers.authorization);
    const player = room ? playerByToken(room, token) : undefined;
    if (!room || !player) return error(reply, 401, "INVALID_TOKEN");
    if (room.status !== "FINISHED") return error(reply, 409, "GAME_NOT_FINISHED");
    player.rematchReady = true;
    if (room.players.length === 2 && room.players.every((entry) => entry.rematchReady)) {
      room.firstPlayer = otherPlayer(room.firstPlayer);
      startGame(room);
    } else {
      broadcast(room);
    }
    return { ok: true };
  });

  app.get("/ws", { websocket: true }, (socket, request) => {
    const query = request.query as { token?: string };
    const room = query.token ? tokenToRoom.get(query.token) : undefined;
    const player = room ? playerByToken(room, query.token) : undefined;
    if (!room || !player) {
      socket.close(1008, "Invalid token");
      return;
    }
    player.sockets.add(socket);
    player.connected = true;
    socket.send(JSON.stringify({ type: "room.snapshot", payload: publicSnapshot(room, player) }));
    broadcast(room);
    socket.on("close", () => {
      player.sockets.delete(socket);
      player.connected = player.clientType === "BOT" || player.sockets.size > 0;
      broadcast(room);
    });
  });

  const webDist = join(fileURLToPath(new URL(".", import.meta.url)), "../../web/dist");
  if (existsSync(webDist)) {
    await app.register(fastifyStatic, { root: webDist });
    app.setNotFoundHandler((request, reply) => {
      if (request.raw.method === "GET" && !request.url.startsWith("/api/") && request.url !== "/ws") {
        return reply.sendFile("index.html");
      }
      return reply.code(404).send({ error: { code: "NOT_FOUND" } });
    });
  }

  return app;
}
