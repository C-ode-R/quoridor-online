import tempfile
import unittest
from pathlib import Path

import numpy as np

from quoridor_rl.encoding import ACTION_SIZE, INPUT_CHANNELS
from quoridor_rl.self_play import TrainingExample
from quoridor_rl.training import ReplayBuffer


def example(index: int, *, policy_weight: float = 1.0) -> TrainingExample:
    observation = np.full((INPUT_CHANNELS, 9, 9), index, dtype=np.float32)
    policy = np.zeros(ACTION_SIZE, dtype=np.float32)
    policy[index % ACTION_SIZE] = 1.0
    return TrainingExample(observation, policy, 1.0, policy_weight)


class ReplayBufferTests(unittest.TestCase):
    def test_recent_only_sampling_uses_recent_window(self):
        replay = ReplayBuffer(capacity=100)
        replay.extend([example(index) for index in range(100)])
        batch = replay.sample(10, recent_fraction=1.0, recent_window=10)
        indices = [int(item.observation[0, 0, 0]) for item in batch]
        self.assertTrue(all(index >= 90 for index in indices))

    def test_policy_weight_round_trip(self):
        replay = ReplayBuffer(capacity=10)
        replay.extend([example(1, policy_weight=0.0), example(2, policy_weight=1.0)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.npz"
            replay.save(path)
            loaded = ReplayBuffer.load(path, capacity=10)
        self.assertEqual([item.policy_weight for item in loaded.data], [0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
