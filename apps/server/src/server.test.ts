import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "./server.js";

describe("room API", () => {
  let app: FastifyInstance;
  beforeAll(async () => { app = await buildServer(); });
  afterAll(async () => { await app.close(); });

  it("creates, joins, and plays a move", async () => {
    const created = await app.inject({
      method: "POST", url: "/api/v1/rooms", payload: { nickname: "Alpha", clientType: "BOT" },
    });
    expect(created.statusCode).toBe(201);
    const host = created.json();

    const waitingSpectator = await app.inject({
      method: "GET", url: `/api/v1/rooms/${host.roomCode.toLowerCase()}/watch`,
    });
    expect(waitingSpectator.statusCode).toBe(200);
    expect(waitingSpectator.json()).toMatchObject({
      roomCode: host.roomCode,
      status: "WAITING",
      me: null,
      spectatorCount: 0,
    });

    const joined = await app.inject({
      method: "POST", url: `/api/v1/rooms/${host.roomCode}/join`,
      payload: { nickname: "Beta", clientType: "BOT" },
    });
    expect(joined.statusCode).toBe(201);

    const session = await app.inject({
      method: "GET", url: "/api/v1/session", headers: { authorization: `Bearer ${host.playerToken}` },
    });
    const snapshot = session.json();
    expect(snapshot.status).toBe("PLAYING");

    const moved = await app.inject({
      method: "POST", url: `/api/v1/games/${snapshot.gameId}/actions`,
      headers: { authorization: `Bearer ${host.playerToken}` },
      payload: { expectedVersion: 0, action: { type: "MOVE_PAWN", to: { row: 7, col: 4 } } },
    });
    expect(moved.statusCode).toBe(200);
    expect(moved.json().version).toBe(1);

    const spectator = await app.inject({
      method: "GET", url: `/api/v1/rooms/${host.roomCode}/watch`,
    });
    expect(spectator.statusCode).toBe(200);
    expect(spectator.json().game.version).toBe(1);
    expect(spectator.json().game.legalActions).toEqual([]);
  });

  it("returns 404 when spectating a missing room", async () => {
    const response = await app.inject({ method: "GET", url: "/api/v1/rooms/ZZZZZZ/watch" });
    expect(response.statusCode).toBe(404);
    expect(response.json()).toEqual({ error: { code: "ROOM_NOT_FOUND" } });
  });
});

describe("tournament API", () => {
  let app: FastifyInstance;
  beforeAll(async () => { app = await buildServer(); });
  afterAll(async () => { await app.close(); });

  it("creates a random bracket and advances byes", async () => {
    const created = await app.inject({
      method: "POST",
      url: "/api/v1/tournaments",
      payload: { name: "Club Cup", participants: ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"] },
    });
    expect(created.statusCode).toBe(201);
    const { tournament } = created.json();
    expect(tournament.rounds.map((round: unknown[]) => round.length)).toEqual([4, 2, 1]);
    expect(tournament.rounds[0].filter((match: { status: string }) => match.status === "BYE")).toHaveLength(3);
    expect(tournament.rounds.flat().filter((match: { status: string }) => match.status === "READY").length).toBeGreaterThan(0);
  });

  it("reserves player seats, handles a forfeit, and advances the winner", async () => {
    const created = await app.inject({
      method: "POST",
      url: "/api/v1/tournaments",
      payload: { name: "Final", participants: ["Alpha", "Beta"] },
    });
    const { adminToken, tournament } = created.json();
    const match = tournament.rounds[0][0];
    const started = await app.inject({
      method: "POST",
      url: `/api/v1/tournaments/${tournament.code}/matches/${match.id}/start`,
      headers: { authorization: `Bearer ${adminToken}` },
      payload: {},
    });
    expect(started.statusCode).toBe(201);
    const roomCode = started.json().roomCode;

    const intruder = await app.inject({
      method: "POST", url: `/api/v1/rooms/${roomCode}/join`,
      payload: { nickname: "Intruder", clientType: "BOT" },
    });
    expect(intruder.statusCode).toBe(403);
    expect(intruder.json().error.code).toBe("TOURNAMENT_SEAT_REQUIRED");

    let firstSeatToken = "";
    for (const nickname of [match.player2, match.player1]) {
      const joined = await app.inject({
        method: "POST", url: `/api/v1/rooms/${roomCode}/join`,
        payload: { nickname, clientType: "BOT" },
      });
      expect(joined.statusCode).toBe(201);
      if (nickname === match.player2) firstSeatToken = joined.json().playerToken;
    }
    const rejoined = await app.inject({
      method: "POST", url: `/api/v1/rooms/${roomCode}/join`,
      payload: { nickname: match.player2, clientType: "BOT" },
    });
    expect(rejoined.statusCode).toBe(200);
    expect(rejoined.json().playerToken).toBe(firstSeatToken);
    const watching = await app.inject({ method: "GET", url: `/api/v1/rooms/${roomCode}/watch` });
    expect(watching.json().status).toBe("PLAYING");

    const forfeited = await app.inject({
      method: "POST",
      url: `/api/v1/tournaments/${tournament.code}/matches/${match.id}/forfeit`,
      headers: { authorization: `Bearer ${adminToken}` },
      payload: { loser: match.player1 },
    });
    expect(forfeited.statusCode).toBe(200);
    expect(forfeited.json().tournament).toMatchObject({ status: "FINISHED", winner: match.player2 });
    const finishedRoom = await app.inject({ method: "GET", url: `/api/v1/rooms/${roomCode}/watch` });
    expect(finishedRoom.json().game).toMatchObject({ winner: "P2", finishReason: "FORFEIT" });
  });

  it("rejects duplicate participant names", async () => {
    const response = await app.inject({
      method: "POST", url: "/api/v1/tournaments",
      payload: { participants: ["Alpha", "alpha"] },
    });
    expect(response.statusCode).toBe(400);
    expect(response.json().error.code).toBe("DUPLICATE_PARTICIPANT");
  });

  it("automatically completes the bracket after a goal", async () => {
    const created = await app.inject({
      method: "POST", url: "/api/v1/tournaments",
      payload: { participants: ["Runner A", "Runner B"] },
    });
    const { adminToken, tournament } = created.json();
    const match = tournament.rounds[0][0];
    const started = await app.inject({
      method: "POST", url: `/api/v1/tournaments/${tournament.code}/matches/${match.id}/start`,
      headers: { authorization: `Bearer ${adminToken}` }, payload: {},
    });
    const roomCode = started.json().roomCode;
    const tokens: Record<string, string> = {};
    for (const nickname of [match.player1, match.player2]) {
      const joined = await app.inject({
        method: "POST", url: `/api/v1/rooms/${roomCode}/join`, payload: { nickname, clientType: "BOT" },
      });
      tokens[joined.json().playerId] = joined.json().playerToken;
    }

    for (let turn = 0; turn < 30; turn += 1) {
      const watched = await app.inject({ method: "GET", url: `/api/v1/rooms/${roomCode}/watch` });
      const room = watched.json();
      if (room.status === "FINISHED") break;
      const playerId = room.game.turn as "P1" | "P2";
      const stateResponse = await app.inject({
        method: "GET", url: `/api/v1/games/${room.gameId}/state`,
        headers: { authorization: `Bearer ${tokens[playerId]}` },
      });
      const state = stateResponse.json();
      const moves = state.game.legalActions.filter((action: { type: string }) => action.type === "MOVE_PAWN");
      moves.sort((left: { to: { row: number } }, right: { to: { row: number } }) =>
        playerId === "P1" ? left.to.row - right.to.row : right.to.row - left.to.row,
      );
      const moved = await app.inject({
        method: "POST", url: `/api/v1/games/${room.gameId}/actions`,
        headers: { authorization: `Bearer ${tokens[playerId]}` },
        payload: { expectedVersion: state.game.version, action: moves[0] },
      });
      expect(moved.statusCode).toBe(200);
    }

    const result = await app.inject({ method: "GET", url: `/api/v1/tournaments/${tournament.code}` });
    expect(result.json().status).toBe("FINISHED");
    expect([match.player1, match.player2]).toContain(result.json().winner);
    expect(result.json().rounds[0][0].finishReason).toBe("GOAL");
  });
});
