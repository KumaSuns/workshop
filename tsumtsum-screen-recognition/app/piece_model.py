from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F
from torchvision.models import ResNet18_Weights, resnet18

PIECE_INPUT = 512
HEATMAP_SIZE = 128
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
KIND_CHANNELS = {"tsum": 0, "bomb": 1}


def pixel_to_heat(
    x: float, y: float, left: float, top: float, crop_w: float, crop_h: float
) -> tuple[float, float]:
    return (x - left) / crop_w * HEATMAP_SIZE, (y - top) / crop_h * HEATMAP_SIZE


def heat_to_pixel(
    hx: float, hy: float, left: float, top: float, crop_w: float, crop_h: float
) -> tuple[float, float]:
    return left + hx / HEATMAP_SIZE * crop_w, top + hy / HEATMAP_SIZE * crop_h


class PieceNet(nn.Module):
    """ゲーム範囲からツム／ボムの中心ヒートマップと半径を出す。"""

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
        self.up = nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.fuse = nn.Sequential(
            nn.Conv2d(128, 64, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 3, kernel_size=1),
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        for layer in self.stem[:4]:
            x = layer(x)
        skip = self.stem[4](x)
        low = self.stem[5](skip)
        up = self.up(low)
        if up.shape[-2:] != skip.shape[-2:]:
            up = F.interpolate(up, size=skip.shape[-2:], mode="bilinear", align_corners=False)
        raw = self.fuse(torch.cat([up, skip], dim=1))
        heat = torch.sigmoid(raw[:, :2])
        radius = torch.sigmoid(raw[:, 2:3])
        return heat, radius

    def freeze_backbone(self) -> None:
        for parameter in self.stem.parameters():
            parameter.requires_grad = False
        for block in self.stem[-2:]:
            for parameter in block.parameters():
                parameter.requires_grad = True


def draw_gaussian(canvas: torch.Tensor, cx: float, cy: float, sigma: float) -> None:
    height, width = canvas.shape
    radius = int(max(1, math.ceil(3 * sigma)))
    x0 = max(0, int(cx) - radius)
    x1 = min(width, int(cx) + radius + 1)
    y0 = max(0, int(cy) - radius)
    y1 = min(height, int(cy) + radius + 1)
    if x0 >= x1 or y0 >= y1:
        return
    ys = torch.arange(y0, y1, dtype=torch.float32).unsqueeze(1)
    xs = torch.arange(x0, x1, dtype=torch.float32).unsqueeze(0)
    blob = torch.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma * sigma))
    canvas[y0:y1, x0:x1] = torch.maximum(canvas[y0:y1, x0:x1], blob)


def refine_peak(heat: torch.Tensor, x: int, y: int) -> tuple[float, float]:
    height, width = heat.shape[-2:]
    if x <= 0 or y <= 0 or x >= width - 1 or y >= height - 1:
        return float(x), float(y)

    def offset(center: float, left: float, right: float) -> float:
        denom = left + right - 2.0 * center
        if abs(denom) < 1e-6:
            return 0.0
        return max(-0.45, min(0.45, 0.5 * (left - right) / denom))

    dx = offset(float(heat[y, x]), float(heat[y, x - 1]), float(heat[y, x + 1]))
    dy = offset(float(heat[y, x]), float(heat[y - 1, x]), float(heat[y + 1, x]))
    return x + dx, y + dy


def peaks_from_heat(
    heat: torch.Tensor,
    radius_map: torch.Tensor,
    threshold: float = 0.22,
) -> list[tuple[float, float, float, float]]:
    if heat.ndim == 3:
        heat = heat.squeeze(0)
        radius_map = radius_map.squeeze(0)
    pooled = F.max_pool2d(heat.unsqueeze(0).unsqueeze(0), 3, stride=1, padding=1)[0, 0]
    keep = (heat >= pooled) & (heat >= threshold)
    ys, xs = torch.where(keep)
    points: list[tuple[float, float, float, float]] = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        fx, fy = refine_peak(heat, int(x), int(y))
        points.append(
            (
                float(heat[y, x]),
                fx,
                fy,
                float(radius_map[y, x]),
            )
        )
    points.sort(reverse=True)
    kept: list[tuple[float, float, float, float]] = []
    min_sep = max(2.0, HEATMAP_SIZE / 18.0)
    for score, x, y, radius in points:
        too_close = False
        for _s, ox, oy, _other_r in kept:
            if math.hypot(x - ox, y - oy) < min_sep:
                too_close = True
                break
        if not too_close:
            kept.append((score, x, y, radius))
    return kept
