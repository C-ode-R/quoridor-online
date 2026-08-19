from __future__ import annotations

import random
from typing import Protocol

from quoridor_sdk import Action, MovePawn

from .env import QuoridorEnv, other


class Agent(Protocol):
    def choose(self, env: QuoridorEnv) -> Action: ...


class RandomAgent:
    def __init__(self, *, wall_candidates: int = 24):
        self.wall_candidates = wall_candidates

    def choose(self, env: QuoridorEnv) -> Action:
        return random.choice(env.search_actions(max_wall_candidates=self.wall_candidates))


class GreedyPathAgent:
    """CPU-cheap BFS baseline that balances progress and blocking."""

    def __init__(self, *, wall_candidates: int = 24):
        self.wall_candidates = wall_candidates

    def choose(self, env: QuoridorEnv) -> Action:
        player = env.state.turn
        opponent = other(player)
        best_action: Action | None = None
        best_score = float("-inf")
        actions = env.search_actions(max_wall_candidates=self.wall_candidates)
        for action in actions:
            simulation = env.clone()
            simulation.step(action, validate=False)
            if simulation.state.winner == player:
                return action
            my_distance = len(simulation.shortest_path(player)) - 1
            opponent_distance = len(simulation.shortest_path(opponent)) - 1
            # Prefer forward progress slightly over spending a wall for an equal score.
            score = opponent_distance - my_distance
            if isinstance(action, MovePawn):
                score += 0.05
            if score > best_score:
                best_score = score
                best_action = action
        if best_action is None:
            raise RuntimeError("No action available")
        return best_action
