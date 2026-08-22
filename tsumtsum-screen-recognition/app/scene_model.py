from __future__ import annotations

import torch
from torch import nn
from torchvision.models import ResNet18_Weights, resnet18

SCENE_INPUT = 224
SCENE_CLASSES = ("other", "go", "timeup")
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def scene_index(sample_confirmed: list[str]) -> int:
    if "go" in sample_confirmed:
        return 1
    if "timeup" in sample_confirmed:
        return 2
    return 0


def scene_name(index: int) -> str:
    if 0 <= index < len(SCENE_CLASSES):
        return SCENE_CLASSES[index]
    return "other"


class SceneNet(nn.Module):
    """画面全体から other / GO / TIME UP を分ける。"""

    def __init__(self, pretrained: bool = True) -> None:
        super().__init__()
        weights = ResNet18_Weights.DEFAULT if pretrained else None
        backbone = resnet18(weights=weights)
        self.features = nn.Sequential(*list(backbone.children())[:-1])
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(512, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(0.25),
            nn.Linear(128, len(SCENE_CLASSES)),
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
