import { randomBytes, randomInt, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
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
type RoomSocket = { send: (data: string) => void; readyState: number };
type FinishReason = "GOAL" | "TIMEOUT" | "FORFEIT";
type TournamentMatchStatus = "PENDING" | "READY" | "WAITING" | "PLAYING" | "FINISHED" | "BYE" | "FORFEIT";

type Player = {
  id: PlayerId;
  nickname: string;
  clientType: ClientType;
  token: string;
  connected: boolean;
  rematchReady: boolean;
  sockets: Set<RoomSocket>;
};

type Room = {
  code: string;
  status: RoomStatus;
  players: Player[];
  gameId: string | null;
  game: GameState | null;
  firstPlayer: PlayerId;
  turnDeadline: string | null;
  finishReason: FinishReason | null;
  timer: NodeJS.Timeout | null;
  spectatorSockets: Set<RoomSocket>;
  reservedPlayers: Partial<Record<PlayerId, string>> | null;
  tournamentMatch: { tournamentCode: string; matchId: string } | null;
};

type TournamentMatch = {
  id: string;
  round: number;
  slot: number;
  player1: string | null;
  player2: string | null;
  winner: string | null;
  status: TournamentMatchStatus;
  roomCode: string | null;
  finishReason: FinishReason | "BYE" | null;
};

type Tournament = {
  code: string;
  name: string;
  adminToken: string;
  participants: string[];
  rounds: TournamentMatch[][];
  status: "ACTIVE" | "FINISHED";
  winner: string | null;
  sockets: Set<RoomSocket>;
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
const createTournamentSchema = z.object({
  name: z.string().trim().min(1).max(40).default("동아리 토너먼트"),
  participants: z.array(z.string().trim().min(1).max(20)).min(2).max(32),
});
const forfeitSchema = z.object({ loser: z.string().trim().min(1).max(20) });

const TURN_TIME_MS = Number(process.env.TURN_TIME_MS ?? 60_000);
const rooms = new Map<string, Room>();
const tournaments = new Map<string, Tournament>();
const tokenToRoom = new Map<string, Room>();
const gameToRoom = new Map<string, Room>();
const idempotencyCache = new Map<string, unknown>();
let persistenceLoaded = false;

type PersistedPlayer = Omit<Player, "sockets" | "connected">;
type PersistedRoom = Omit<Room, "players" | "timer" | "spectatorSockets"> & { players: PersistedPlayer[] };
type PersistedTournament = Omit<Tournament, "sockets">;
type PersistedState = { version: 1; rooms: PersistedRoom[]; tournaments: PersistedTournament[] };

function stateFile(): string | null {
  const configured = process.env.STATE_FILE?.trim();
  if (configured) return configured;
  return process.env.NODE_ENV === "production" ? "/data/state.json" : null;
}

function persistState(): void {
  const path = stateFile();
  if (!path || !persistenceLoaded) return;
  const state: PersistedState = {
    version: 1,
    rooms: [...rooms.values()].map((room) => ({
      code: room.code,
      status: room.status,
      players: room.players.map(({ sockets: _sockets, connected: _connected, ...player }) => player),
      gameId: room.gameId,
      game: room.game,
      firstPlayer: room.firstPlayer,
      turnDeadline: room.turnDeadline,
      finishReason: room.finishReason,
      reservedPlayers: room.reservedPlayers,
      tournamentMatch: room.tournamentMatch,
    })),
    tournaments: [...tournaments.values()].map(({ sockets: _sockets, ...tournament }) => tournament),
  };
  mkdirSync(dirname(path), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.tmp`;
  writeFileSync(temporaryPath, JSON.stringify(state), { encoding: "utf8", mode: 0o600 });
  renameSync(temporaryPath, path);
}

function loadPersistedState(): void {
  if (persistenceLoaded) return;
  const path = stateFile();
  if (path && existsSync(path)) {
    const state = JSON.parse(readFileSync(path, "utf8")) as PersistedState;
    if (state.version !== 1 || !Array.isArray(state.rooms) || !Array.isArray(state.tournaments)) {
      throw new Error(`Unsupported persistent state format: ${path}`);
    }
    tournaments.clear();
    rooms.clear();
    tokenToRoom.clear();
    gameToRoom.clear();
    for (const saved of state.tournaments) {
      tournaments.set(saved.code, { ...saved, sockets: new Set() });
    }
    for (const saved of state.rooms) {
      const room: Room = {
        ...saved,
        players: saved.players.map((player) => ({
          ...player,
          connected: player.clientType === "BOT",
          sockets: new Set(),
        })),
        timer: null,
        spectatorSockets: new Set(),
      };
      rooms.set(room.code, room);
      for (const player of room.players) tokenToRoom.set(player.token, room);
      if (room.gameId) gameToRoom.set(room.gameId, room);
    }
  }
  persistenceLoaded = true;
  for (const room of rooms.values()) {
    if (room.status === "PLAYING" && room.game) armTurnTimer(room, room.turnDeadline);
  }
}

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

function makeTournamentCode(): string {
  const alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
  for (;;) {
    let code = "";
    for (let index = 0; index < 6; index += 1) code += alphabet[randomInt(alphabet.length)];
    if (!tournaments.has(code) && !rooms.has(code)) return code;
  }
}

function shuffled<T>(items: T[]): T[] {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const target = randomInt(index + 1);
    [copy[index], copy[target]] = [copy[target], copy[index]];
  }
  return copy;
}

function publicTournament(tournament: Tournament) {
  return {
    code: tournament.code,
    name: tournament.name,
    participants: tournament.participants,
    rounds: tournament.rounds,
    status: tournament.status,
    winner: tournament.winner,
  };
}

function broadcastTournament(tournament: Tournament): void {
  const message = JSON.stringify({ type: "tournament.snapshot", payload: publicTournament(tournament) });
  for (const socket of tournament.sockets) {
    if (socket.readyState === 1) socket.send(message);
  }
}

function findTournamentMatch(tournament: Tournament, matchId: string): TournamentMatch | undefined {
  return tournament.rounds.flat().find((match) => match.id === matchId);
}

function completeTournamentMatch(
  tournament: Tournament,
  match: TournamentMatch,
  winner: string,
  reason: FinishReason | "BYE",
): void {
  if (match.winner) return;
  match.winner = winner;
  match.finishReason = reason;
  match.status = reason === "BYE" ? "BYE" : reason === "FORFEIT" ? "FORFEIT" : "FINISHED";

  const nextRound = tournament.rounds[match.round + 1];
  if (!nextRound) {
    tournament.status = "FINISHED";
    tournament.winner = winner;
    persistState();
    broadcastTournament(tournament);
    return;
  }

  const nextMatch = nextRound[Math.floor(match.slot / 2)];
  if (match.slot % 2 === 0) nextMatch.player1 = winner;
  else nextMatch.player2 = winner;
  if (nextMatch.player1 && nextMatch.player2) nextMatch.status = "READY";
  persistState();
  broadcastTournament(tournament);
}

function createTournament(name: string, participants: string[]): Tournament {
  const ordered = shuffled(participants);
  let bracketSize = 2;
  while (bracketSize < ordered.length) bracketSize *= 2;
  const roundCount = Math.log2(bracketSize);
  const rounds: TournamentMatch[][] = Array.from({ length: roundCount }, (_, round) =>
    Array.from({ length: bracketSize / 2 ** (round + 1) }, (_, slot) => ({
      id: `R${round + 1}M${slot + 1}`,
      round,
      slot,
      player1: null,
      player2: null,
      winner: null,
      status: "PENDING" as TournamentMatchStatus,
      roomCode: null,
      finishReason: null,
    })),
  );

  const byeCount = bracketSize - ordered.length;
  const pairedCount = ordered.length - byeCount;
  const seeds: Array<[string | null, string | null]> = [];
  let cursor = 0;
  for (let index = 0; index < pairedCount / 2; index += 1) {
    seeds.push([ordered[cursor], ordered[cursor + 1]]);
    cursor += 2;
  }
  while (cursor < ordered.length) {
    seeds.push(randomInt(2) === 0 ? [ordered[cursor], null] : [null, ordered[cursor]]);
    cursor += 1;
  }

  shuffled(seeds).forEach(([player1, player2], slot) => {
    rounds[0][slot].player1 = player1;
    rounds[0][slot].player2 = player2;
    rounds[0][slot].status = player1 && player2 ? "READY" : "PENDING";
  });

  const tournament: Tournament = {
    code: makeTournamentCode(),
    name,
    adminToken: makeToken(),
    participants,
    rounds,
    status: "ACTIVE",
    winner: null,
    sockets: new Set(),
  };
  tournaments.set(tournament.code, tournament);
  rounds[0].forEach((match) => {
    const lonePlayer = match.player1 ?? match.player2;
    if (lonePlayer && (!match.player1 || !match.player2)) completeTournamentMatch(tournament, match, lonePlayer, "BYE");
  });
  persistState();
  return tournament;
}

function publicSnapshot(room: Room, viewer?: Player) {
  const game = room.game;
  return {
    roomCode: room.code,
    tournamentCode: room.tournamentMatch?.tournamentCode ?? null,
    status: room.status,
    gameId: room.gameId,
    me: viewer?.id ?? null,
    spectatorCount: room.spectatorSockets.size,
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
  const spectatorMessage = JSON.stringify({ type: "room.snapshot", payload: publicSnapshot(room) });
  for (const socket of room.spectatorSockets) {
    if (socket.readyState === 1) socket.send(spectatorMessage);
  }
}

function clearTurnTimer(room: Room): void {
  if (room.timer) clearTimeout(room.timer);
  room.timer = null;
}

function completeTournamentFromRoom(room: Room): void {
  if (!room.tournamentMatch || !room.game?.winner || !room.reservedPlayers || !room.finishReason) return;
  const tournament = tournaments.get(room.tournamentMatch.tournamentCode);
  const match = tournament ? findTournamentMatch(tournament, room.tournamentMatch.matchId) : undefined;
  const winner = room.reservedPlayers[room.game.winner];
  if (tournament && match && winner) completeTournamentMatch(tournament, match, winner, room.finishReason);
}

function armTurnTimer(room: Room, restoredDeadline?: string | null): void {
  clearTurnTimer(room);
  if (!room.game || room.status !== "PLAYING" || TURN_TIME_MS <= 0) {
    room.turnDeadline = null;
    return;
  }
  room.turnDeadline = restoredDeadline ?? new Date(Date.now() + TURN_TIME_MS).toISOString();
  const expectedVersion = room.game.version;
  const remainingTime = Math.max(0, new Date(room.turnDeadline).getTime() - Date.now());
  room.timer = setTimeout(() => {
    if (!room.game || room.status !== "PLAYING" || room.game.version !== expectedVersion) return;
    room.game = { ...room.game, winner: otherPlayer(room.game.turn) };
    room.status = "FINISHED";
    room.finishReason = "TIMEOUT";
    room.turnDeadline = null;
    completeTournamentFromRoom(room);
    persistState();
    broadcast(room);
  }, remainingTime);
  room.timer.unref();
}

function startGame(room: Room): void {
  room.gameId = randomUUID();
  room.game = createInitialState(room.firstPlayer);
  room.status = "PLAYING";
  room.finishReason = null;
  room.players.forEach((player) => { player.rematchReady = false; });
  gameToRoom.set(room.gameId, room);
  if (room.tournamentMatch) {
    const tournament = tournaments.get(room.tournamentMatch.tournamentCode);
    const match = tournament ? findTournamentMatch(tournament, room.tournamentMatch.matchId) : undefined;
    if (tournament && match && !match.winner) {
      match.status = "PLAYING";
      broadcastTournament(tournament);
    }
  }
  armTurnTimer(room);
  persistState();
  broadcast(room);
}

function addPlayer(room: Room, nickname: string, clientType: ClientType, reservedId?: PlayerId): Player {
  const player: Player = {
    id: reservedId ?? (room.players.some((entry) => entry.id === "P1") ? "P2" : "P1"),
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
  loadPersistedState();
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
      spectatorSockets: new Set(), reservedPlayers: null, tournamentMatch: null,
    };
    rooms.set(room.code, room);
    const player = addPlayer(room, parsed.data.nickname, parsed.data.clientType);
    persistState();
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
    let reservedId: PlayerId | undefined;
    let nickname = parsed.data.nickname;
    if (room.reservedPlayers) {
      const requested = nickname.toLocaleLowerCase();
      const seat = (Object.entries(room.reservedPlayers) as [PlayerId, string][])
        .find(([, reservedName]) => reservedName.toLocaleLowerCase() === requested);
      if (!seat) return error(reply, 403, "TOURNAMENT_SEAT_REQUIRED");
      [reservedId, nickname] = seat;
      const existingPlayer = room.players.find((player) => player.id === reservedId);
      if (existingPlayer) {
        return reply.code(200).send({
          roomCode: room.code,
          playerToken: existingPlayer.token,
          playerId: existingPlayer.id,
          snapshot: publicSnapshot(room, existingPlayer),
        });
      }
    }
    if (room.players.length >= 2) return error(reply, 409, "ROOM_FULL");
    const player = addPlayer(room, nickname, parsed.data.clientType, reservedId);
    if (room.players.length === 2) startGame(room);
    else {
      persistState();
      broadcast(room);
    }
    return reply.code(201).send({
      roomCode: room.code,
      playerToken: player.token,
      playerId: player.id,
      snapshot: publicSnapshot(room, player),
    });
  });

  app.post("/api/v1/tournaments", async (request, reply) => {
    const parsed = createTournamentSchema.safeParse(request.body);
    if (!parsed.success) return error(reply, 400, "INVALID_REQUEST");
    const normalized = parsed.data.participants.map((participant) => participant.trim());
    if (new Set(normalized.map((participant) => participant.toLocaleLowerCase())).size !== normalized.length) {
      return error(reply, 400, "DUPLICATE_PARTICIPANT");
    }
    const tournament = createTournament(parsed.data.name, normalized);
    return reply.code(201).send({ adminToken: tournament.adminToken, tournament: publicTournament(tournament) });
  });

  app.get("/api/v1/tournaments/:code", async (request, reply) => {
    const { code } = request.params as { code: string };
    const tournament = tournaments.get(code.toUpperCase());
    if (!tournament) return error(reply, 404, "TOURNAMENT_NOT_FOUND");
    reply.header("Cache-Control", "no-store");
    return publicTournament(tournament);
  });

  app.post("/api/v1/tournaments/:code/matches/:matchId/start", async (request, reply) => {
    const { code, matchId } = request.params as { code: string; matchId: string };
    const tournament = tournaments.get(code.toUpperCase());
    if (!tournament) return error(reply, 404, "TOURNAMENT_NOT_FOUND");
    if (bearerToken(request.headers.authorization) !== tournament.adminToken) return error(reply, 403, "ADMIN_REQUIRED");
    const match = findTournamentMatch(tournament, matchId);
    if (!match) return error(reply, 404, "MATCH_NOT_FOUND");
    if (match.status !== "READY" || !match.player1 || !match.player2) return error(reply, 409, "MATCH_NOT_READY");

    const room: Room = {
      code: makeRoomCode(), status: "WAITING", players: [], gameId: null, game: null,
      firstPlayer: randomInt(2) === 0 ? "P1" : "P2", turnDeadline: null, finishReason: null, timer: null,
      spectatorSockets: new Set(),
      reservedPlayers: { P1: match.player1, P2: match.player2 },
      tournamentMatch: { tournamentCode: tournament.code, matchId: match.id },
    };
    rooms.set(room.code, room);
    match.roomCode = room.code;
    match.status = "WAITING";
    persistState();
    broadcastTournament(tournament);
    return reply.code(201).send({ roomCode: room.code, tournament: publicTournament(tournament) });
  });

  app.post("/api/v1/tournaments/:code/matches/:matchId/forfeit", async (request, reply) => {
    const { code, matchId } = request.params as { code: string; matchId: string };
    const tournament = tournaments.get(code.toUpperCase());
    if (!tournament) return error(reply, 404, "TOURNAMENT_NOT_FOUND");
    if (bearerToken(request.headers.authorization) !== tournament.adminToken) return error(reply, 403, "ADMIN_REQUIRED");
    const match = findTournamentMatch(tournament, matchId);
    if (!match) return error(reply, 404, "MATCH_NOT_FOUND");
    const parsed = forfeitSchema.safeParse(request.body);
    if (!parsed.success) return error(reply, 400, "INVALID_REQUEST");
    if (match.winner || !match.player1 || !match.player2) return error(reply, 409, "MATCH_ALREADY_FINISHED");
    const loser = parsed.data.loser.toLocaleLowerCase();
    const winner = match.player1.toLocaleLowerCase() === loser
      ? match.player2
      : match.player2.toLocaleLowerCase() === loser ? match.player1 : null;
    if (!winner) return error(reply, 400, "PLAYER_NOT_IN_MATCH");

    if (match.roomCode) {
      const room = rooms.get(match.roomCode);
      if (room) {
        clearTurnTimer(room);
        room.status = "FINISHED";
        room.finishReason = "FORFEIT";
        room.turnDeadline = null;
        if (room.game && room.reservedPlayers) {
          const winnerId = (Object.entries(room.reservedPlayers) as [PlayerId, string][])
            .find(([, nickname]) => nickname === winner)?.[0];
          if (winnerId) room.game = { ...room.game, winner: winnerId };
        }
        broadcast(room);
      }
    }
    completeTournamentMatch(tournament, match, winner, "FORFEIT");
    return { ok: true, tournament: publicTournament(tournament) };
  });

  app.get("/api/v1/rooms/:code/watch", async (request, reply) => {
    const { code } = request.params as { code: string };
    const room = rooms.get(code.toUpperCase());
    if (!room) return error(reply, 404, "ROOM_NOT_FOUND");
    reply.header("Cache-Control", "no-store");
    return publicSnapshot(room);
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
      completeTournamentFromRoom(room);
    } else {
      armTurnTimer(room);
    }
    const response = { ok: true, version: room.game.version, snapshot: publicSnapshot(room, player) };
    if (cacheKey) idempotencyCache.set(cacheKey, response);
    persistState();
    broadcast(room);
    return response;
  });

  app.post("/api/v1/rooms/:code/rematch", async (request, reply) => {
    const { code } = request.params as { code: string };
    const room = rooms.get(code.toUpperCase());
    const token = bearerToken(request.headers.authorization);
    const player = room ? playerByToken(room, token) : undefined;
    if (!room || !player) return error(reply, 401, "INVALID_TOKEN");
    if (room.tournamentMatch) return error(reply, 409, "REMATCH_NOT_AVAILABLE");
    if (room.status !== "FINISHED") return error(reply, 409, "GAME_NOT_FINISHED");
    player.rematchReady = true;
    if (room.players.length === 2 && room.players.every((entry) => entry.rematchReady)) {
      room.firstPlayer = otherPlayer(room.firstPlayer);
      startGame(room);
    } else {
      persistState();
      broadcast(room);
    }
    return { ok: true };
  });

  app.get("/ws", { websocket: true }, (socket, request) => {
    const query = request.query as { token?: string; room?: string; tournament?: string };
    if (query.tournament) {
      const tournament = tournaments.get(query.tournament.toUpperCase());
      if (!tournament) {
        socket.close(1008, "Invalid tournament");
        return;
      }
      tournament.sockets.add(socket);
      socket.send(JSON.stringify({ type: "tournament.snapshot", payload: publicTournament(tournament) }));
      socket.on("close", () => tournament.sockets.delete(socket));
      return;
    }
    if (query.token) {
      const room = tokenToRoom.get(query.token);
      const player = room ? playerByToken(room, query.token) : undefined;
      if (!room || !player) {
        socket.close(1008, "Invalid token");
        return;
      }
      player.sockets.add(socket);
      player.connected = true;
      broadcast(room);
      socket.on("close", () => {
        player.sockets.delete(socket);
        player.connected = player.clientType === "BOT" || player.sockets.size > 0;
        broadcast(room);
      });
      return;
    }

    const room = query.room ? rooms.get(query.room.toUpperCase()) : undefined;
    if (!room) {
      socket.close(1008, "Invalid room");
      return;
    }
    room.spectatorSockets.add(socket);
    broadcast(room);
    socket.on("close", () => {
      room.spectatorSockets.delete(socket);
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
