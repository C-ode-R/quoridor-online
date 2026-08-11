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
  });
});
