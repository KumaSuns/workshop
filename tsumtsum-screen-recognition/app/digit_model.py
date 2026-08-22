from __future__ import annotations

import re

import torch
from torch import nn
from torchvision.models import ResNet18_Weights, resnet18

DIGIT_HEIGHT = 64
DIGIT_WIDTH = 256
MAX_DIGITS = 8
BLANK_INDEX = 10
NUM_CLASSES = 11
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def digit_string(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def encode_digits(text: str) -> torch.Tensor:
    digits = [int(char) for char in digit_string(text)[-MAX_DIGITS:]]
    pad = [BLANK_INDEX] * (MAX_DIGITS - len(digits))
    return torch.tensor(pad + digits, dtype=torch.long)


def decode_logits(logits: torch.Tensor) -> str:
    if logits.ndim == 3:
        logits = logits[0]
    indices = logits.argmax(dim=-1).tolist()
    return "".join(str(index) for index in indices if 0 <= index <= 9)


class CoinDigitNet(nn.Module):
    """コイン枠から数字列を読む。右詰め 8 桁、余りは空白。"""

    def __init__(self, pretrained: bool = True) -> None:
        super().__init__()
        weights = ResNet18_Weights.DEFAULT if pretrained else None
        backbone = resnet18(weights=weights)
        self.stem = nn.Sequential(
            backbone.conv1,
            backbone.bn1,
            backbone.relu,
            backbone.maxpool,
            backbone.layer1,
            backbone.layer2,
        )
        self.pool = nn.AdaptiveAvgPool2d((1, MAX_DIGITS))
        self.classifier = nn.Linear(128, NUM_CLASSES)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.pool(self.stem(x)).squeeze(2).permute(0, 2, 1)
        return self.classifier(feat)

    def freeze_backbone(self) -> None:
        for parameter in self.stem.parameters():
            parameter.requires_grad = False
        for parameter in self.stem[-1].parameters():
            parameter.requires_grad = True
