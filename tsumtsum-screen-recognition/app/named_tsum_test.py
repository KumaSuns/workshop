from __future__ import annotations

import random
from pathlib import Path

import torch
from PIL import Image
from torch.nn import functional as F
from torchvision.transforms import functional as TF
from torchvision.transforms import ColorJitter

from app.dataset import Dataset
from app.paths import DATA_DIR
from app.regions import is_tsum_kind
from app.tsum_type import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    TYPE_FILL,
    TsumTypeNet,
    isolated_tsum_rgb,
    supcon_loss,
)

TEST_MODEL_PATH = DATA_DIR / "models" / "named_tsum_test.pt"
EPOCHS = 12


def registered_crops() -> list[tuple[str, str, torch.Tensor]]:
    rows: list[tuple[str, str, torch.Tensor]] = []
    dataset = Dataset()
    for sample in dataset.all():
        names = sample.circle_names or {}
        if not names or not sample.image_path.is_file():
            continue
        with Image.open(sample.image_path) as opened:
            image = opened.convert("RGB")
        tsums = [piece for piece in sample.pieces if is_tsum_kind(str(piece.get("kind") or ""))]
        for piece in tsums:
            saved = names.get(str(int(piece.get("group") or 1))) or {}
            ja = str(saved.get("ja") or "").strip()
            en = str(saved.get("en") or "").strip()
            if not ja and not en:
                continue
            raw_out = saved.get("out")
            out = {str(item) for item in raw_out} if isinstance(raw_out, list) else set()
            if f"{int(piece['x'])},{int(piece['y'])}" in out:
                continue
            rows.append((ja, en, isolated_tsum_rgb(image, piece, tsums)))
    return rows


def _normalize(batch: torch.Tensor) -> torch.Tensor:
    mean = batch.new_tensor(IMAGENET_MEAN).view(1, 3, 1, 1)
    std = batch.new_tensor(IMAGENET_STD).view(1, 3, 1, 1)
    return (batch.clamp(0, 255) / 255.0 - mean) / std


def _augment(crop: torch.Tensor) -> torch.Tensor:
    image = TF.to_pil_image(crop.byte().clamp(0, 255))
    image = ColorJitter(0.12, 0.12, 0.12, 0.03)(image)
    if random.random() < 0.5:
        image = TF.hflip(image)
    image = TF.rotate(image, random.uniform(-8.0, 8.0), fill=TYPE_FILL)
    return TF.pil_to_tensor(image).float()


def _batch(rows: list[tuple[str, str, torch.Tensor]], labels: dict[tuple[str, str], int]) -> tuple[torch.Tensor, torch.Tensor]:
    by_name: dict[tuple[str, str], list[torch.Tensor]] = {}
    for ja, en, crop in rows:
        by_name.setdefault((ja, en), []).append(crop)
    crops: list[torch.Tensor] = []
    targets: list[int] = []
    per_name = 8 if len(by_name) > 1 else 16
    for name, group in by_name.items():
        take = min(per_name, len(group))
        for crop in random.sample(group, take):
            crops.append(_augment(crop))
            targets.append(labels[name])
    order = list(range(len(crops)))
    random.shuffle(order)
    batch = torch.stack([crops[index] for index in order])
    target = torch.tensor([targets[index] for index in order], dtype=torch.long)
    return batch, target


def train(path: Path = TEST_MODEL_PATH, epochs: int = EPOCHS) -> dict:
    rows = registered_crops()
    names = sorted({(ja, en) for ja, en, _crop in rows})
    if not names:
        raise RuntimeError("登録された〇がありません")
    labels = {name: index for index, name in enumerate(names)}
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    try:
        model = TsumTypeNet(pretrained=True)
    except Exception:
        model = TsumTypeNet(pretrained=False)
    model.freeze_backbone()
    model.to(device)
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=1e-3,
        weight_decay=1e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    model.train()
    for _epoch in range(epochs):
        batch, target = _batch(rows, labels)
        if batch.size(0) < 2:
            break
        batch = _normalize(batch).to(device)
        target = target.to(device)
        optimizer.zero_grad(set_to_none=True)
        loss = supcon_loss(model(batch), target)
        loss.backward()
        optimizer.step()
        scheduler.step()
    model.eval()
    vectors: dict[tuple[str, str], list[torch.Tensor]] = {name: [] for name in names}
    with torch.no_grad():
        for ja, en, crop in rows:
            encoded = model(_normalize(crop.unsqueeze(0)).to(device))
            vectors[(ja, en)].append(F.normalize(encoded, dim=1).cpu().squeeze(0))
    prototypes = torch.stack(
        [F.normalize(torch.stack(vectors[name]).mean(dim=0), dim=0) for name in names]
    )
    counts = [len(vectors[name]) for name in names]
    payload = {
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "names": [{"ja": ja, "en": en, "count": count} for (ja, en), count in zip(names, counts)],
        "prototypes": prototypes,
        "examples": len(rows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, path)
    return payload


def main() -> None:
    payload = train()
    print(f"examples {payload['examples']}")
    for name in payload["names"]:
        print(f"{name['ja']}  {name['en']}  {name['count']}")
    print(TEST_MODEL_PATH)


if __name__ == "__main__":
    main()
