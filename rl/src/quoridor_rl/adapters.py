from __future__ import annotations

from quoridor_sdk import Snapshot

from .env import LocalState, QuoridorEnv


def env_from_snapshot(snapshot: Snapshot) -> QuoridorEnv:
    if snapshot.game is None:
        raise ValueError("Game has not started")
    game = snapshot.game
    env = QuoridorEnv()
    env.state = LocalState(
        turn=game.turn,
        pawns=dict(game.pawns),
        walls_remaining=dict(game.walls_remaining),
        walls=list(game.walls),
        winner=game.winner,
        done=game.winner is not None,
        move_count=game.version,
    )
    return env
