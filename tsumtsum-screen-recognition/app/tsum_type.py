from __future__ import annotations

import torch
from PIL import Image
from torch import nn
from torch.nn import functional as F
from torchvision.models import ResNet18_Weights, resnet18
from torchvision.transforms.functional import pil_to_tensor, to_pil_image

TYPE_INPUT = 64
TYPE_EMBED = 64
TYPE_CROP_SCALE = 0.70
TYPE_DISK_INNER = 0.72
TYPE_DISK_OUTER = 0.96
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
TYPE_FILL = tuple(int(round(value * 255)) for value in IMAGENET_MEAN)


def crop_tsum(image: Image.Image, piece: dict[str, int], scale: float = TYPE_CROP_SCALE) -> Image.Image:
    x, y, r = int(piece["x"]), int(piece["y"]), max(4, int(piece["r"]))
    span = max(8, int(round(r * scale)))
    return image.crop((x - span, y - span, x + span, y + span))


def prepare_tsum_crop(
    image: Image.Image,
    piece: dict[str, int],
    others: list[dict[str, int]] | None = None,
) -> Image.Image:
    x, y, r = int(piece["x"]), int(piece["y"]), max(4, int(piece["r"]))
    span = max(8, int(round(r * TYPE_CROP_SCALE)))
    left = x - span
    top = y - span
    size = TYPE_INPUT
    crop = image.crop((left, top, x + span, y + span)).convert("RGB").resize(
        (size, size), Image.Resampling.BILINEAR
    )
    scale = size / max(1, 2 * span)
    cx = (x - left) * scale
    cy = (y - top) * scale
    rgb = pil_to_tensor(crop).float()
    ys = torch.arange(size, dtype=torch.float32).unsqueeze(1) + 0.5
    xs = torch.arange(size, dtype=torch.float32).unsqueeze(0) + 0.5
    dist_self = torch.hypot(xs - cx, ys - cy)
    half = size / 2.0
    inner = half * TYPE_DISK_INNER
    outer = max(inner + 1.0, half * TYPE_DISK_OUTER)
    fade = ((outer - dist_self) / (outer - inner)).clamp(0.0, 1.0)
    fade = torch.where(dist_self <= inner, torch.ones_like(fade), fade)
    fade = torch.where(dist_self < outer, fade, torch.zeros_like(fade))
    fill = torch.tensor(TYPE_FILL, dtype=torch.float32).view(3, 1, 1)
    isolated = rgb * fade.unsqueeze(0) + fill * (1.0 - fade.unsqueeze(0))
    return to_pil_image(isolated.byte().clamp(0, 255))


class TsumTypeNet(nn.Module):
    """ツム切り出しから、同じ種類が近くなる埋め込みを出す。"""

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
        self.pool = nn.AdaptiveAvgPool2d((4, 4))
        self.proj = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128 * 16, 256),
            nn.ReLU(inplace=True),
            nn.Linear(256, TYPE_EMBED),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.pool(self.stem(x))
        return F.normalize(self.proj(feat), dim=1)

    def freeze_backbone(self) -> None:
        for parameter in self.stem.parameters():
            parameter.requires_grad = False
        for block in self.stem[-2:]:
            for parameter in block.parameters():
                parameter.requires_grad = True


def supcon_loss(z: torch.Tensor, labels: torch.Tensor, temperature: float = 0.07) -> torch.Tensor:
    similar = z @ z.T / temperature
    eye = torch.eye(z.size(0), dtype=torch.bool, device=z.device)
    pos = labels.unsqueeze(0).eq(labels.unsqueeze(1)) & ~eye
    similar = similar - similar.max(dim=1, keepdim=True).values
    exp = similar.exp() * (~eye)
    log_prob = similar - exp.sum(dim=1, keepdim=True).clamp(min=1e-8).log()
    pos_n = pos.sum(dim=1)
    has_pos = pos_n > 0
    if not has_pos.any():
        return z.sum() * 0.0
    loss = -(log_prob * pos).sum(dim=1) / pos_n.clamp(min=1)
    return loss[has_pos].mean()
