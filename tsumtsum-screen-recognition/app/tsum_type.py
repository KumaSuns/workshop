from __future__ import annotations

import torch
from PIL import Image
from torch import nn
from torch.nn import functional as F
from torchvision.models import ResNet18_Weights, resnet18
from torchvision.transforms.functional import pil_to_tensor, to_pil_image

TYPE_INPUT = 96
TYPE_EMBED = 64
TYPE_CROP_SCALE = 1.1
TYPE_CROP_INNER = 0.9
TYPE_DISK_INNER = 0.78
TYPE_DISK_OUTER = 0.98
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
TYPE_FILL = tuple(int(round(value * 255)) for value in IMAGENET_MEAN)


def crop_tsum(image: Image.Image, piece: dict[str, int], scale: float = TYPE_CROP_SCALE) -> Image.Image:
    x, y, r = int(piece["x"]), int(piece["y"]), max(4, int(piece["r"]))
    span = max(8, int(round(r * scale)))
    return image.crop((x - span, y - span, x + span, y + span))


def isolated_tsum_rgb(
    image: Image.Image,
    piece: dict[str, int],
    others: list[dict[str, int]] | None = None,
    crop_scale: float | None = None,
) -> torch.Tensor:
    x, y, r = int(piece["x"]), int(piece["y"]), max(4, int(piece["r"]))
    span = max(8, int(round(r * (TYPE_CROP_SCALE if crop_scale is None else crop_scale))))
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
    if others:
        for other in others:
            ox, oy = int(other["x"]), int(other["y"])
            if ox == x and oy == y:
                continue
            orad = max(4, int(other.get("r") or r)) * scale * TYPE_DISK_INNER
            dist_other = torch.hypot(xs - (ox - left) * scale, ys - (oy - top) * scale)
            fade = torch.where(dist_other < orad, torch.zeros_like(fade), fade)
    fill = torch.tensor(TYPE_FILL, dtype=torch.float32).view(3, 1, 1)
    isolated = rgb * fade.unsqueeze(0) + fill * (1.0 - fade.unsqueeze(0))
    return _suppress_effect_pixels(isolated, fade)


def prepare_tsum_crop(
    image: Image.Image,
    piece: dict[str, int],
    others: list[dict[str, int]] | None = None,
    crop_scale: float | None = None,
) -> Image.Image:
    isolated = isolated_tsum_rgb(image, piece, others, crop_scale)
    return to_pil_image(isolated.byte().clamp(0, 255))


def piece_lab(image: Image.Image, piece: dict[str, int]) -> tuple[float, ...]:
    x, y, r = int(piece["x"]), int(piece["y"]), max(4, int(piece["r"]))
    span = max(8, int(round(r * TYPE_CROP_SCALE)))
    width, height = image.size
    box = (
        max(0, x - span),
        max(0, y - span),
        min(width, x + span + 1),
        min(height, y + span + 1),
    )
    crop = image.crop(box).resize((32, 32), Image.Resampling.BILINEAR).convert("LAB")
    cx = cy = 15.5
    inner: list[tuple[int, int, int]] = []
    ring: list[tuple[int, int, int]] = []
    for index, pixel in enumerate(crop.getdata()):
        px = index % 32
        py = index // 32
        dist = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        lab = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        if dist <= 4.0:
            inner.append(lab)
        elif dist <= 9.0:
            ring.append(lab)
    if not inner and not ring:
        return (0.0, 128.0, 128.0, 0.0, 128.0, 128.0)
    if not inner:
        inner = ring
    if not ring:
        ring = inner
    luma = sorted(pixel[0] for pixel in ring)
    median_l = luma[len(luma) // 2]
    kept = [pixel for pixel in ring if pixel[0] <= median_l + 28]
    if not kept:
        kept = ring

    def mean(pixels: list[tuple[int, int, int]]) -> tuple[float, float, float]:
        count = len(pixels)
        total = [sum(pixel[i] for pixel in pixels) / count for i in range(3)]
        return (0.3 * total[0], total[1], total[2])

    return mean(inner) + mean(kept)


def _suppress_effect_pixels(rgb: torch.Tensor, fade: torch.Tensor) -> torch.Tensor:
    luma = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    body = fade > 0.6
    if int(body.sum()) < 16:
        return rgb
    median = luma[body].median()
    sparkle = body & (luma > median + 48)
    if not bool(sparkle.any()):
        return rgb
    keep = body & ~sparkle
    if int(keep.sum()) < 8:
        return rgb
    out = rgb.clone()
    out[0][sparkle] = rgb[0][keep].median()
    out[1][sparkle] = rgb[1][keep].median()
    out[2][sparkle] = rgb[2][keep].median()
    return out


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
            parameter.requires_grad = True


def supcon_loss(
    z: torch.Tensor,
    labels: torch.Tensor,
    colors: torch.Tensor | None = None,
    temperature: float = 0.07,
) -> torch.Tensor:
    similar = z @ z.T / temperature
    eye = torch.eye(z.size(0), dtype=torch.bool, device=z.device)
    pos = labels.unsqueeze(0).eq(labels.unsqueeze(1)) & ~eye
    neg = ~pos & ~eye
    if colors is not None and colors.size(0) == z.size(0):
        dist = torch.cdist(colors.float(), colors.float())
        nz = dist[dist > 1e-6]
        med = nz.median() if int(nz.numel()) else torch.tensor(1.0, device=z.device)
        hard = torch.exp(-dist / med.clamp(min=1e-3))
        similar = similar + 0.8 * hard * neg.float()
    similar = similar - similar.max(dim=1, keepdim=True).values
    exp = similar.exp() * (~eye)
    log_prob = similar - exp.sum(dim=1, keepdim=True).clamp(min=1e-8).log()
    pos_n = pos.sum(dim=1)
    has_pos = pos_n > 0
    if not has_pos.any():
        return z.sum() * 0.0
    loss = -(log_prob * pos).sum(dim=1) / pos_n.clamp(min=1)
    return loss[has_pos].mean()
