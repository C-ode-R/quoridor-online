from __future__ import annotations

import torch
from torch import nn

from .encoding import ACTION_SIZE, INPUT_CHANNELS


class ResidualBlock(nn.Module):
    def __init__(self, channels: int):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
        )
        self.activation = nn.ReLU(inplace=True)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.activation(inputs + self.layers(inputs))


class PolicyValueNet(nn.Module):
    """Small AlphaZero-style policy/value network for a 9x9 board."""

    def __init__(self, channels: int = 64, blocks: int = 4, in_channels: int = INPUT_CHANNELS):
        super().__init__()
        self.channels = channels
        self.blocks = blocks
        self.in_channels = in_channels
        self.stem = nn.Sequential(
            nn.Conv2d(in_channels, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
        )
        self.backbone = nn.Sequential(*[ResidualBlock(channels) for _ in range(blocks)])
        self.policy_head = nn.Sequential(
            nn.Conv2d(channels, 2, 1, bias=False),
            nn.BatchNorm2d(2),
            nn.ReLU(inplace=True),
            nn.Flatten(),
            nn.Linear(2 * 9 * 9, ACTION_SIZE),
        )
        self.value_head = nn.Sequential(
            nn.Conv2d(channels, 1, 1, bias=False),
            nn.BatchNorm2d(1),
            nn.ReLU(inplace=True),
            nn.Flatten(),
            nn.Linear(9 * 9, 64),
            nn.ReLU(inplace=True),
            nn.Linear(64, 1),
            nn.Tanh(),
        )

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        features = self.backbone(self.stem(inputs))
        return self.policy_head(features), self.value_head(features).squeeze(-1)

    def checkpoint(self) -> dict:
        return {
            "channels": self.channels,
            "blocks": self.blocks,
            "in_channels": self.in_channels,
            "state_dict": self.state_dict(),
        }

    @classmethod
    def from_checkpoint(cls, checkpoint: dict, *, device: str = "cpu") -> PolicyValueNet:
        model = cls(
            channels=checkpoint["channels"],
            blocks=checkpoint["blocks"],
            in_channels=checkpoint.get("in_channels", 6),
        )
        model.load_state_dict(checkpoint["state_dict"])
        return model.to(device)
