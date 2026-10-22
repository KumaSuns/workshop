from __future__ import annotations

import torch
from torch import nn
from torchvision.models import ResNet18_Weights, resnet18

INPUT_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class GameRegionNet(nn.Module):
    """スクリーンショット全体からゲーム範囲 (x, y, w, h) を 0-1 で回帰する。"""

    def __init__(self, pretrained: bool = True) -> None:
        super().__init__()
        weights = ResNet18_Weights.DEFAULT if pretrained else None
        backbone = resnet18(weights=weights)
        self.features = nn.Sequential(*list(backbone.children())[:-1])
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(512, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(128, 4),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(x))

    def freeze_backbone(self, train_last_block: bool = True) -> None:
        for parameter in self.features.parameters():
            parameter.requires_grad = False
        if train_last_block:
            last_block = self.features[-2]
            for parameter in last_block.parameters():
                parameter.requires_grad = True
