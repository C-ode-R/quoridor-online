import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";

describe("persistent server state", () => {
  const directory = mkdtempSync(join(tmpdir(), "quoridor-state-"));
  const path = join(directory, "state.json");

  afterAll(() => {
    delete process.env.STATE_FILE;
    rmSync(directory, { recursive: true, force: true });
  });

  it("restores rooms, tokens, and tournaments after a server restart", async () => {
    process.env.STATE_FILE = path;
    vi.resetModules();
    const firstModule = await import("./server.js");
    const firstServer = await firstModule.buildServer();

    const roomResponse = await firstServer.inject({
      method: "POST", url: "/api/v1/rooms", payload: { nickname: "Persistent Bot", clientType: "BOT" },
    });
    const room = roomResponse.json();
    const tournamentResponse = await firstServer.inject({
      method: "POST", url: "/api/v1/tournaments",
      payload: { name: "Saved Cup", participants: ["Alpha", "Beta", "Gamma"] },
    });
    const tournament = tournamentResponse.json().tournament;
    expect(existsSync(path)).toBe(true);
    await firstServer.close();

    vi.resetModules();
    const secondModule = await import("./server.js");
    const secondServer = await secondModule.buildServer();
    const restoredRoom = await secondServer.inject({
      method: "GET", url: `/api/v1/rooms/${room.roomCode}/watch`,
    });
    const restoredSession = await secondServer.inject({
      method: "GET", url: "/api/v1/session", headers: { authorization: `Bearer ${room.playerToken}` },
    });
    const restoredTournament = await secondServer.inject({
      method: "GET", url: `/api/v1/tournaments/${tournament.code}`,
    });

    expect(restoredRoom.statusCode).toBe(200);
    expect(restoredRoom.json().players[0].nickname).toBe("Persistent Bot");
    expect(restoredSession.statusCode).toBe(200);
    expect(restoredTournament.statusCode).toBe(200);
    expect(restoredTournament.json()).toMatchObject({ name: "Saved Cup", participants: ["Alpha", "Beta", "Gamma"] });
    await secondServer.close();
  });
});
