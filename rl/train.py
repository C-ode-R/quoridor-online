from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
import os
import random
import signal
import shutil
import time
from pathlib import Path

import numpy as np
import torch

from quoridor_rl.arena import (
    combine_results,
    evaluate_checkpoint_pair,
    evaluate_checkpoint_vs_greedy,
)
from quoridor_rl.league import (
    allocate_match_types,
    qualifies_for_promotion,
    select_history_paths,
)
from quoridor_rl.model import PolicyValueNet
from quoridor_rl.self_play import generate_games
from quoridor_rl.training import ReplayBuffer, train_steps


def atomic_torch_save(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def append_metric(path: Path, metric: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(metric, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="CPU-optimized Quoridor self-play trainer")
    parser.add_argument("--iterations", type=int, default=100, help="이번 실행에서 추가할 반복 수")
    parser.add_argument("--games", type=int, default=8, help="iteration당 자기대국 수")
    parser.add_argument("--simulations", type=int, default=50, help="한 수당 MCTS 횟수")
    parser.add_argument("--wall-candidates", type=int, default=24)
    parser.add_argument("--temperature-moves", type=int, default=16)
    parser.add_argument("--heuristic-start", type=float, default=0.65)
    parser.add_argument("--heuristic-end", type=float, default=0.10)
    parser.add_argument("--heuristic-decay", type=int, default=100)
    parser.add_argument("--train-steps", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--replay-capacity", type=int, default=50_000)
    parser.add_argument("--channels", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=3)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--learning-rate-mid", type=float, default=3e-4)
    parser.add_argument("--learning-rate-final", type=float, default=1e-4)
    parser.add_argument("--lr-mid-iteration", type=int, default=100)
    parser.add_argument("--lr-final-iteration", type=int, default=250)
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--workers", type=int, default=1, help="병렬 자기대국 프로세스 수")
    parser.add_argument("--device", default="cpu", choices=("cpu",))
    parser.add_argument("--output", default="checkpoints/quoridor_latest.pt")
    parser.add_argument("--best-output", default="checkpoints/quoridor_best.pt")
    parser.add_argument("--league-dir", default="checkpoints/league")
    parser.add_argument("--snapshot-every", type=int, default=10)
    parser.add_argument("--max-snapshots", type=int, default=12)
    parser.add_argument("--league-current-weight", type=float, default=0.50)
    parser.add_argument("--league-champion-weight", type=float, default=0.30)
    parser.add_argument("--league-history-weight", type=float, default=0.20)
    parser.add_argument("--history-recent-snapshots", type=int, default=6)
    parser.add_argument("--history-champions", type=int, default=3)
    parser.add_argument("--replay", default="replay/quoridor_replay.npz")
    parser.add_argument("--replay-recent-fraction", type=float, default=0.60)
    parser.add_argument("--replay-recent-window", type=int, default=30_000)
    parser.add_argument("--metrics", default="metrics/training.jsonl")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--save-replay-every", type=int, default=1)
    parser.add_argument("--eval-every", type=int, default=10)
    parser.add_argument("--eval-games", type=int, default=20)
    parser.add_argument("--eval-random-games", type=int, default=20)
    parser.add_argument("--eval-fixed-seed", type=int, default=20_260_818)
    parser.add_argument("--eval-simulations", type=int, default=30)
    parser.add_argument("--eval-opening-plies", type=int, default=2)
    parser.add_argument("--promotion-games", type=int, default=40)
    parser.add_argument("--promotion-random-games", type=int, default=40)
    parser.add_argument("--promotion-score", type=float, default=0.60)
    parser.add_argument("--promotion-seat-win-rate", type=float, default=0.45)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    def request_stop(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)

    def learning_rate_for_iteration(iteration: int) -> float:
        if iteration >= args.lr_final_iteration:
            return args.learning_rate_final
        if iteration >= args.lr_mid_iteration:
            return args.learning_rate_mid
        return args.learning_rate

    if args.iterations < 1 or args.games < 1 or args.simulations < 1:
        parser.error("iterations, games, simulations는 1 이상이어야 합니다")
    if args.eval_games < 2 or args.eval_games % 2 != 0:
        parser.error("eval-games는 선후공 쌍을 위해 2 이상의 짝수여야 합니다")
    if args.eval_random_games < 2 or args.eval_random_games % 2 != 0:
        parser.error("eval-random-games는 선후공 쌍을 위해 2 이상의 짝수여야 합니다")
    if args.promotion_games < 2 or args.promotion_games % 2 != 0:
        parser.error("promotion-games는 선후공 쌍을 위해 2 이상의 짝수여야 합니다")
    if args.promotion_random_games < 2 or args.promotion_random_games % 2 != 0:
        parser.error(
            "promotion-random-games는 선후공 쌍을 위해 2 이상의 짝수여야 합니다"
        )
    torch.set_num_threads(max(1, args.threads))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    output = Path(args.output)
    best_output = Path(args.best_output)
    league_dir = Path(args.league_dir)
    replay_path = Path(args.replay)
    metrics_path = Path(args.metrics)
    completed_iteration = 0
    best_score = -1.0
    champion_iteration = 0
    promotion_count = 0

    if args.resume and output.exists():
        checkpoint = torch.load(output, map_location="cpu", weights_only=False)
        model = PolicyValueNet.from_checkpoint(checkpoint, device="cpu")
        optimizer = torch.optim.AdamW(
            model.parameters(), lr=args.learning_rate, weight_decay=1e-4
        )
        if "optimizer" in checkpoint:
            optimizer.load_state_dict(checkpoint["optimizer"])
        completed_iteration = int(checkpoint.get("iteration", 0))
        best_score = float(checkpoint.get("best_score", -1.0))
        champion_iteration = int(checkpoint.get("champion_iteration", 0))
        promotion_count = int(checkpoint.get("promotion_count", 0))
        if "numpy_rng" in checkpoint:
            np.random.set_state(checkpoint["numpy_rng"])
        if "python_rng" in checkpoint:
            random.setstate(checkpoint["python_rng"])
        if "torch_rng" in checkpoint:
            torch.set_rng_state(checkpoint["torch_rng"])
        print(f"resumed checkpoint={output} iteration={completed_iteration}", flush=True)
    else:
        model = PolicyValueNet(channels=args.channels, blocks=args.blocks).to("cpu")
        optimizer = torch.optim.AdamW(
            model.parameters(), lr=args.learning_rate, weight_decay=1e-4
        )

    if best_output.exists():
        champion_checkpoint = torch.load(best_output, map_location="cpu", weights_only=False)
        champion_iteration = int(champion_checkpoint.get("iteration", champion_iteration))

    if args.resume and replay_path.exists():
        replay = ReplayBuffer.load(replay_path, capacity=args.replay_capacity)
        print(f"resumed replay={replay_path} examples={len(replay)}", flush=True)
    else:
        replay = ReplayBuffer(capacity=args.replay_capacity)

    latest_metrics: dict[str, float | int] = {}
    start_iteration = completed_iteration

    def copy_snapshot(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)

    def save_league_snapshot(source: Path, iteration: int, *, prefix: str = "iteration") -> Path:
        destination = league_dir / f"{prefix}_{iteration:06d}.pt"
        if not destination.exists():
            copy_snapshot(source, destination)
        snapshots = sorted(league_dir.glob("iteration_*.pt"))
        for stale in snapshots[: max(0, len(snapshots) - args.max_snapshots)]:
            stale.unlink()
        return destination

    if args.resume and output.exists() and completed_iteration > 0:
        save_league_snapshot(output, completed_iteration, prefix="resume")
    if best_output.exists() and champion_iteration > 0:
        save_league_snapshot(best_output, champion_iteration, prefix="champion")

    def save_checkpoint(iteration: int) -> None:
        atomic_torch_save(
            {
                **model.checkpoint(),
                "iteration": iteration,
                "optimizer": optimizer.state_dict(),
                "metrics": latest_metrics,
                "best_score": best_score,
                "champion_iteration": champion_iteration,
                "promotion_count": promotion_count,
                "numpy_rng": np.random.get_state(),
                "python_rng": random.getstate(),
                "torch_rng": torch.get_rng_state(),
                "training_config": vars(args),
            },
            output,
        )

    try:
        for offset in range(1, args.iterations + 1):
            iteration = start_iteration + offset
            started = time.monotonic()
            learning_rate = learning_rate_for_iteration(iteration)
            for parameter_group in optimizer.param_groups:
                parameter_group["lr"] = learning_rate
            model.eval()
            decay_progress = min(1.0, max(0.0, iteration / max(1, args.heuristic_decay)))
            heuristic_weight = (
                args.heuristic_start
                + (args.heuristic_end - args.heuristic_start) * decay_progress
            )
            lengths: list[int] = []
            winners: list[str | None] = []
            termination_reasons: list[str | None] = []
            search_stats = {"cache_hits": 0, "cache_misses": 0, "reused_roots": 0}
            suppressed_policy_examples = 0
            champion_checkpoint = (
                torch.load(best_output, map_location="cpu", weights_only=False)
                if best_output.exists()
                else None
            )
            history_paths = select_history_paths(
                list(league_dir.glob("*.pt")) if league_dir.exists() else [],
                recent_iterations=args.history_recent_snapshots,
                champion_count=args.history_champions,
            )
            match_types = allocate_match_types(
                args.games,
                champion_available=champion_checkpoint is not None,
                history_available=bool(history_paths),
                current_weight=args.league_current_weight,
                champion_weight=args.league_champion_weight,
                history_weight=args.league_history_weight,
            )
            match_counts = {
                kind: match_types.count(kind)
                for kind in ("current", "champion", "history")
            }
            match_specs: list[tuple[str, dict | None, str | None, float]] = []
            source_game_numbers = {"champion": 0, "history": 0}
            history_cache: dict[Path, dict] = {}
            for kind in match_types:
                opponent_checkpoint: dict | None = None
                current_player: str | None = None
                opponent_policy_weight = 1.0
                if kind == "champion":
                    opponent_checkpoint = champion_checkpoint
                elif kind == "history":
                    history_path = random.choice(history_paths)
                    if history_path not in history_cache:
                        history_cache[history_path] = torch.load(
                            history_path, map_location="cpu", weights_only=False
                        )
                    opponent_checkpoint = history_cache[history_path]
                    opponent_policy_weight = 0.0
                if opponent_checkpoint is not None:
                    source_game_number = source_game_numbers[kind]
                    current_player = "P1" if source_game_number % 2 == 0 else "P2"
                    source_game_numbers[kind] += 1
                match_specs.append(
                    (
                        kind,
                        opponent_checkpoint,
                        current_player,
                        opponent_policy_weight,
                    )
                )

            workers = min(max(1, args.workers), args.games)
            if workers == 1:
                for game_number, (
                    kind,
                    opponent_checkpoint,
                    current_player,
                    opponent_policy_weight,
                ) in enumerate(match_specs, start=1):
                    (
                        examples,
                        worker_lengths,
                        worker_winners,
                        worker_reasons,
                        worker_stats,
                    ) = generate_games(
                        model.checkpoint(),
                        games=1,
                        simulations=args.simulations,
                        wall_candidates=args.wall_candidates,
                        temperature_moves=args.temperature_moves,
                        heuristic_weight=heuristic_weight,
                        seed=args.seed + iteration * 10_000 + game_number,
                        threads=max(1, args.threads),
                        opponent_checkpoint=opponent_checkpoint,
                        current_player=current_player,
                        opponent_policy_weight=opponent_policy_weight,
                    )
                    suppressed_policy_examples += sum(
                        example.policy_weight <= 0.0 for example in examples
                    )
                    replay.extend(examples)
                    lengths.extend(worker_lengths)
                    winners.extend(worker_winners)
                    termination_reasons.extend(worker_reasons)
                    for key in search_stats:
                        search_stats[key] += worker_stats[key]
                    print(
                        f"iteration={iteration} selfplay={game_number}/{args.games} "
                        f"source={kind} moves={worker_lengths[0]} replay={len(replay)}",
                        flush=True,
                    )
            else:
                context = multiprocessing.get_context("spawn")
                pool = ProcessPoolExecutor(max_workers=workers, mp_context=context)
                futures = []
                try:
                    futures = {}
                    for game_index, (
                        kind,
                        opponent_checkpoint,
                        current_player,
                        opponent_policy_weight,
                    ) in enumerate(match_specs):
                        future = pool.submit(
                            generate_games,
                            model.checkpoint(),
                            games=1,
                            simulations=args.simulations,
                            wall_candidates=args.wall_candidates,
                            temperature_moves=args.temperature_moves,
                            heuristic_weight=heuristic_weight,
                            seed=args.seed + iteration * 10_000 + game_index,
                            threads=max(1, args.threads // workers),
                            opponent_checkpoint=opponent_checkpoint,
                            current_player=current_player,
                            opponent_policy_weight=opponent_policy_weight,
                        )
                        futures[future] = kind
                    finished_games = 0
                    for future in as_completed(futures):
                        kind = futures[future]
                        (
                            examples,
                            worker_lengths,
                            worker_winners,
                            worker_reasons,
                            worker_stats,
                        ) = future.result()
                        suppressed_policy_examples += sum(
                            example.policy_weight <= 0.0 for example in examples
                        )
                        replay.extend(examples)
                        lengths.extend(worker_lengths)
                        winners.extend(worker_winners)
                        termination_reasons.extend(worker_reasons)
                        for key in search_stats:
                            search_stats[key] += worker_stats[key]
                        finished_games += len(worker_lengths)
                        print(
                            f"iteration={iteration} selfplay={finished_games}/{args.games} "
                            f"source={kind} workers={workers} replay={len(replay)}",
                            flush=True,
                        )
                except BaseException:
                    for future in futures:
                        future.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise
                else:
                    pool.shutdown()

            latest_metrics = train_steps(
                model,
                optimizer,
                replay,
                steps=args.train_steps,
                batch_size=args.batch_size,
                device="cpu",
                recent_fraction=args.replay_recent_fraction,
                recent_window=args.replay_recent_window,
            )
            latest_metrics.update(
                iteration=iteration,
                average_moves=sum(lengths) / len(lengths),
                replay_size=len(replay),
                elapsed_seconds=time.monotonic() - started,
                selfplay_p1_wins=winners.count("P1"),
                selfplay_p2_wins=winners.count("P2"),
                selfplay_draws=winners.count(None),
                selfplay_goal_finishes=termination_reasons.count("GOAL"),
                selfplay_repetitions=termination_reasons.count("REPETITION"),
                selfplay_move_limits=termination_reasons.count("MOVE_LIMIT"),
                league_current_games=match_counts["current"],
                league_champion_games=match_counts["champion"],
                league_history_games=match_counts["history"],
                league_history_pool_size=len(history_paths),
                suppressed_policy_examples=suppressed_policy_examples,
                learning_rate=learning_rate,
                heuristic_weight=heuristic_weight,
                mcts_cache_hits=search_stats["cache_hits"],
                mcts_cache_misses=search_stats["cache_misses"],
                mcts_reused_roots=search_stats["reused_roots"],
            )

            promoted = False
            if args.eval_every > 0 and iteration % args.eval_every == 0:
                evaluation_started = time.monotonic()
                model.eval()
                candidate_checkpoint = model.checkpoint()
                champion_checkpoint = (
                    torch.load(best_output, map_location="cpu", weights_only=False)
                    if best_output.exists()
                    else None
                )
                evaluation_jobs = (
                    args.eval_games + args.eval_random_games
                ) // 2
                if champion_checkpoint is not None:
                    evaluation_jobs += (
                        args.promotion_games + args.promotion_random_games
                    ) // 2
                evaluation_workers = min(max(1, args.workers), evaluation_jobs)
                context = multiprocessing.get_context("spawn")
                pool = ProcessPoolExecutor(
                    max_workers=evaluation_workers, mp_context=context
                )
                evaluation_futures = {}
                try:
                    for pair_number in range(args.eval_games // 2):
                        future = pool.submit(
                            evaluate_checkpoint_vs_greedy,
                            candidate_checkpoint,
                            simulations=args.eval_simulations,
                            wall_candidates=args.wall_candidates,
                            heuristic_weight=args.heuristic_end,
                            seed=args.eval_fixed_seed + pair_number * 104_729,
                            opening_plies=args.eval_opening_plies,
                            threads=max(1, args.threads // evaluation_workers),
                        )
                        evaluation_futures[future] = "baseline_fixed"
                    for pair_number in range(args.eval_random_games // 2):
                        future = pool.submit(
                            evaluate_checkpoint_vs_greedy,
                            candidate_checkpoint,
                            simulations=args.eval_simulations,
                            wall_candidates=args.wall_candidates,
                            heuristic_weight=args.heuristic_end,
                            seed=args.seed
                            + iteration * 1_003
                            + pair_number * 104_729,
                            opening_plies=args.eval_opening_plies,
                            threads=max(1, args.threads // evaluation_workers),
                        )
                        evaluation_futures[future] = "baseline_random"
                    if champion_checkpoint is not None:
                        for pair_number in range(args.promotion_games // 2):
                            future = pool.submit(
                                evaluate_checkpoint_pair,
                                candidate_checkpoint,
                                champion_checkpoint,
                                simulations=args.eval_simulations,
                                wall_candidates=args.wall_candidates,
                                heuristic_weight=args.heuristic_end,
                                seed=args.eval_fixed_seed + pair_number * 104_729,
                                opening_plies=args.eval_opening_plies,
                                threads=max(1, args.threads // evaluation_workers),
                            )
                            evaluation_futures[future] = "champion_fixed"
                        for pair_number in range(
                            args.promotion_random_games // 2
                        ):
                            future = pool.submit(
                                evaluate_checkpoint_pair,
                                candidate_checkpoint,
                                champion_checkpoint,
                                simulations=args.eval_simulations,
                                wall_candidates=args.wall_candidates,
                                heuristic_weight=args.heuristic_end,
                                seed=args.seed
                                + iteration * 7_919
                                + pair_number * 104_729,
                                opening_plies=args.eval_opening_plies,
                                threads=max(1, args.threads // evaluation_workers),
                            )
                            evaluation_futures[future] = "champion_random"
                    evaluation_results = {
                        "baseline_fixed": [],
                        "baseline_random": [],
                        "champion_fixed": [],
                        "champion_random": [],
                    }
                    for future in as_completed(evaluation_futures):
                        evaluation_results[evaluation_futures[future]].append(
                            future.result()
                        )
                except BaseException:
                    for future in evaluation_futures:
                        future.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise
                else:
                    pool.shutdown()

                baseline_fixed_evaluation = combine_results(
                    evaluation_results["baseline_fixed"]
                )
                baseline_random_evaluation = combine_results(
                    evaluation_results["baseline_random"]
                )
                baseline_evaluation = combine_results(
                    [baseline_fixed_evaluation, baseline_random_evaluation]
                )
                latest_metrics.update(
                    eval_wins=baseline_evaluation.wins,
                    eval_losses=baseline_evaluation.losses,
                    eval_draws=baseline_evaluation.draws,
                    eval_win_rate=baseline_evaluation.win_rate,
                    eval_p1_win_rate=baseline_evaluation.p1_win_rate,
                    eval_p2_win_rate=baseline_evaluation.p2_win_rate,
                    eval_fixed_win_rate=baseline_fixed_evaluation.win_rate,
                    eval_fixed_p1_win_rate=baseline_fixed_evaluation.p1_win_rate,
                    eval_fixed_p2_win_rate=baseline_fixed_evaluation.p2_win_rate,
                    eval_random_win_rate=baseline_random_evaluation.win_rate,
                    eval_random_p1_win_rate=baseline_random_evaluation.p1_win_rate,
                    eval_random_p2_win_rate=baseline_random_evaluation.p2_win_rate,
                )
                if champion_checkpoint is not None:
                    champion_fixed_evaluation = combine_results(
                        evaluation_results["champion_fixed"]
                    )
                    champion_random_evaluation = combine_results(
                        evaluation_results["champion_random"]
                    )
                    champion_evaluation = combine_results(
                        [champion_fixed_evaluation, champion_random_evaluation]
                    )
                    latest_metrics.update(
                        champion_eval_wins=champion_evaluation.wins,
                        champion_eval_losses=champion_evaluation.losses,
                        champion_eval_draws=champion_evaluation.draws,
                        champion_eval_score=champion_evaluation.score,
                        champion_eval_p1_win_rate=champion_evaluation.p1_win_rate,
                        champion_eval_p2_win_rate=champion_evaluation.p2_win_rate,
                        champion_eval_fixed_score=champion_fixed_evaluation.score,
                        champion_eval_fixed_p1_win_rate=(
                            champion_fixed_evaluation.p1_win_rate
                        ),
                        champion_eval_fixed_p2_win_rate=(
                            champion_fixed_evaluation.p2_win_rate
                        ),
                        champion_eval_random_score=champion_random_evaluation.score,
                        champion_eval_random_p1_win_rate=(
                            champion_random_evaluation.p1_win_rate
                        ),
                        champion_eval_random_p2_win_rate=(
                            champion_random_evaluation.p2_win_rate
                        ),
                        champion_iteration=champion_iteration,
                    )
                    promoted = qualifies_for_promotion(
                        score=champion_evaluation.score,
                        p1_win_rate=champion_evaluation.p1_win_rate,
                        p2_win_rate=champion_evaluation.p2_win_rate,
                        minimum_score=args.promotion_score,
                        minimum_seat_win_rate=args.promotion_seat_win_rate,
                    )
                    if promoted:
                        best_score = champion_evaluation.score
                        champion_iteration = iteration
                        promotion_count += 1
                else:
                    promoted = True
                    best_score = 1.0
                    champion_iteration = iteration
                    promotion_count += 1
                latest_metrics["evaluation_seconds"] = (
                    time.monotonic() - evaluation_started
                )

            latest_metrics.update(
                promoted=int(promoted),
                active_champion_iteration=champion_iteration,
                promotion_count=promotion_count,
                iteration_seconds=time.monotonic() - started,
            )

            save_checkpoint(iteration)
            if promoted:
                copy_snapshot(output, best_output)
                save_league_snapshot(best_output, iteration, prefix="champion")
            if args.snapshot_every > 0 and iteration % args.snapshot_every == 0:
                save_league_snapshot(output, iteration)
            if args.save_replay_every > 0 and iteration % args.save_replay_every == 0:
                replay.save(replay_path)
            append_metric(metrics_path, latest_metrics)
            print(json.dumps(latest_metrics, ensure_ascii=False), flush=True)
            completed_iteration = iteration
    except KeyboardInterrupt:
        # The latest committed checkpoint/replay pair is already recoverable.
        # Saving here could label a partially trained model as the previous
        # completed iteration, so deliberately leave the atomic files intact.
        print(
            f"interrupt received; preserving committed iteration={completed_iteration}",
            flush=True,
        )
        raise SystemExit(130)


if __name__ == "__main__":
    main()
