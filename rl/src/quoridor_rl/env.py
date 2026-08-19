from __future__ import annotations

import hashlib
from dataclasses import dataclass

from quoridor_sdk import Action, MovePawn, PlaceWall, Position, Wall

BOARD_SIZE = 9
WALL_SIZE = 8
DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def other(player: str) -> str:
    return "P2" if player == "P1" else "P1"


@dataclass(slots=True)
class LocalState:
    turn: str
    pawns: dict[str, Position]
    walls_remaining: dict[str, int]
    walls: list[Wall]
    winner: str | None = None
    done: bool = False
    move_count: int = 0
    termination_reason: str | None = None
    repetition_count: int = 1

    def clone(self) -> LocalState:
        return LocalState(
            turn=self.turn,
            pawns=dict(self.pawns),
            walls_remaining=dict(self.walls_remaining),
            walls=list(self.walls),
            winner=self.winner,
            done=self.done,
            move_count=self.move_count,
            termination_reason=self.termination_reason,
            repetition_count=self.repetition_count,
        )


class QuoridorEnv:
    """Fast local two-player environment used for self-play training."""

    def __init__(self, *, max_moves: int = 128):
        self.max_moves = max_moves
        self._state = self.initial_state()
        self._horizontal_walls: set[tuple[int, int]] = set()
        self._vertical_walls: set[tuple[int, int]] = set()
        self._position_counts: dict[tuple, int] = {}
        self.state = self.initial_state()

    @property
    def state(self) -> LocalState:
        return self._state

    @state.setter
    def state(self, value: LocalState) -> None:
        self._state = value
        self._rebuild_wall_index()
        self._position_counts = {self.position_key(): value.repetition_count}

    def _rebuild_wall_index(self) -> None:
        self._horizontal_walls = {
            (wall.row, wall.col) for wall in self._state.walls if wall.orientation == "HORIZONTAL"
        }
        self._vertical_walls = {
            (wall.row, wall.col) for wall in self._state.walls if wall.orientation == "VERTICAL"
        }

    def _ensure_wall_index(self) -> None:
        if len(self._horizontal_walls) + len(self._vertical_walls) != len(self.state.walls):
            self._rebuild_wall_index()

    @staticmethod
    def initial_state(first_player: str = "P1") -> LocalState:
        return LocalState(
            turn=first_player,
            pawns={"P1": Position(8, 4), "P2": Position(0, 4)},
            walls_remaining={"P1": 10, "P2": 10},
            walls=[],
        )

    def reset(self, *, first_player: str = "P1") -> LocalState:
        self.state = self.initial_state(first_player)
        return self.state.clone()

    def clone(self) -> QuoridorEnv:
        copied = QuoridorEnv(max_moves=self.max_moves)
        copied.state = self.state.clone()
        copied._position_counts = dict(self._position_counts)
        return copied

    def position_key(self) -> tuple:
        """Hashable board position key, excluding clocks and terminal metadata."""
        return (
            self.state.turn,
            self.state.pawns["P1"].row,
            self.state.pawns["P1"].col,
            self.state.pawns["P2"].row,
            self.state.pawns["P2"].col,
            self.state.walls_remaining["P1"],
            self.state.walls_remaining["P2"],
            tuple(sorted((wall.row, wall.col, wall.orientation) for wall in self.state.walls)),
        )

    def search_key(self) -> tuple:
        """Tree key including information that affects cutoff and repetition."""
        return (
            self.position_key(),
            self.state.move_count,
            self.max_moves,
            self.state.repetition_count,
            frozenset(self._position_counts.items()),
        )

    def inference_key(self) -> tuple:
        """Key for deterministic model/candidate inference reuse."""
        return (
            self.position_key(),
            self.state.move_count,
            self.max_moves,
            self.state.repetition_count,
        )

    def legal_actions(self, player: str | None = None) -> tuple[Action, ...]:
        player = player or self.state.turn
        if self.state.done:
            return ()

        actions: list[Action] = [MovePawn(position) for position in self._legal_pawn_moves(player)]
        if self.state.walls_remaining[player] > 0:
            for row in range(WALL_SIZE):
                for col in range(WALL_SIZE):
                    for orientation in ("HORIZONTAL", "VERTICAL"):
                        action = PlaceWall(row=row, col=col, orientation=orientation)
                        if self._can_place_wall(action):
                            actions.append(action)
        return tuple(actions)

    def step(self, action: Action, *, validate: bool = True) -> tuple[LocalState, float, bool]:
        if self.state.done:
            raise ValueError("Game is already finished")
        player = self.state.turn
        if validate and action not in self.legal_actions(player):
            raise ValueError(f"Illegal action: {action!r}")

        if isinstance(action, MovePawn):
            self.state.pawns[player] = action.to
            reached_goal = (
                player == "P1" and action.to.row == 0
            ) or (
                player == "P2" and action.to.row == 8
            )
            if reached_goal:
                self.state.winner = player
                self.state.done = True
                self.state.termination_reason = "GOAL"
        else:
            wall = Wall(action.row, action.col, action.orientation)
            self.state.walls.append(wall)
            target = self._horizontal_walls if wall.orientation == "HORIZONTAL" else self._vertical_walls
            target.add((wall.row, wall.col))
            self.state.walls_remaining[player] -= 1

        self.state.move_count += 1
        self.state.turn = other(player)
        if not self.state.done:
            position_key = self.position_key()
            self._position_counts[position_key] = self._position_counts.get(position_key, 0) + 1
            self.state.repetition_count = self._position_counts[position_key]
            if self.state.repetition_count >= 3:
                self.state.done = True
                # Repeating the same position for the third time is treated as
                # a loss for the mover so self-play cannot exploit cycles.
                self.state.winner = self.state.turn
                self.state.termination_reason = "REPETITION"
            elif self.state.move_count >= self.max_moves:
                self.state.done = True
                self.state.winner = self._adjudicate_winner()
                self.state.termination_reason = "MOVE_LIMIT"

        reward = 1.0 if self.state.winner == player else 0.0
        return self.state.clone(), reward, self.state.done

    def _adjudicate_winner(self) -> str | None:
        """Choose the better position when the self-play safety limit is reached."""
        scores: dict[str, tuple[int, int, int]] = {}
        for player in ("P1", "P2"):
            distance = len(self.shortest_path(player)) - 1
            mobility = len(self._legal_pawn_moves(player))
            scores[player] = (distance, -self.state.walls_remaining[player], -mobility)
        if scores["P1"] == scores["P2"]:
            return None
        return min(scores, key=scores.__getitem__)

    def search_actions(self, *, max_wall_candidates: int = 24) -> tuple[Action, ...]:
        """Return a strong, bounded action set for tree search.

        Pawn moves are never pruned. Wall candidates are taken from the edges on
        both players' current shortest paths, with the opponent's path first.
        This keeps MCTS practical on CPUs without changing the game rules used
        by :meth:`legal_actions`.
        """
        if self.state.done:
            return ()
        player = self.state.turn
        actions: list[Action] = [MovePawn(position) for position in self._legal_pawn_moves(player)]
        pawn_action_count = len(actions)
        if self.state.walls_remaining[player] <= 0 or max_wall_candidates <= 0:
            return tuple(actions)

        opponent = other(player)
        candidate_scores: dict[PlaceWall, float] = {}
        for path_player, coverage_weight in ((opponent, 1.0), (player, 0.15)):
            for first, second in self.shortest_path_edges(path_player):
                for wall in self._walls_blocking_edge(first, second):
                    candidate_scores[wall] = candidate_scores.get(wall, 0.0) + coverage_weight

        # Local tactical walls prevent the strategic pool from collapsing onto
        # only one family of shortest paths.
        for pawn in self.state.pawns.values():
            for row in range(max(0, pawn.row - 2), min(WALL_SIZE, pawn.row + 2)):
                for col in range(max(0, pawn.col - 2), min(WALL_SIZE, pawn.col + 2)):
                    for orientation in ("HORIZONTAL", "VERTICAL"):
                        candidate_scores.setdefault(PlaceWall(row, col, orientation), 0.05)

        state_seed = repr(self.position_key()).encode()
        all_walls = [
            PlaceWall(row, col, orientation)
            for row in range(WALL_SIZE)
            for col in range(WALL_SIZE)
            for orientation in ("HORIZONTAL", "VERTICAL")
        ]
        all_walls.sort(
            key=lambda wall: hashlib.sha256(
                state_seed + f"{wall.row}:{wall.col}:{wall.orientation}".encode()
            ).digest()
        )
        base_own = len(self.shortest_path(player)) - 1
        base_opponent = len(self.shortest_path(opponent)) - 1
        ranked_pool = sorted(
            candidate_scores,
            key=lambda wall: (-candidate_scores[wall], wall.row, wall.col, wall.orientation),
        )[: max(40, max_wall_candidates * 2)]
        ranked: list[tuple[float, PlaceWall]] = []
        for wall in ranked_pool:
            impact = self._wall_impact(
                wall,
                player=player,
                base_own=base_own,
                base_opponent=base_opponent,
            )
            if impact is None:
                continue
            own_delta, opponent_delta = impact
            score = 5.0 * opponent_delta - 2.0 * own_delta + candidate_scores[wall]
            ranked.append((score, wall))

        ranked.sort(key=lambda item: (-item[0], item[1].row, item[1].col, item[1].orientation))
        exploration_count = min(4, max_wall_candidates // 4)
        strategic_count = max_wall_candidates - exploration_count
        selected = [wall for _score, wall in ranked[:strategic_count]]
        # Explore globally, not merely inside the already-truncated strategic
        # pool. The bounded attempt count keeps deep-node expansion predictable.
        global_candidates = [wall for wall in all_walls if wall not in selected]
        global_candidates.sort(
            key=lambda wall: hashlib.sha256(
                state_seed + b"explore" + f"{wall.row}:{wall.col}:{wall.orientation}".encode()
            ).digest()
        )
        explored: list[PlaceWall] = []
        if exploration_count > 0:
            for wall in global_candidates[:32]:
                if self._wall_impact(
                    wall,
                    player=player,
                    base_own=base_own,
                    base_opponent=base_opponent,
                ) is not None:
                    explored.append(wall)
                    if len(explored) >= exploration_count:
                        break
        selected.extend(explored)
        if len(selected) < max_wall_candidates:
            remaining = [
                wall
                for _score, wall in ranked[strategic_count:]
                if wall not in selected
            ]
            selected.extend(remaining[: max_wall_candidates - len(selected)])
        actions.extend(selected)
        assert len(actions) - pawn_action_count <= max_wall_candidates
        return tuple(actions)

    def _wall_impact(
        self,
        wall: PlaceWall,
        *,
        player: str,
        base_own: int,
        base_opponent: int,
    ) -> tuple[int, int] | None:
        self._ensure_wall_index()
        placed = Wall(wall.row, wall.col, wall.orientation)
        if not 0 <= placed.row < WALL_SIZE or not 0 <= placed.col < WALL_SIZE:
            return None
        if self._wall_conflicts(placed):
            return None
        self.state.walls.append(placed)
        target = (
            self._horizontal_walls
            if placed.orientation == "HORIZONTAL"
            else self._vertical_walls
        )
        target.add((placed.row, placed.col))
        own_path = self.shortest_path(player)
        opponent_path = self.shortest_path(other(player))
        self.state.walls.pop()
        target.remove((placed.row, placed.col))
        if not own_path or not opponent_path:
            return None
        return (len(own_path) - 1 - base_own, len(opponent_path) - 1 - base_opponent)

    def shortest_path(self, player: str) -> list[Position]:
        """Return one shortest path to the player's goal, including its start."""
        start = self.state.pawns[player]
        goal_row = 0 if player == "P1" else BOARD_SIZE - 1
        queue = [start]
        parent: dict[Position, Position | None] = {start: None}
        goal: Position | None = None
        for current in queue:
            if current.row == goal_row:
                goal = current
                break
            for dr, dc in DIRECTIONS:
                nxt = Position(current.row + dr, current.col + dc)
                if self._inside(nxt) and nxt not in parent and not self._blocked(current, nxt):
                    parent[nxt] = current
                    queue.append(nxt)
        if goal is None:
            return []
        path = []
        current: Position | None = goal
        while current is not None:
            path.append(current)
            current = parent[current]
        return list(reversed(path))

    def shortest_path_edges(self, player: str) -> set[tuple[Position, Position]]:
        """Return every edge that belongs to any shortest path to the goal."""
        start = self.state.pawns[player]
        goals = [Position(0 if player == "P1" else BOARD_SIZE - 1, col) for col in range(BOARD_SIZE)]
        from_start = self._distance_map([start])
        to_goal = self._distance_map(goals)
        distance = min(from_start.get(goal, BOARD_SIZE * BOARD_SIZE) for goal in goals)
        edges: set[tuple[Position, Position]] = set()
        for current, current_distance in from_start.items():
            for dr, dc in DIRECTIONS:
                nxt = Position(current.row + dr, current.col + dc)
                if (
                    nxt in from_start
                    and from_start[nxt] == current_distance + 1
                    and current_distance + 1 + to_goal.get(nxt, BOARD_SIZE * BOARD_SIZE) == distance
                ):
                    edges.add((current, nxt))
        return edges

    def _distance_map(self, starts: list[Position]) -> dict[Position, int]:
        distances = {position: 0 for position in starts}
        queue = list(starts)
        for current in queue:
            for dr, dc in DIRECTIONS:
                nxt = Position(current.row + dr, current.col + dc)
                if self._inside(nxt) and nxt not in distances and not self._blocked(current, nxt):
                    distances[nxt] = distances[current] + 1
                    queue.append(nxt)
        return distances

    @staticmethod
    def _walls_blocking_edge(first: Position, second: Position) -> tuple[PlaceWall, ...]:
        if first.row == second.row:
            left_col = min(first.col, second.col)
            return tuple(
                PlaceWall(row=row, col=left_col, orientation="VERTICAL")
                for row in (first.row, first.row - 1)
                if 0 <= row < WALL_SIZE and 0 <= left_col < WALL_SIZE
            )
        top_row = min(first.row, second.row)
        return tuple(
            PlaceWall(row=top_row, col=col, orientation="HORIZONTAL")
            for col in (first.col, first.col - 1)
            if 0 <= top_row < WALL_SIZE and 0 <= col < WALL_SIZE
        )

    def _legal_pawn_moves(self, player: str) -> list[Position]:
        me = self.state.pawns[player]
        opponent = self.state.pawns[other(player)]
        moves: list[Position] = []

        for dr, dc in DIRECTIONS:
            adjacent = Position(me.row + dr, me.col + dc)
            if not self._inside(adjacent) or self._blocked(me, adjacent):
                continue
            if adjacent != opponent:
                moves.append(adjacent)
                continue

            jump = Position(opponent.row + dr, opponent.col + dc)
            if self._inside(jump) and not self._blocked(opponent, jump):
                moves.append(jump)
                continue

            perpendicular = ((0, -1), (0, 1)) if dr else ((-1, 0), (1, 0))
            for side_dr, side_dc in perpendicular:
                diagonal = Position(opponent.row + side_dr, opponent.col + side_dc)
                if self._inside(diagonal) and not self._blocked(opponent, diagonal):
                    moves.append(diagonal)
        return moves

    def _can_place_wall(self, action: PlaceWall) -> bool:
        self._ensure_wall_index()
        wall = Wall(action.row, action.col, action.orientation)
        if not 0 <= wall.row < WALL_SIZE or not 0 <= wall.col < WALL_SIZE:
            return False
        if self._wall_conflicts(wall):
            return False
        self.state.walls.append(wall)
        target = self._horizontal_walls if wall.orientation == "HORIZONTAL" else self._vertical_walls
        target.add((wall.row, wall.col))
        valid = self._has_path("P1") and self._has_path("P2")
        self.state.walls.pop()
        target.remove((wall.row, wall.col))
        return valid

    def _wall_conflicts(self, wall: Wall) -> bool:
        position = (wall.row, wall.col)
        if wall.orientation == "HORIZONTAL":
            return position in self._vertical_walls or any(
                (wall.row, col) in self._horizontal_walls
                for col in (wall.col - 1, wall.col, wall.col + 1)
            )
        return position in self._horizontal_walls or any(
            (row, wall.col) in self._vertical_walls
            for row in (wall.row - 1, wall.row, wall.row + 1)
        )

    def _has_path(self, player: str) -> bool:
        return bool(self.shortest_path(player))

    def _blocked(self, first: Position, second: Position) -> bool:
        self._ensure_wall_index()
        if first.row == second.row:
            left_col = min(first.col, second.col)
            return (first.row, left_col) in self._vertical_walls or (
                first.row - 1,
                left_col,
            ) in self._vertical_walls
        top_row = min(first.row, second.row)
        return (top_row, first.col) in self._horizontal_walls or (
            top_row,
            first.col - 1,
        ) in self._horizontal_walls

    @staticmethod
    def _inside(position: Position) -> bool:
        return 0 <= position.row < BOARD_SIZE and 0 <= position.col < BOARD_SIZE
