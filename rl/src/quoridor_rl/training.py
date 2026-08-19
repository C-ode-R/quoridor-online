from __future__ import annotations

import random
from collections import deque
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from .model import PolicyValueNet
from .self_play import TrainingExample
from .encoding import ACTION_SIZE, INPUT_CHANNELS


class ReplayBuffer:
    def __init__(self, capacity: int = 50_000):
        self.data: deque[TrainingExample] = deque(maxlen=capacity)

    def extend(self, examples: list[TrainingExample]) -> None:
        self.data.extend(examples)

    def sample(
        self,
        batch_size: int,
        *,
        recent_fraction: float = 0.0,
        recent_window: int = 0,
    ) -> list[TrainingExample]:
        items = list(self.data)
        count = min(batch_size, len(items))
        if count == 0:
            return []
        window = min(max(0, recent_window), len(items))
        recent_count = min(count, round(count * min(1.0, max(0.0, recent_fraction))))
        if window == 0 or recent_count == 0:
            return random.sample(items, count)
        recent_count = min(recent_count, window)
        recent_start = len(items) - window
        recent_indices = set(
            random.sample(range(recent_start, len(items)), recent_count)
        )
        remaining_indices = [
            index for index in range(len(items)) if index not in recent_indices
        ]
        other_count = min(count - recent_count, len(remaining_indices))
        selected = list(recent_indices) + random.sample(remaining_indices, other_count)
        random.shuffle(selected)
        return [items[index] for index in selected]

    def __len__(self) -> int:
        return len(self.data)

    @property
    def capacity(self) -> int:
        return self.data.maxlen or len(self.data)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        items = list(self.data)
        if items:
            observations = np.stack([item.observation for item in items])
            policies = np.stack([item.policy for item in items])
            values = np.asarray([item.value for item in items], dtype=np.float32)
            policy_weights = np.asarray(
                [item.policy_weight for item in items], dtype=np.float32
            )
        else:
            observations = np.empty((0, INPUT_CHANNELS, 9, 9), dtype=np.float32)
            policies = np.empty((0, ACTION_SIZE), dtype=np.float32)
            values = np.empty((0,), dtype=np.float32)
            policy_weights = np.empty((0,), dtype=np.float32)
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("wb") as output:
            np.savez_compressed(
                output,
                observations=observations,
                policies=policies,
                values=values,
                policy_weights=policy_weights,
            )
        temporary.replace(target)

    @classmethod
    def load(cls, path: str | Path, *, capacity: int = 50_000) -> "ReplayBuffer":
        replay = cls(capacity=capacity)
        with np.load(Path(path), allow_pickle=False) as data:
            weights = (
                data["policy_weights"]
                if "policy_weights" in data
                else np.ones(len(data["values"]), dtype=np.float32)
            )
            for observation, policy, value, policy_weight in zip(
                data["observations"], data["policies"], data["values"], weights
            ):
                replay.data.append(
                    TrainingExample(
                        observation, policy, float(value), float(policy_weight)
                    )
                )
        return replay


def train_steps(
    model: PolicyValueNet,
    optimizer: torch.optim.Optimizer,
    replay: ReplayBuffer,
    *,
    steps: int,
    batch_size: int,
    device: str,
    recent_fraction: float = 0.0,
    recent_window: int = 0,
) -> dict[str, float]:
    model.train()
    totals = {"loss": 0.0, "policy": 0.0, "value": 0.0}
    for _ in range(steps):
        batch = replay.sample(
            batch_size,
            recent_fraction=recent_fraction,
            recent_window=recent_window,
        )
        observations = torch.from_numpy(np.stack([item.observation for item in batch])).to(device)
        policies = torch.from_numpy(np.stack([item.policy for item in batch])).to(device)
        values = torch.tensor([item.value for item in batch], dtype=torch.float32, device=device)
        policy_weights = torch.tensor(
            [item.policy_weight for item in batch], dtype=torch.float32, device=device
        )

        logits, predicted_values = model(observations)
        per_example_policy_loss = -(
            policies * F.log_softmax(logits, dim=1)
        ).sum(dim=1)
        policy_loss = (
            per_example_policy_loss * policy_weights
        ).sum() / policy_weights.sum().clamp_min(1.0)
        value_loss = F.mse_loss(predicted_values, values)
        loss = policy_loss + value_loss

        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        totals["loss"] += float(loss.item())
        totals["policy"] += float(policy_loss.item())
        totals["value"] += float(value_loss.item())

    return {key: value / steps for key, value in totals.items()}
