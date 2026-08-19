from __future__ import annotations

import numpy as np

from quoridor_sdk import Action, MovePawn, PlaceWall, Position

from .env import LocalState, other

ACTION_SIZE = 209
INPUT_CHANNELS = 10


def _rotate_position(position: Position, size: int) -> Position:
    return Position(size - 1 - position.row, size - 1 - position.col)


def encode_action(action: Action, player: str) -> int:
    if isinstance(action, MovePawn):
        position = _rotate_position(action.to, 9) if player == "P2" else action.to
        return position.row * 9 + position.col

    row, col = action.row, action.col
    if player == "P2":
        row, col = 7 - row, 7 - col
    offset = 81 if action.orientation == "HORIZONTAL" else 145
    return offset + row * 8 + col


def decode_action(index: int, player: str) -> Action:
    if not 0 <= index < ACTION_SIZE:
        raise ValueError(f"Action index out of range: {index}")
    if index < 81:
        position = Position(index // 9, index % 9)
        if player == "P2":
            position = _rotate_position(position, 9)
        return MovePawn(position)

    orientation = "HORIZONTAL" if index < 145 else "VERTICAL"
    raw = index - (81 if orientation == "HORIZONTAL" else 145)
    row, col = raw // 8, raw % 8
    if player == "P2":
        row, col = 7 - row, 7 - col
    return PlaceWall(row=row, col=col, orientation=orientation)


def encode_state(state: LocalState) -> np.ndarray:
    """Encode from the current player's canonical bottom-to-top viewpoint."""
    player = state.turn
    opponent = other(player)
    planes = np.zeros((INPUT_CHANNELS, 9, 9), dtype=np.float32)

    own_position = state.pawns[player]
    opponent_position = state.pawns[opponent]
    if player == "P2":
        own_position = _rotate_position(own_position, 9)
        opponent_position = _rotate_position(opponent_position, 9)
    planes[0, own_position.row, own_position.col] = 1.0
    planes[1, opponent_position.row, opponent_position.col] = 1.0

    for wall in state.walls:
        row, col = wall.row, wall.col
        if player == "P2":
            row, col = 7 - row, 7 - col
        channel = 2 if wall.orientation == "HORIZONTAL" else 3
        planes[channel, row, col] = 1.0

    planes[4, :, :] = state.walls_remaining[player] / 10.0
    planes[5, :, :] = state.walls_remaining[opponent] / 10.0
    planes[6, :, :] = min(state.move_count / 128.0, 1.0)

    # Explicit route planes reduce the amount of BFS geometry the small CPU
    # network must rediscover. They are still derived only from public state.
    from .env import QuoridorEnv

    route_env = QuoridorEnv()
    route_env.state = state.clone()
    for position in route_env.shortest_path(player):
        canonical = _rotate_position(position, 9) if player == "P2" else position
        planes[7, canonical.row, canonical.col] = 1.0
    for position in route_env.shortest_path(opponent):
        canonical = _rotate_position(position, 9) if player == "P2" else position
        planes[8, canonical.row, canonical.col] = 1.0
    planes[9, :, :] = min(state.repetition_count / 3.0, 1.0)
    return planes


def reflect_observation(observation: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(observation[:, :, ::-1])


def reflect_policy(policy: np.ndarray) -> np.ndarray:
    reflected = np.zeros_like(policy)
    for index, probability in enumerate(policy):
        if index < 81:
            row, col = divmod(index, 9)
            reflected[row * 9 + (8 - col)] = probability
        elif index < 145:
            raw = index - 81
            row, col = divmod(raw, 8)
            reflected[81 + row * 8 + (7 - col)] = probability
        else:
            raw = index - 145
            row, col = divmod(raw, 8)
            reflected[145 + row * 8 + (7 - col)] = probability
    return reflected


def legal_action_mask(actions: tuple[Action, ...], player: str) -> np.ndarray:
    mask = np.zeros(ACTION_SIZE, dtype=np.bool_)
    for action in actions:
        mask[encode_action(action, player)] = True
    return mask
