from __future__ import annotations

import random
from dataclasses import dataclass

import torch
from quoridor_sdk import Action

from .baselines import Agent, GreedyPathAgent
from .env import QuoridorEnv
from .mcts import MCTS
from .model import PolicyValueNet


@dataclass(slots=True)
class ArenaResult:
    games: int
    wins: int
    losses: int
    draws: int
    average_moves: float
    p1_games: int = 0
    p1_wins: int = 0
    p2_games: int = 0
    p2_wins: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def score(self) -> float:
        return (self.wins + 0.5 * self.draws) / self.games if self.games else 0.0

    @property
    def p1_win_rate(self) -> float:
        return self.p1_wins / self.p1_games if self.p1_games else 0.0

    @property
    def p2_win_rate(self) -> float:
        return self.p2_wins / self.p2_games if self.p2_games else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "games": self.games,
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "win_rate": self.win_rate,
            "score": self.score,
            "average_moves": self.average_moves,
            "p1_games": self.p1_games,
            "p1_wins": self.p1_wins,
            "p1_win_rate": self.p1_win_rate,
            "p2_games": self.p2_games,
            "p2_wins": self.p2_wins,
            "p2_win_rate": self.p2_win_rate,
        }


def combine_results(results: list[ArenaResult]) -> ArenaResult:
    games = sum(result.games for result in results)
    total_moves = sum(result.average_moves * result.games for result in results)
    return ArenaResult(
        games=games,
        wins=sum(result.wins for result in results),
        losses=sum(result.losses for result in results),
        draws=sum(result.draws for result in results),
        average_moves=total_moves / games if games else 0.0,
        p1_games=sum(result.p1_games for result in results),
        p1_wins=sum(result.p1_wins for result in results),
        p2_games=sum(result.p2_games for result in results),
        p2_wins=sum(result.p2_wins for result in results),
    )


def _opening_for_pair(
    pair_number: int,
    *,
    seed: int,
    plies: int,
    wall_candidates: int,
) -> tuple[Action, ...]:
    """Create a reproducible opening that is replayed with both seat assignments."""
    env = QuoridorEnv()
    rng = random.Random(seed + pair_number * 104_729)
    opening: list[Action] = []
    for _ in range(max(0, plies)):
        if env.state.done:
            break
        actions = list(env.search_actions(max_wall_candidates=wall_candidates))
        if not actions:
            break
        # Prefer the first (pawn) actions, while occasionally retaining a tactical wall.
        candidate_count = min(len(actions), 8)
        action = actions[rng.randrange(candidate_count)]
        opening.append(action)
        env.step(action, validate=False)
    return tuple(opening)


def _new_opened_game(opening: tuple[Action, ...]) -> QuoridorEnv:
    env = QuoridorEnv()
    for action in opening:
        env.step(action, validate=False)
    return env


def evaluate_mcts(
    mcts: MCTS,
    opponent: Agent,
    *,
    games: int,
    seed: int = 0,
    opening_plies: int = 2,
) -> ArenaResult:
    wins = losses = draws = total_moves = 0
    p1_games = p1_wins = p2_games = p2_wins = 0
    for game_number in range(games):
        opening = _opening_for_pair(
            game_number // 2,
            seed=seed,
            plies=opening_plies,
            wall_candidates=mcts.wall_candidates,
        )
        env = _new_opened_game(opening)
        model_player = "P1" if game_number % 2 == 0 else "P2"
        mcts.reset_tree()
        while not env.state.done:
            if env.state.turn == model_player:
                action, _ = mcts.search(env, temperature=0.0)
            else:
                action = opponent.choose(env)
            env.step(action, validate=False)
        total_moves += env.state.move_count
        if env.state.winner is None:
            draws += 1
        elif env.state.winner == model_player:
            wins += 1
            if model_player == "P1":
                p1_wins += 1
            else:
                p2_wins += 1
        else:
            losses += 1
        if model_player == "P1":
            p1_games += 1
        else:
            p2_games += 1
    return ArenaResult(
        games,
        wins,
        losses,
        draws,
        total_moves / games if games else 0.0,
        p1_games,
        p1_wins,
        p2_games,
        p2_wins,
    )


def evaluate_models(
    candidate: MCTS,
    champion: MCTS,
    *,
    games: int,
    seed: int = 0,
    opening_plies: int = 2,
) -> ArenaResult:
    """Evaluate a candidate against a champion using paired openings and seats."""
    wins = losses = draws = total_moves = 0
    p1_games = p1_wins = p2_games = p2_wins = 0
    wall_candidates = min(candidate.wall_candidates, champion.wall_candidates)
    for game_number in range(games):
        opening = _opening_for_pair(
            game_number // 2,
            seed=seed,
            plies=opening_plies,
            wall_candidates=wall_candidates,
        )
        env = _new_opened_game(opening)
        candidate_player = "P1" if game_number % 2 == 0 else "P2"
        candidate.reset_tree()
        champion.reset_tree()
        while not env.state.done:
            search = candidate if env.state.turn == candidate_player else champion
            action, _ = search.search(env, temperature=0.0)
            env.step(action, validate=False)
        total_moves += env.state.move_count
        if env.state.winner is None:
            draws += 1
        elif env.state.winner == candidate_player:
            wins += 1
            if candidate_player == "P1":
                p1_wins += 1
            else:
                p2_wins += 1
        else:
            losses += 1
        if candidate_player == "P1":
            p1_games += 1
        else:
            p2_games += 1
    return ArenaResult(
        games,
        wins,
        losses,
        draws,
        total_moves / games if games else 0.0,
        p1_games,
        p1_wins,
        p2_games,
        p2_wins,
    )


def evaluate_checkpoint_vs_greedy(
    checkpoint: dict,
    *,
    simulations: int,
    wall_candidates: int,
    heuristic_weight: float,
    seed: int,
    opening_plies: int,
    threads: int = 1,
) -> ArenaResult:
    """Process-safe paired baseline evaluation worker."""
    torch.set_num_threads(max(1, threads))
    model = PolicyValueNet.from_checkpoint(checkpoint, device="cpu")
    model.eval()
    return evaluate_mcts(
        MCTS(
            model,
            simulations=simulations,
            wall_candidates=wall_candidates,
            heuristic_weight=heuristic_weight,
        ),
        GreedyPathAgent(wall_candidates=wall_candidates),
        games=2,
        seed=seed,
        opening_plies=opening_plies,
    )


def evaluate_checkpoint_pair(
    candidate_checkpoint: dict,
    champion_checkpoint: dict,
    *,
    simulations: int,
    wall_candidates: int,
    heuristic_weight: float,
    seed: int,
    opening_plies: int,
    threads: int = 1,
) -> ArenaResult:
    """Process-safe paired candidate/champion evaluation worker."""
    torch.set_num_threads(max(1, threads))
    candidate_model = PolicyValueNet.from_checkpoint(candidate_checkpoint, device="cpu")
    champion_model = PolicyValueNet.from_checkpoint(champion_checkpoint, device="cpu")
    candidate_model.eval()
    champion_model.eval()
    return evaluate_models(
        MCTS(
            candidate_model,
            simulations=simulations,
            wall_candidates=wall_candidates,
            heuristic_weight=heuristic_weight,
        ),
        MCTS(
            champion_model,
            simulations=simulations,
            wall_candidates=wall_candidates,
            heuristic_weight=heuristic_weight,
        ),
        games=2,
        seed=seed,
        opening_plies=opening_plies,
    )
