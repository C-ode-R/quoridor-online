import unittest

import numpy as np

from quoridor_sdk import horizontal_wall, move, vertical_wall
from quoridor_rl.encoding import (
    ACTION_SIZE,
    INPUT_CHANNELS,
    decode_action,
    encode_action,
    encode_state,
    legal_action_mask,
    reflect_observation,
    reflect_policy,
)
from quoridor_rl.env import QuoridorEnv


class EncodingTests(unittest.TestCase):
    def test_action_round_trip_for_both_players(self):
        actions = [move(7, 4), horizontal_wall(3, 4), vertical_wall(6, 1)]
        for player in ("P1", "P2"):
            for action in actions:
                self.assertEqual(decode_action(encode_action(action, player), player), action)

    def test_initial_state_is_canonical_for_current_player(self):
        p1 = QuoridorEnv.initial_state("P1")
        p2 = QuoridorEnv.initial_state("P2")
        np.testing.assert_array_equal(encode_state(p1), encode_state(p2))

    def test_mask_matches_legal_actions(self):
        env = QuoridorEnv()
        legal = env.legal_actions()
        mask = legal_action_mask(legal, env.state.turn)
        self.assertEqual(mask.shape, (ACTION_SIZE,))
        self.assertEqual(int(mask.sum()), len(legal))

    def test_input_channels_and_reflection_round_trip(self):
        observation = encode_state(QuoridorEnv.initial_state())
        self.assertEqual(observation.shape, (INPUT_CHANNELS, 9, 9))
        np.testing.assert_array_equal(
            reflect_observation(reflect_observation(observation)), observation
        )
        policy = np.arange(ACTION_SIZE, dtype=np.float32)
        np.testing.assert_array_equal(reflect_policy(reflect_policy(policy)), policy)


if __name__ == "__main__":
    unittest.main()
