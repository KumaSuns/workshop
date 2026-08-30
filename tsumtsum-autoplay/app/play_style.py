from __future__ import annotations

import json
from pathlib import Path

from app.paths import APP_ROOT

PATH = APP_ROOT / "data" / "play_style.json"


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


def rank(chain: list[dict[str, int]], options: list[int]) -> tuple[int, bool, bool, int]:
    count = len(chain)
    data = _load()
    key = f"{max(options or [count])}:{count}"
    wins = int(data["wins"].get(key, 0))
    losses = int(data["losses"].get(key, 0))
    return (count, wins - losses, count >= 7, count >= 5)
