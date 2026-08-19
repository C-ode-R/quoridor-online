import unittest

from quoridor_sdk import MovePawn, Position, Wall, horizontal_wall, move, vertical_wall
from quoridor_rl.env import LocalState, QuoridorEnv


class EnvironmentTests(unittest.TestCase):
    def test_standard_start(self):
        env = QuoridorEnv()
        self.assertEqual(env.state.pawns["P1"], Position(8, 4))
        self.assertEqual(env.state.walls_remaining, {"P1": 10, "P2": 10})
        self.assertIn(move(7, 4), env.legal_actions())

    def test_move_changes_turn(self):
        env = QuoridorEnv()
        state, reward, done = env.step(move(7, 4))
        self.assertEqual(state.turn, "P2")
        self.assertEqual(reward, 0.0)
        self.assertFalse(done)

    def test_wall_is_applied(self):
        env = QuoridorEnv()
        env.step(horizontal_wall(7, 4))
        self.assertEqual(env.state.walls_remaining["P1"], 9)
        self.assertNotIn(move(7, 4), env.legal_actions("P1"))

    def test_crossing_wall_is_illegal(self):
        env = QuoridorEnv()
        env.step(horizontal_wall(3, 3))
        self.assertNotIn(vertical_wall(3, 3), env.legal_actions("P2"))

    def test_straight_jump(self):
        env = QuoridorEnv()
        env.state = LocalState(
            turn="P1",
            pawns={"P1": Position(4, 4), "P2": Position(3, 4)},
            walls_remaining={"P1": 10, "P2": 10},
            walls=[],
        )
        moves = [action for action in env.legal_actions() if isinstance(action, MovePawn)]
        self.assertIn(move(2, 4), moves)

    def test_diagonal_when_jump_blocked(self):
        env = QuoridorEnv()
        env.state = LocalState(
            turn="P1",
            pawns={"P1": Position(4, 4), "P2": Position(3, 4)},
            walls_remaining={"P1": 10, "P2": 10},
            walls=[],
        )
        env.state.walls.append(Wall(2, 4, "HORIZONTAL"))
        moves = [action for action in env.legal_actions() if isinstance(action, MovePawn)]
        self.assertIn(move(3, 3), moves)
        self.assertIn(move(3, 5), moves)

    def test_search_actions_are_legal_and_bounded(self):
        env = QuoridorEnv()
        search_actions = env.search_actions(max_wall_candidates=6)
        legal_actions = env.legal_actions()
        self.assertTrue(set(search_actions).issubset(set(legal_actions)))
        wall_count = sum(not isinstance(action, MovePawn) for action in search_actions)
        self.assertLessEqual(wall_count, 6)

    def test_shortest_path_reaches_goal(self):
        env = QuoridorEnv()
        path = env.shortest_path("P1")
        self.assertEqual(path[0], Position(8, 4))
        self.assertEqual(path[-1].row, 0)
        self.assertEqual(len(path) - 1, 8)

    def test_move_limit_adjudicates_a_better_position(self):
        env = QuoridorEnv(max_moves=1)
        state, _reward, done = env.step(move(7, 4))
        self.assertTrue(done)
        self.assertEqual(state.winner, "P1")

    def test_threefold_repetition_finishes_game(self):
        env = QuoridorEnv()
        cycle = [move(8, 3), move(0, 3), move(8, 4), move(0, 4)] * 2
        for action in cycle:
            state, _reward, done = env.step(action)
        self.assertTrue(done)
        self.assertEqual(state.termination_reason, "REPETITION")
        self.assertEqual(state.move_count, 8)
        self.assertEqual(state.winner, "P1")

    def test_all_initial_shortest_path_edges_are_returned(self):
        env = QuoridorEnv()
        self.assertEqual(len(env.shortest_path_edges("P1")), 8)


if __name__ == "__main__":
    unittest.main()
