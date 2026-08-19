from __future__ import annotations

import argparse
import json

import torch

from quoridor_rl.arena import evaluate_mcts
from quoridor_rl.baselines import GreedyPathAgent, RandomAgent
from quoridor_rl.mcts import MCTS
from quoridor_rl.model import PolicyValueNet


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a checkpoint against a CPU baseline")
    parser.add_argument("checkpoint")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--simulations", type=int, default=100)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--opponent", choices=("greedy", "random"), default="greedy")
    parser.add_argument("--wall-candidates", type=int, default=24)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--heuristic-weight", type=float, default=0.10)
    args = parser.parse_args()

    torch.set_num_threads(args.threads)
    checkpoint = torch.load(args.checkpoint, map_location=args.device, weights_only=False)
    model = PolicyValueNet.from_checkpoint(checkpoint, device=args.device)
    model.eval()
    mcts = MCTS(
        model,
        simulations=args.simulations,
        device=args.device,
        wall_candidates=args.wall_candidates,
        heuristic_weight=args.heuristic_weight,
    )
    opponent = (
        GreedyPathAgent(wall_candidates=args.wall_candidates)
        if args.opponent == "greedy"
        else RandomAgent(wall_candidates=args.wall_candidates)
    )
    result = evaluate_mcts(mcts, opponent, games=args.games)
    print(json.dumps({"opponent": args.opponent, **result.as_dict()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
