from __future__ import annotations

import random
from pathlib import Path

import torch
from PIL import Image
from torch.nn import functional as F
from torchvision.transforms import functional as TF
from torchvision.transforms import ColorJitter

from app.dataset import Dataset
from app.paths import DATA_DIR, IMAGE_EXTENSIONS
from app.regions import is_tsum_kind
from app.tsum_type import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    TYPE_FILL,
    TYPE_INPUT,
    TsumTypeNet,
    isolated_tsum_rgb,
    supcon_loss,
)

TEST_MODEL_PATH = DATA_DIR / "models" / "named_tsum_test.pt"
VER01_MODEL_PATH = DATA_DIR / "models" / "named_tsum_ver01.pt"
VER01_IMAGE_DIR = DATA_DIR / "named_tsum_ver01"
EPOCHS = 12


class NamedTrainingCancelled(Exception):
    pass


def registered_crops(should_stop=None) -> list[tuple[str, str, torch.Tensor]]:
    rows: list[tuple[str, str, torch.Tensor]] = []
    dataset = Dataset()
    for sample in dataset.all():
        if should_stop is not None and should_stop():
            raise NamedTrainingCancelled()
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


def _per_name(kind_count: int) -> int:
    return 8 if kind_count > 1 else 16


def epoch_passes(counts: list[int]) -> int:
    if not counts:
        return 1
    per_name = _per_name(len(counts))
    return max(1, max((count + per_name - 1) // per_name for count in counts))


def _epoch_batches(rows: list[tuple[str, str, torch.Tensor]], labels: dict[tuple[str, str], int]):
    pools: dict[tuple[str, str], list[torch.Tensor]] = {}
    for ja, en, crop in rows:
        pools.setdefault((ja, en), []).append(crop)
    for group in pools.values():
        random.shuffle(group)
    per_name = _per_name(len(pools))
    while True:
        crops: list[torch.Tensor] = []
        targets: list[int] = []
        for name, group in pools.items():
            if not group:
                continue
            take = group[:per_name]
            del group[:per_name]
            for crop in take:
                crops.append(_augment(crop))
                targets.append(labels[name])
        if len(crops) < 2:
            return
        order = list(range(len(crops)))
        random.shuffle(order)
        batch = torch.stack([crops[index] for index in order])
        target = torch.tensor([targets[index] for index in order], dtype=torch.long)
        yield batch, target


def _check_registered_faces(names, vectors, prototypes) -> dict:
    checked = 0
    hit = 0
    alone: list[dict] = []
    wrong: list[dict] = []
    low: list[dict] = []
    proto = F.normalize(prototypes.float(), dim=1)
    for index, name in enumerate(names):
        ja, en = name
        group = vectors[name]
        count = len(group)
        if count < 2:
            alone.append({"ja": ja, "en": en, "count": count})
            continue
        stacked = torch.stack(group).float()
        total = stacked.sum(dim=0)
        misses: dict[tuple[str, str], int] = {}
        low_count = 0
        for row_index in range(count):
            own = total - stacked[row_index]
            if float(own.norm()) < 1e-6:
                continue
            own = F.normalize(own, dim=0)
            scores = (proto @ stacked[row_index]).clone()
            scores[index] = torch.dot(own, stacked[row_index])
            best = int(torch.argmax(scores).item())
            own_score = float(scores[index])
            checked += 1
            if best == index:
                hit += 1
                if own_score < 0.70:
                    low_count += 1
            else:
                other = names[best]
                misses[other] = misses.get(other, 0) + 1
        if misses:
            other, other_count = max(misses.items(), key=lambda item: item[1])
            wrong.append(
                {
                    "ja": ja,
                    "en": en,
                    "count": count,
                    "miss": sum(misses.values()),
                    "other_ja": other[0],
                    "other_en": other[1],
                    "other_count": other_count,
                }
            )
        if low_count:
            low.append({"ja": ja, "en": en, "count": count, "low": low_count})
    wrong.sort(key=lambda item: (-int(item["miss"]), str(item["ja"]), str(item["en"])))
    low.sort(key=lambda item: (-int(item["low"]), str(item["ja"]), str(item["en"])))
    return {"checked": checked, "hit": hit, "alone": alone, "wrong": wrong, "low": low}


def train(
    path: Path = TEST_MODEL_PATH,
    epochs: int = EPOCHS,
    on_progress=None,
    should_stop=None,
    rows: list[tuple[str, str, torch.Tensor]] | None = None,
    on_fraction=None,
) -> dict:
    if on_progress is not None:
        on_progress(0, epochs, "ツム名  準備しています")
    if rows is None:
        rows = registered_crops(should_stop)
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
    counts: dict[tuple[str, str], int] = {}
    for ja, en, _crop in rows:
        counts[(ja, en)] = counts.get((ja, en), 0) + 1
    passes = epoch_passes(list(counts.values()))
    work = epochs * passes + len(rows)

    def fraction(done: int, text: str) -> None:
        if on_fraction is None:
            return
        if work <= 0:
            on_fraction(0, text)
            return
        on_fraction(min(100, int(done * 100 / work)), text)

    fraction(0, "準備しています")
    for epoch in range(epochs):
        if should_stop is not None and should_stop():
            raise NamedTrainingCancelled()
        step = 0
        for batch, target in _epoch_batches(rows, labels):
            step += 1
            if should_stop is not None and should_stop():
                raise NamedTrainingCancelled()
            if on_progress is not None:
                on_progress(epoch + 1, epochs, f"ツム名  {epoch + 1}/{epochs}  {step}/{passes}")
            fraction(epoch * passes + step, f"{epoch + 1}/{epochs}")
            batch = _normalize(batch).to(device)
            target = target.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = supcon_loss(model(batch), target)
            loss.backward()
            optimizer.step()
        scheduler.step()
    if should_stop is not None and should_stop():
        raise NamedTrainingCancelled()
    model.eval()
    if on_progress is not None:
        on_progress(epochs, epochs, "ツム名  まとめています")
    fraction(epochs * passes, "まとめています")
    vectors: dict[tuple[str, str], list[torch.Tensor]] = {name: [] for name in names}
    with torch.no_grad():
        for index, (ja, en, crop) in enumerate(rows):
            if should_stop is not None and index % 32 == 0 and should_stop():
                raise NamedTrainingCancelled()
            encoded = model(_normalize(crop.unsqueeze(0)).to(device))
            vectors[(ja, en)].append(F.normalize(encoded, dim=1).cpu().squeeze(0))
            fraction(epochs * passes + index + 1, "まとめています")
    averaged = torch.stack(
        [F.normalize(torch.stack(vectors[name]).mean(dim=0), dim=0) for name in names]
    )
    counts = [len(vectors[name]) for name in names]
    check = _check_registered_faces(names, vectors, averaged)
    saved_names = []
    proto_rows = []
    for (ja, en), count in zip(names, counts):
        vecs = vectors[(ja, en)]
        if ja == "ツムではない":
            for vec in vecs:
                proto_rows.append(F.normalize(vec, dim=0))
                saved_names.append({"ja": ja, "en": en, "count": 1})
        else:
            proto_rows.append(F.normalize(torch.stack(vecs).mean(dim=0), dim=0))
            saved_names.append({"ja": ja, "en": en, "count": count})
    prototypes = torch.stack(proto_rows)
    payload = {
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "names": saved_names,
        "prototypes": prototypes,
        "examples": len(rows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, path)
    payload["check"] = check
    return payload


def ver01_rows() -> list[tuple[str, str, torch.Tensor]]:
    rows: list[tuple[str, str, torch.Tensor]] = []
    if not VER01_IMAGE_DIR.is_dir():
        return rows
    for folder in sorted(VER01_IMAGE_DIR.iterdir()):
        if not folder.is_dir():
            continue
        ja = folder.name.strip()
        if not ja:
            continue
        for image_path in sorted(folder.iterdir()):
            if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            with Image.open(image_path) as opened:
                image = opened.convert("RGB").resize((TYPE_INPUT, TYPE_INPUT), Image.Resampling.BILINEAR)
            rows.append((ja, "", TF.pil_to_tensor(image).float()))
    return rows


def estimate_ver01_seconds(
    rows: list[tuple[str, str, torch.Tensor]],
    face_rate: float,
    saved_passes: float,
    batch_rate: float,
) -> float:
    faces = len(rows)
    counts: dict[tuple[str, str], int] = {}
    for ja, en, _crop in rows:
        counts[(ja, en)] = counts.get((ja, en), 0) + 1
    passes = epoch_passes(list(counts.values()))
    if saved_passes < 1:
        saved_passes = 1.0
    if face_rate > 0:
        return max(face_rate * max(faces, 1) * (passes / saved_passes), 5.0)
    proto_batches = max(1, (max(faces, 1) + 7) // 8)
    return max(8.0 + (EPOCHS * passes + proto_batches) * batch_rate, 5.0)


def main() -> None:
    payload = train()
    print(f"examples {payload['examples']}")
    for name in payload["names"]:
        print(f"{name['ja']}  {name['en']}  {name['count']}")
    print(TEST_MODEL_PATH)


if __name__ == "__main__":
    main()
