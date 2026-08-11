import { describe, expect, it } from "vitest";
import {
  applyAction,
  canPlaceWall,
  createInitialState,
  hasPathToGoal,
  isBlocked,
  legalPawnMoves,
  type GameState,
} from "./index.js";

describe("Quoridor engine", () => {
  it("creates the standard starting state", () => {
    const state = createInitialState();
    expect(state.pawns.P1).toEqual({ row: 8, col: 4 });
    expect(state.pawns.P2).toEqual({ row: 0, col: 4 });
    expect(state.wallsRemaining).toEqual({ P1: 10, P2: 10 });
  });

  it("moves a pawn and changes the turn", () => {
    const result = applyAction(createInitialState(), "P1", {
      type: "MOVE_PAWN",
      to: { row: 7, col: 4 },
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.state.turn).toBe("P2");
      expect(result.state.version).toBe(1);
    }
  });

  it("blocks movement across a horizontal wall", () => {
    const walls = [{ row: 7, col: 4, orientation: "HORIZONTAL" as const }];
    expect(isBlocked({ row: 8, col: 4 }, { row: 7, col: 4 }, walls)).toBe(true);
    expect(isBlocked({ row: 8, col: 5 }, { row: 7, col: 5 }, walls)).toBe(true);
  });

  it("allows a straight jump over the opponent", () => {
    const state: GameState = {
      ...createInitialState(),
      pawns: { P1: { row: 4, col: 4 }, P2: { row: 3, col: 4 } },
    };
    expect(legalPawnMoves(state, "P1")).toContainEqual({ row: 2, col: 4 });
  });

  it("allows diagonal movement when a jump is blocked", () => {
    const state: GameState = {
      ...createInitialState(),
      pawns: { P1: { row: 4, col: 4 }, P2: { row: 3, col: 4 } },
      walls: [{ row: 2, col: 4, orientation: "HORIZONTAL" }],
    };
    const moves = legalPawnMoves(state, "P1");
    expect(moves).toContainEqual({ row: 3, col: 3 });
    expect(moves).toContainEqual({ row: 3, col: 5 });
  });

  it("rejects crossing and overlapping walls", () => {
    const state = {
      ...createInitialState(),
      walls: [{ row: 3, col: 3, orientation: "HORIZONTAL" as const }],
    };
    expect(canPlaceWall(state, { row: 3, col: 3, orientation: "VERTICAL" })).toBe(false);
    expect(canPlaceWall(state, { row: 3, col: 4, orientation: "HORIZONTAL" })).toBe(false);
  });

  it("keeps a path for both players", () => {
    const state = createInitialState();
    expect(hasPathToGoal(state, "P1")).toBe(true);
    expect(hasPathToGoal(state, "P2")).toBe(true);
  });
});
