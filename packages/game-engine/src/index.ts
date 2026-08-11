export const BOARD_SIZE = 9;
export const WALL_GRID_SIZE = 8;

export type PlayerId = "P1" | "P2";
export type Orientation = "HORIZONTAL" | "VERTICAL";
export type Position = { row: number; col: number };
export type Wall = Position & { orientation: Orientation };

export type MovePawnAction = { type: "MOVE_PAWN"; to: Position };
export type PlaceWallAction = {
  type: "PLACE_WALL";
  orientation: Orientation;
  row: number;
  col: number;
};
export type GameAction = MovePawnAction | PlaceWallAction;

export type GameState = {
  version: number;
  turn: PlayerId;
  pawns: Record<PlayerId, Position>;
  wallsRemaining: Record<PlayerId, number>;
  walls: Wall[];
  winner: PlayerId | null;
};

export type ActionResult =
  | { ok: true; state: GameState }
  | { ok: false; reason: string };

const directions: Position[] = [
  { row: -1, col: 0 },
  { row: 1, col: 0 },
  { row: 0, col: -1 },
  { row: 0, col: 1 },
];

export function createInitialState(first: PlayerId = "P1"): GameState {
  return {
    version: 0,
    turn: first,
    pawns: { P1: { row: 8, col: 4 }, P2: { row: 0, col: 4 } },
    wallsRemaining: { P1: 10, P2: 10 },
    walls: [],
    winner: null,
  };
}

export function otherPlayer(player: PlayerId): PlayerId {
  return player === "P1" ? "P2" : "P1";
}

export function isInside(position: Position): boolean {
  return (
    Number.isInteger(position.row) &&
    Number.isInteger(position.col) &&
    position.row >= 0 &&
    position.row < BOARD_SIZE &&
    position.col >= 0 &&
    position.col < BOARD_SIZE
  );
}

export function samePosition(a: Position, b: Position): boolean {
  return a.row === b.row && a.col === b.col;
}

export function isBlocked(a: Position, b: Position, walls: Wall[]): boolean {
  if (a.row === b.row) {
    const leftCol = Math.min(a.col, b.col);
    return walls.some(
      (wall) =>
        wall.orientation === "VERTICAL" &&
        (wall.row === a.row || wall.row === a.row - 1) &&
        wall.col === leftCol,
    );
  }

  const topRow = Math.min(a.row, b.row);
  return walls.some(
    (wall) =>
      wall.orientation === "HORIZONTAL" &&
      wall.row === topRow &&
      (wall.col === a.col || wall.col === a.col - 1),
  );
}

export function legalPawnMoves(state: GameState, player: PlayerId): Position[] {
  const me = state.pawns[player];
  const opponent = state.pawns[otherPlayer(player)];
  const moves: Position[] = [];

  for (const direction of directions) {
    const adjacent = { row: me.row + direction.row, col: me.col + direction.col };
    if (!isInside(adjacent) || isBlocked(me, adjacent, state.walls)) continue;

    if (!samePosition(adjacent, opponent)) {
      moves.push(adjacent);
      continue;
    }

    const jump = {
      row: opponent.row + direction.row,
      col: opponent.col + direction.col,
    };
    if (isInside(jump) && !isBlocked(opponent, jump, state.walls)) {
      moves.push(jump);
      continue;
    }

    const perpendiculars = direction.row !== 0
      ? [{ row: 0, col: -1 }, { row: 0, col: 1 }]
      : [{ row: -1, col: 0 }, { row: 1, col: 0 }];

    for (const side of perpendiculars) {
      const diagonal = { row: opponent.row + side.row, col: opponent.col + side.col };
      if (isInside(diagonal) && !isBlocked(opponent, diagonal, state.walls)) {
        moves.push(diagonal);
      }
    }
  }

  return moves;
}

export function wallConflicts(wall: Wall, walls: Wall[]): boolean {
  return walls.some((existing) => {
    if (existing.orientation !== wall.orientation) {
      return existing.row === wall.row && existing.col === wall.col;
    }
    if (wall.orientation === "HORIZONTAL") {
      return existing.row === wall.row && Math.abs(existing.col - wall.col) <= 1;
    }
    return existing.col === wall.col && Math.abs(existing.row - wall.row) <= 1;
  });
}

export function hasPathToGoal(state: GameState, player: PlayerId): boolean {
  const start = state.pawns[player];
  const goalRow = player === "P1" ? 0 : 8;
  const queue: Position[] = [start];
  const visited = new Set([`${start.row},${start.col}`]);

  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    if (current.row === goalRow) return true;

    for (const direction of directions) {
      const next = { row: current.row + direction.row, col: current.col + direction.col };
      const key = `${next.row},${next.col}`;
      if (!isInside(next) || visited.has(key) || isBlocked(current, next, state.walls)) continue;
      visited.add(key);
      queue.push(next);
    }
  }
  return false;
}

export function canPlaceWall(state: GameState, wall: Wall): boolean {
  if (
    !Number.isInteger(wall.row) ||
    !Number.isInteger(wall.col) ||
    wall.row < 0 ||
    wall.row >= WALL_GRID_SIZE ||
    wall.col < 0 ||
    wall.col >= WALL_GRID_SIZE ||
    wallConflicts(wall, state.walls)
  ) return false;

  const simulated = { ...state, walls: [...state.walls, wall] };
  return hasPathToGoal(simulated, "P1") && hasPathToGoal(simulated, "P2");
}

export function legalActions(state: GameState, player: PlayerId = state.turn): GameAction[] {
  if (state.winner) return [];
  const actions: GameAction[] = legalPawnMoves(state, player).map((to) => ({
    type: "MOVE_PAWN",
    to,
  }));

  if (state.wallsRemaining[player] > 0) {
    for (let row = 0; row < WALL_GRID_SIZE; row += 1) {
      for (let col = 0; col < WALL_GRID_SIZE; col += 1) {
        for (const orientation of ["HORIZONTAL", "VERTICAL"] as const) {
          const wall = { row, col, orientation };
          if (canPlaceWall(state, wall)) actions.push({ type: "PLACE_WALL", ...wall });
        }
      }
    }
  }
  return actions;
}

export function applyAction(state: GameState, player: PlayerId, action: GameAction): ActionResult {
  if (state.winner) return { ok: false, reason: "GAME_ALREADY_FINISHED" };
  if (state.turn !== player) return { ok: false, reason: "NOT_YOUR_TURN" };

  if (action.type === "MOVE_PAWN") {
    if (!legalPawnMoves(state, player).some((move) => samePosition(move, action.to))) {
      return { ok: false, reason: "ILLEGAL_MOVE" };
    }
    const pawns = { ...state.pawns, [player]: { ...action.to } };
    const winner = (player === "P1" && action.to.row === 0) ||
      (player === "P2" && action.to.row === 8) ? player : null;
    return {
      ok: true,
      state: {
        ...state,
        version: state.version + 1,
        pawns,
        winner,
        turn: winner ? state.turn : otherPlayer(player),
      },
    };
  }

  const wall: Wall = {
    row: action.row,
    col: action.col,
    orientation: action.orientation,
  };
  if (state.wallsRemaining[player] <= 0) return { ok: false, reason: "NO_WALLS_LEFT" };
  if (!canPlaceWall(state, wall)) return { ok: false, reason: "ILLEGAL_WALL" };

  return {
    ok: true,
    state: {
      ...state,
      version: state.version + 1,
      turn: otherPlayer(player),
      walls: [...state.walls, wall],
      wallsRemaining: {
        ...state.wallsRemaining,
        [player]: state.wallsRemaining[player] - 1,
      },
    },
  };
}
