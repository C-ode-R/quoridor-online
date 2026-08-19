from __future__ import annotations

from dataclasses import dataclass
import random

import numpy as np
import torch

from .encoding import encode_state, reflect_observation, reflect_policy
from .env import QuoridorEnv
from .mcts import MCTS
from .model import PolicyValueNet


@dataclass(slots=True)
class TrainingExample:
    observation: np.ndarray
    policy: np.ndarray
    value: float
    policy_weight: float = 1.0


def play_game(mcts: MCTS, *, temperature_moves: int = 16) -> list[TrainingExample]:
    examples, _winner, _reason = play_game_with_result(mcts, temperature_moves=temperature_moves)
    return examples


def play_game_with_result(
    mcts: MCTS,
    *,
    temperature_moves: int = 16,
    opponent_mcts: MCTS | None = None,
    current_player: str | None = None,
    opponent_policy_weight: float = 1.0,
) -> tuple[list[TrainingExample], str | None, str | None]:
    env = QuoridorEnv()
    if opponent_mcts is None:
        env.reset(first_player="P1" if np.random.random() < 0.5 else "P2")
    else:
        if current_player not in ("P1", "P2"):
            raise ValueError("current_player must be P1 or P2 for league games")
        env.reset(first_player="P1")
    mcts.reset_tree()
    if opponent_mcts is not None:
        opponent_mcts.reset_tree()
    history: list[tuple[np.ndarray, np.ndarray, str, float]] = []

    while not env.state.done:
        player = env.state.turn
        temperature = 1.0 if env.state.move_count < temperature_moves else 0.05
        search = (
            mcts
            if opponent_mcts is None or player == current_player
            else opponent_mcts
        )
        action, policy = search.search(env, temperature=temperature, add_noise=True)
        policy_weight = (
            opponent_policy_weight
            if opponent_mcts is not None and player != current_player
            else 1.0
        )
        history.append((encode_state(env.state), policy, player, policy_weight))
        env.step(action)

    winner = env.state.winner
    examples: list[TrainingExample] = []
    for observation, policy, player, policy_weight in history:
        value = 0.0 if winner is None else (1.0 if winner == player else -1.0)
        examples.append(
            TrainingExample(
                observation=observation,
                policy=policy,
                value=value,
                policy_weight=policy_weight,
            )
        )
        examples.append(
            TrainingExample(
                observation=reflect_observation(observation),
                policy=reflect_policy(policy),
                value=value,
                policy_weight=policy_weight,
            )
        )
    return examples, winner, env.state.termination_reason


def generate_games(
    checkpoint: dict,
    *,
    games: int,
    simulations: int,
    wall_candidates: int,
    temperature_moves: int,
    heuristic_weight: float,
    seed: int,
    threads: int = 1,
    opponent_checkpoint: dict | None = None,
    current_player: str | None = None,
    opponent_policy_weight: float = 1.0,
) -> tuple[
    list[TrainingExample],
    list[int],
    list[str | None],
    list[str | None],
    dict[str, int],
]:
    """Process-safe self-play worker used by CPU training."""
    np.random.seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, threads))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    model = PolicyValueNet.from_checkpoint(checkpoint, device="cpu")
    model.eval()
    mcts = MCTS(
        model,
        simulations=simulations,
        device="cpu",
        wall_candidates=wall_candidates,
        heuristic_weight=heuristic_weight,
    )
    opponent_mcts: MCTS | None = None
    if opponent_checkpoint is not None:
        opponent_model = PolicyValueNet.from_checkpoint(
            opponent_checkpoint, device="cpu"
        )
        opponent_model.eval()
        opponent_mcts = MCTS(
            opponent_model,
            simulations=simulations,
            device="cpu",
            wall_candidates=wall_candidates,
            heuristic_weight=heuristic_weight,
        )
    examples: list[TrainingExample] = []
    lengths: list[int] = []
    winners: list[str | None] = []
    reasons: list[str | None] = []
    for _ in range(games):
        game_examples, winner, reason = play_game_with_result(
            mcts,
            temperature_moves=temperature_moves,
            opponent_mcts=opponent_mcts,
            current_player=current_player,
            opponent_policy_weight=opponent_policy_weight,
        )
        examples.extend(game_examples)
        lengths.append(len(game_examples) // 2)
        winners.append(winner)
        reasons.append(reason)
    searches = (mcts,) if opponent_mcts is None else (mcts, opponent_mcts)
    return examples, lengths, winners, reasons, {
        "cache_hits": sum(search.cache_hits for search in searches),
        "cache_misses": sum(search.cache_misses for search in searches),
        "reused_roots": sum(search.reused_roots for search in searches),
    }
