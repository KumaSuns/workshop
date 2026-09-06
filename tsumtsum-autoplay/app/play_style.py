from __future__ import annotations

import json
import random
from pathlib import Path

from app.paths import APP_ROOT

PATH = APP_ROOT / "data" / "play_style.json"
UNLIKE_PATH = APP_ROOT / "data" / "unlike.json"
UNLIKE_SIM = 0.75
UNLIKE_MAX = 40
GOAL_COIN = 1200


def _empty_rl() -> dict:
    return {"n": 0, "baseline": 0.0, "goal_coin": GOAL_COIN, "choices": {}}


def _empty() -> dict:
    return {
        "wins": {},
        "losses": {},
        "follow_max": 3,
        "plays": [],
        "hud": {},
        "rl": _empty_rl(),
    }


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
    plays = payload.get("plays") if isinstance(payload.get("plays"), list) else []
    cleaned = []
    for item in plays[-40:]:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "clears": int(item.get("clears") or 0),
                "swipes": int(item.get("swipes") or 0),
                "skills": int(item.get("skills") or 0),
                "bombs": int(item.get("bombs") or 0),
                "fans": int(item.get("fans") or 0),
            }
        )
    hud_raw = payload.get("hud") if isinstance(payload.get("hud"), dict) else {}
    hud: dict[str, dict[str, int]] = {}
    for key, item in hud_raw.items():
        if not isinstance(item, dict):
            continue
        hud[str(key)] = {
            "w": int(item.get("w") or 0),
            "l": int(item.get("l") or 0),
        }
    return {
        "wins": {str(key): int(value) for key, value in wins.items()},
        "losses": {str(key): int(value) for key, value in losses.items()},
        "follow_max": max(1, min(6, follow)),
        "plays": cleaned,
        "hud": hud,
        "rl": _rl_from(payload.get("rl")),
    }


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(
        json.dumps(
            {
                "wins": data.get("wins") or {},
                "losses": data.get("losses") or {},
                "follow_max": int(data.get("follow_max") or 3),
                "plays": data.get("plays") or [],
                "hud": data.get("hud") or {},
                "rl": data.get("rl") or _empty_rl(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def style_now() -> dict:
    return _load()


def _rl_from(raw) -> dict:
    empty = _empty_rl()
    if not isinstance(raw, dict):
        return empty
    choices_raw = raw.get("choices") if isinstance(raw.get("choices"), dict) else {}
    choices: dict[str, dict[str, float | int]] = {}
    for key, item in choices_raw.items():
        if not isinstance(item, dict):
            continue
        choices[str(key)] = {
            "sum": float(item.get("sum") or 0),
            "n": int(item.get("n") or 0),
        }
    return {
        "n": int(raw.get("n") or 0),
        "baseline": float(raw.get("baseline") or 0),
        "goal_coin": GOAL_COIN,
        "choices": choices,
    }


def _rl_key(options: list[int], picked: int) -> str:
    return ",".join(str(n) for n in options) + f":{picked}"


def order_found(
    found: list[list[dict[str, int]]],
) -> tuple[list[list[dict[str, int]]], list[int], int]:
    if not found:
        return found, [], 0
    options = [len(item) for item in found]
    if len(found) == 1:
        return found, options, options[0]
    data = _load()
    rl = data.get("rl") if isinstance(data.get("rl"), dict) else _empty_rl()
    choices = rl.get("choices") if isinstance(rl.get("choices"), dict) else {}
    matches = int(rl.get("n") or 0)
    baseline = float(rl.get("baseline") or 0)
    scores: list[float] = []
    for item in found:
        key = _rl_key(options, len(item))
        entry = choices.get(key) if isinstance(choices.get(key), dict) else None
        n = int(entry.get("n") or 0) if entry else 0
        if n > 0:
            scores.append(float(entry.get("sum") or 0) / n)
        elif matches > 0:
            scores.append(baseline)
        else:
            scores.append(float(len(item)))
    if random.randrange(matches + 2) == 0:
        index = random.randrange(len(found))
    else:
        best = max(scores)
        index = scores.index(best)
    picked = found[index]
    rest = [item for i, item in enumerate(found) if i != index]
    return [picked] + rest, options, len(picked)


def record_rl_match(picks: list[tuple[list[int], int]], coin: int) -> None:
    if coin <= 0 or not picks:
        return
    data = _load()
    rl = _rl_from(data.get("rl"))
    choices = dict(rl.get("choices") or {})
    for options, picked in picks:
        if picked < 3:
            continue
        key = _rl_key(options, picked)
        item = dict(choices.get(key) or {}) if isinstance(choices.get(key), dict) else {}
        item["sum"] = float(item.get("sum") or 0) + coin
        item["n"] = int(item.get("n") or 0) + 1
        choices[key] = item
    prev_n = int(rl.get("n") or 0)
    n = prev_n + 1
    prev_base = float(rl.get("baseline") or 0)
    rl["choices"] = choices
    rl["n"] = n
    rl["baseline"] = (prev_base * prev_n + coin) / n
    data["rl"] = rl
    _save(data)


def record_play(clears: int, swipes: int, skills: int, bombs: int, fans: int) -> None:
    data = _load()
    plays = list(data.get("plays") or [])
    plays.append(
        {
            "clears": int(clears),
            "swipes": int(swipes),
            "skills": int(skills),
            "bombs": int(bombs),
            "fans": int(fans),
        }
    )
    data["plays"] = plays[-40:]
    _save(data)


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
    data: dict | None = None,
) -> tuple[int, int, float, int]:
    length = len(chain)
    data = data if data is not None else _load()
    key = f"{max(options or [length])}:{length}"
    learned = int(data["wins"].get(key, 0)) - int(data["losses"].get(key, 0))
    return (length, leftover, -jump, learned)


def hud_situation(fever_on: bool, fever_fill: float, has_chain: bool, has_bomb: bool, full: bool) -> str:
    if fever_on:
        gauge = "on"
    elif fever_fill >= 0.12:
        gauge = "up"
    else:
        gauge = "off"
    chain = "c" if has_chain else "n"
    bomb = "b" if has_bomb else "x"
    board = "f" if full else "s"
    return f"{gauge}_{chain}_{bomb}_{board}"


def hud_net(kind: str, sit: str, data: dict | None = None) -> int:
    data = data if data is not None else _load()
    hud = data.get("hud") or {}
    item = hud.get(f"{sit}:{kind}") if isinstance(hud.get(f"{sit}:{kind}"), dict) else {}
    return int(item.get("w") or 0) - int(item.get("l") or 0)


def should_hud(kind: str, sit: str, default: bool, data: dict | None = None) -> bool:
    data = data if data is not None else _load()
    hud = data.get("hud") or {}

    def pair(key: str) -> tuple[int, int]:
        item = hud.get(key) if isinstance(hud.get(key), dict) else {}
        return int(item.get("w") or 0), int(item.get("l") or 0)

    go_w, go_l = pair(f"{sit}:{kind}")
    skip_w, skip_l = pair(f"{sit}:skip_{kind}")
    if go_w + go_l + skip_w + skip_l < 4:
        return default
    return (go_w - go_l) >= (skip_w - skip_l)


def record_hud(sit: str, kind: str, pressed: bool, ok: bool) -> None:
    if not sit or not kind:
        return
    data = _load()
    hud = dict(data.get("hud") or {})
    key = f"{sit}:{kind}" if pressed else f"{sit}:skip_{kind}"
    item = dict(hud.get(key) or {}) if isinstance(hud.get(key), dict) else {}
    bucket = "w" if ok else "l"
    item[bucket] = int(item.get(bucket) or 0) + 1
    hud[key] = {"w": int(item.get("w") or 0), "l": int(item.get("l") or 0)}
    data["hud"] = hud
    _save(data)


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
