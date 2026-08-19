import unittest

import torch

from quoridor_sdk import Position, move
from quoridor_rl.encoding import ACTION_SIZE
from quoridor_rl.env import LocalState, QuoridorEnv
from quoridor_rl.mcts import MCTS, Node


class ZeroModel(torch.nn.Module):
    def forward(self, inputs):
        return torch.zeros((inputs.shape[0], ACTION_SIZE)), torch.zeros(inputs.shape[0])


class MCTSTests(unittest.TestCase):
    def test_root_considers_every_legal_action(self):
        env = QuoridorEnv()
        mcts = MCTS(ZeroModel(), simulations=2, wall_candidates=1, heuristic_weight=0.0)
        root = Node(prior=1.0)
        mcts._expand(root, env, full_expansion=True)
        self.assertEqual(set(root.children), set(env.legal_actions()))
        self.assertTrue(root.fully_expanded)

    def test_reused_internal_node_is_widened_when_it_becomes_root(self):
        env = QuoridorEnv()
        mcts = MCTS(ZeroModel(), simulations=8, wall_candidates=2, heuristic_weight=0.0)
        action, _ = mcts.search(env, temperature=0.0)
        promoted_root = mcts._root
        env.step(action)
        legal_at_promoted_root = set(env.legal_actions())
        mcts.search(env, temperature=0.0)
        self.assertIsNotNone(promoted_root)
        self.assertTrue(promoted_root.fully_expanded)
        self.assertEqual(set(promoted_root.children), legal_at_promoted_root)

    def test_selects_immediate_win_and_reuses_selected_root(self):
        env = QuoridorEnv()
        env.state = LocalState(
            turn="P2",
            pawns={"P1": Position(4, 4), "P2": Position(7, 4)},
            walls_remaining={"P1": 0, "P2": 0},
            walls=[],
        )
        mcts = MCTS(ZeroModel(), simulations=50, wall_candidates=0, heuristic_weight=0.0)
        action, _policy = mcts.search(env, temperature=0.0)
        self.assertEqual(action, move(8, 4))
        env.step(action)
        self.assertEqual(mcts._root_key, env.search_key())


if __name__ == "__main__":
    unittest.main()
