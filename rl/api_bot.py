from __future__ import annotations

import argparse

import torch

from quoridor_sdk import run_bot
from quoridor_rl.adapters import env_from_snapshot
from quoridor_rl.mcts import MCTS
from quoridor_rl.model import PolicyValueNet


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a trained checkpoint on the online API")
    parser.add_argument("checkpoint")
    parser.add_argument("--name", default="RLBot")
    parser.add_argument("--server", default="https://qrd.coder.re.kr")
    parser.add_argument("--room")
    parser.add_argument("--simulations", type=int, default=200)
    parser.add_argument("--wall-candidates", type=int, default=24)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--heuristic-weight", type=float, default=0.10)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.threads))
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

    def choose_action(snapshot):
        env = env_from_snapshot(snapshot)
        action, _ = mcts.search(env, temperature=0.0)
        if action not in snapshot.game.legal_actions:
            raise RuntimeError("로컬 환경과 서버의 합법 수가 일치하지 않습니다.")
        return action

    run_bot(
        choose_action,
        nickname=args.name,
        server_url=args.server,
        room_code=args.room,
    )


if __name__ == "__main__":
    main()
