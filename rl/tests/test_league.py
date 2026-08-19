import unittest
from pathlib import Path

from quoridor_rl.league import (
    allocate_match_types,
    qualifies_for_promotion,
    select_history_paths,
)


class LeagueTests(unittest.TestCase):
    def test_default_eight_game_mix_is_exact(self):
        schedule = allocate_match_types(
            8, champion_available=True, history_available=True
        )
        self.assertEqual(schedule.count("current"), 4)
        self.assertEqual(schedule.count("champion"), 2)
        self.assertEqual(schedule.count("history"), 2)

    def test_missing_history_moves_games_to_champion(self):
        schedule = allocate_match_types(
            8, champion_available=True, history_available=False
        )
        self.assertEqual(schedule.count("current"), 4)
        self.assertEqual(schedule.count("champion"), 4)

    def test_no_pool_falls_back_to_current_self_play(self):
        schedule = allocate_match_types(
            7, champion_available=False, history_available=False
        )
        self.assertEqual(schedule, ["current"] * 7)

    def test_promotion_requires_both_seats(self):
        self.assertTrue(
            qualifies_for_promotion(score=0.55, p1_win_rate=0.70, p2_win_rate=0.40)
        )
        self.assertFalse(
            qualifies_for_promotion(score=0.60, p1_win_rate=1.0, p2_win_rate=0.20)
        )

    def test_history_pool_excludes_resume_and_deduplicates_iterations(self):
        paths = [
            Path("resume_000110.pt"),
            Path("champion_000100.pt"),
            Path("iteration_000100.pt"),
            Path("iteration_000110.pt"),
            Path("iteration_000120.pt"),
            Path("champion_000090.pt"),
        ]
        selected = select_history_paths(
            paths, recent_iterations=2, champion_count=2
        )
        self.assertEqual(
            [path.name for path in selected],
            [
                "champion_000100.pt",
                "champion_000090.pt",
                "iteration_000120.pt",
                "iteration_000110.pt",
            ],
        )


if __name__ == "__main__":
    unittest.main()
