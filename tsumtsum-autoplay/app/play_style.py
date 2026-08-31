from __future__ import annotations

import json
from pathlib import Path

from app.paths import APP_ROOT

PATH = APP_ROOT / "data" / "play_style.json"
UNLIKE_PATH = APP_ROOT / "data" / "unlike.json"
UNLIKE_SIM = 0.75
UNLIKE_MAX = 40


def _empty() -> dict:
    return {"wins": {}, "losses": {}, "follow_max": 3}


def _load() -> dict:
    if not PATH.is_file():
        return _empty()
    try:
        payload = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return _empty()
    if not isinstance(payload, dict):
        return _empty()
    wins = payload.get("wins") if isinstance(payload.get("wins"), dict) else {}
    losses = payload.get("losses") if isinstance(payload.get("losses"), dict) else {}
    follow = int(payload.get("follow_max") or 3)
    return {
        "wins": {str(key): int(value) for key, value in wins.items()},
        "losses": {str(key): int(value) for key, value in losses.items()},
        "follow_max": max(1, min(6, follow)),
    }


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_pick(options: list[int], picked: int, ok: bool) -> None:
    if picked < 3:
        return
    data = _load()
    key = f"{max(options or [picked])}:{picked}"
    bucket = "wins" if ok else "losses"
    data[bucket][key] = int(data[bucket].get(key, 0)) + 1
    _save(data)


def follow_max() -> int:
    return _load()["follow_max"]


def note_combo(hit_cap: bool, leftover_had_more: bool) -> None:
    if not (hit_cap and leftover_had_more):
        return
    data = _load()
    data["follow_max"] = min(6, data["follow_max"] + 1)
    _save(data)


def rank(
    chain: list[dict[str, int]],
    leftover: int = 0,
    options: list[int] | None = None,
    jump: float = 0.0,
) -> tuple[int, int, float, int]:
    length = len(chain)
    data = _load()
    key = f"{max(options or [length])}:{length}"
    learned = int(data["wins"].get(key, 0)) - int(data["losses"].get(key, 0))
    return (length, leftover, -jump, learned)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))


def load_unlike() -> list[tuple[tuple[float, ...], tuple[float, ...]]]:
    if not UNLIKE_PATH.is_file():
        return []
    try:
        payload = json.loads(UNLIKE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    pairs: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        left, right = item
        if not isinstance(left, list) or not isinstance(right, list):
            continue
        if not left or not right or len(left) != len(right):
            continue
        pairs.append((tuple(float(v) for v in left), tuple(float(v) for v in right)))
    return pairs[:UNLIKE_MAX]


def save_unlike(pairs: list[tuple[tuple[float, ...], tuple[float, ...]]]) -> None:
    UNLIKE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [[list(left), list(right)] for left, right in pairs[:UNLIKE_MAX]]
    UNLIKE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def add_unlike(
    pairs: list[tuple[tuple[float, ...], tuple[float, ...]]],
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> bool:
    if unlike_hit(left, right, pairs):
        return False
    pairs.append((left, right))
    del pairs[:-UNLIKE_MAX]
    save_unlike(pairs)
    return True


def unlike_hit(
    left: tuple[float, ...] | None,
    right: tuple[float, ...] | None,
    pairs: list[tuple[tuple[float, ...], tuple[float, ...]]],
    min_sim: float = UNLIKE_SIM,
) -> bool:
    if left is None or right is None or not pairs:
        return False
    for first, second in pairs:
        if _cosine(left, first) >= min_sim and _cosine(right, second) >= min_sim:
            return True
        if _cosine(left, second) >= min_sim and _cosine(right, first) >= min_sim:
            return True
    return False
