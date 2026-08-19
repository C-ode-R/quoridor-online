from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, TypeAlias

PlayerId: TypeAlias = Literal["P1", "P2"]
Orientation: TypeAlias = Literal["HORIZONTAL", "VERTICAL"]
RoomStatus: TypeAlias = Literal["WAITING", "PLAYING", "FINISHED"]


@dataclass(frozen=True, slots=True)
class Position:
    row: int
    col: int

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Position:
        return cls(row=int(data["row"]), col=int(data["col"]))


@dataclass(frozen=True, slots=True)
class Wall:
    row: int
    col: int
    orientation: Orientation

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Wall:
        return cls(
            row=int(data["row"]),
            col=int(data["col"]),
            orientation=data["orientation"],
        )


@dataclass(frozen=True, slots=True)
class MovePawn:
    to: Position
    type: Literal["MOVE_PAWN"] = "MOVE_PAWN"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "to": {"row": self.to.row, "col": self.to.col}}


@dataclass(frozen=True, slots=True)
class PlaceWall:
    row: int
    col: int
    orientation: Orientation
    type: Literal["PLACE_WALL"] = "PLACE_WALL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "row": self.row,
            "col": self.col,
            "orientation": self.orientation,
        }


Action: TypeAlias = MovePawn | PlaceWall


def move(row: int, col: int) -> MovePawn:
    return MovePawn(Position(row, col))


def horizontal_wall(row: int, col: int) -> PlaceWall:
    return PlaceWall(row=row, col=col, orientation="HORIZONTAL")


def vertical_wall(row: int, col: int) -> PlaceWall:
    return PlaceWall(row=row, col=col, orientation="VERTICAL")


def action_from_dict(data: Mapping[str, Any]) -> Action:
    if data.get("type") == "MOVE_PAWN":
        return MovePawn(Position.from_dict(data["to"]))
    if data.get("type") == "PLACE_WALL":
        return PlaceWall(
            row=int(data["row"]),
            col=int(data["col"]),
            orientation=data["orientation"],
        )
    raise ValueError(f"Unknown action type: {data.get('type')!r}")


@dataclass(frozen=True, slots=True)
class Player:
    id: PlayerId
    nickname: str
    client_type: Literal["HUMAN", "BOT"]
    connected: bool
    rematch_ready: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Player:
        return cls(
            id=data["id"],
            nickname=str(data["nickname"]),
            client_type=data["clientType"],
            connected=bool(data["connected"]),
            rematch_ready=bool(data["rematchReady"]),
        )


@dataclass(frozen=True, slots=True)
class GameState:
    version: int
    turn: PlayerId
    pawns: Mapping[PlayerId, Position]
    walls_remaining: Mapping[PlayerId, int]
    walls: tuple[Wall, ...]
    winner: PlayerId | None
    turn_deadline: str | None
    finish_reason: Literal["GOAL", "TIMEOUT"] | None
    legal_actions: tuple[Action, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GameState:
        return cls(
            version=int(data["version"]),
            turn=data["turn"],
            pawns={key: Position.from_dict(value) for key, value in data["pawns"].items()},
            walls_remaining={key: int(value) for key, value in data["wallsRemaining"].items()},
            walls=tuple(Wall.from_dict(item) for item in data["walls"]),
            winner=data.get("winner"),
            turn_deadline=data.get("turnDeadline"),
            finish_reason=data.get("finishReason"),
            legal_actions=tuple(action_from_dict(item) for item in data.get("legalActions", [])),
        )

    @property
    def seconds_left(self) -> float | None:
        if not self.turn_deadline:
            return None
        deadline = datetime.fromisoformat(self.turn_deadline.replace("Z", "+00:00"))
        return max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())


@dataclass(frozen=True, slots=True)
class Snapshot:
    room_code: str
    status: RoomStatus
    game_id: str | None
    me: PlayerId
    players: tuple[Player, ...]
    game: GameState | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Snapshot:
        return cls(
            room_code=str(data["roomCode"]),
            status=data["status"],
            game_id=data.get("gameId"),
            me=data["me"],
            players=tuple(Player.from_dict(item) for item in data["players"]),
            game=GameState.from_dict(data["game"]) if data.get("game") else None,
        )

    @property
    def is_my_turn(self) -> bool:
        return self.status == "PLAYING" and self.game is not None and self.game.turn == self.me

    @property
    def opponent(self) -> Player | None:
        return next((player for player in self.players if player.id != self.me), None)


@dataclass(frozen=True, slots=True)
class Session:
    room_code: str
    player_token: str
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class MatchResult:
    room_code: str
    player_id: PlayerId
    winner: PlayerId | None
    finish_reason: Literal["GOAL", "TIMEOUT"] | None

    @property
    def won(self) -> bool:
        return self.winner == self.player_id
