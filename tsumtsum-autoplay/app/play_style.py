from __future__ import annotations

import json
import random
from collections.abc import Callable
from pathlib import Path

from app.paths import APP_ROOT

PATH = APP_ROOT / "data" / "play_style.json"
UNLIKE_PATH = APP_ROOT / "data" / "unlike.json"
UNLIKE_SIM = 0.75
UNLIKE_MAX = 40
GOAL_COIN = 1200
_cache: dict | None = None
_dirty = False


def play_coin(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n >= 3000:
        return None
    return n


def _empty_rl() -> dict:
    return {"n": 0, "baseline": 0.0, "goal_coin": GOAL_COIN, "choices": {}}


def _empty_rl_length() -> dict:
    return {"n": 0, "baseline": 0.0, "choices": {}}


def _skill_coin_from_plays(plays: list) -> dict:
    choices: dict[str, dict[str, float | int]] = {}
    total_n = 0
    total_sum = 0.0
    for item in plays:
        if not isinstance(item, dict) or "coin" not in item:
            continue
        value = play_coin(item.get("coin"))
        if value is None:
            continue
        key = str(max(0, int(item.get("skill_ok") or 0)))
        entry = dict(choices.get(key) or {})
        entry["sum"] = float(entry.get("sum") or 0) + value
        entry["n"] = int(entry.get("n") or 0) + 1
        choices[key] = entry
        total_n += 1
        total_sum += value
    if total_n <= 0:
        return _empty_rl_length()
    return {
        "choices": choices,
        "n": total_n,
        "baseline": total_sum / total_n,
    }


def _empty() -> dict:
    return {
        "wins": {},
        "losses": {},
        "follow_max": 3,
        "plays": [],
        "hud": {},
        "rl": _empty_rl(),
        "rl_length": _empty_rl_length(),
        "rl_wait": _empty_rl_length(),
        "rl_bomb": _empty_rl_length(),
        "rl_skill": _empty_rl_length(),
        "rl_skill_coin": _empty_rl_length(),
    }


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if not PATH.is_file():
        _cache = _empty()
        return _cache
    try:
        payload = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        _cache = _empty()
        return _cache
    if not isinstance(payload, dict):
        _cache = _empty()
        return _cache
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
        if "skill_ok" in item:
            cleaned[-1]["skill_ok"] = int(item.get("skill_ok") or 0)
        if "coin" in item:
            kept = play_coin(item.get("coin"))
            if kept is not None:
                cleaned[-1]["coin"] = kept
        waits = _play_waits(item)
        if waits:
            cleaned[-1]["waits"] = waits
    hud_raw = payload.get("hud") if isinstance(payload.get("hud"), dict) else {}
    hud: dict[str, dict[str, int]] = {}
    for key, item in hud_raw.items():
        if not isinstance(item, dict):
            continue
        hud[str(key)] = {
            "w": int(item.get("w") or 0),
            "l": int(item.get("l") or 0),
        }
    _cache = {
        "wins": {str(key): int(value) for key, value in wins.items()},
        "losses": {str(key): int(value) for key, value in losses.items()},
        "follow_max": max(1, min(6, follow)),
        "plays": cleaned,
        "hud": hud,
        "rl": _rl_from(payload.get("rl")),
        "rl_length": _rl_length_from(payload.get("rl_length")),
        "rl_wait": _rl_length_from(payload.get("rl_wait")),
        "rl_bomb": _rl_length_from(payload.get("rl_bomb")),
        "rl_skill": _rl_length_from(payload.get("rl_skill")),
        "rl_skill_coin": _skill_coin_from_plays(cleaned),
    }
    return _cache


def _save(data: dict, disk: bool = False) -> None:
    global _cache, _dirty
    _cache = data
    if not disk:
        _dirty = True
        return
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
                "rl_length": data.get("rl_length") or _empty_rl_length(),
                "rl_wait": data.get("rl_wait") or _empty_rl_length(),
                "rl_bomb": data.get("rl_bomb") or _empty_rl_length(),
                "rl_skill": data.get("rl_skill") or _empty_rl_length(),
                "rl_skill_coin": data.get("rl_skill_coin") or _empty_rl_length(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _dirty = False


def flush_style() -> None:
    if _cache is not None and _dirty:
        _save(_cache, True)


def style_now() -> dict:
    return _load()


def history_text() -> str:
    data = _load()
    length = data.get("rl_length") if isinstance(data.get("rl_length"), dict) else {}
    coin = data.get("rl") if isinstance(data.get("rl"), dict) else {}
    wait = data.get("rl_wait") if isinstance(data.get("rl_wait"), dict) else {}
    bomb = data.get("rl_bomb") if isinstance(data.get("rl_bomb"), dict) else {}
    plays = list(data.get("plays") or [])
    length_n = int(length.get("n") or 0)
    wait_n = int(wait.get("n") or 0)
    bomb_n = int(bomb.get("n") or 0)
    coin_n = int(coin.get("n") or 0)
    length_avg = float(length.get("baseline") or 0)
    wait_avg = float(wait.get("baseline") or 0)
    bomb_avg = float(bomb.get("baseline") or 0)
    coin_avg = float(coin.get("baseline") or 0)
    goal = int(coin.get("goal_coin") or GOAL_COIN)
    nw = _num_width(length_n, wait_n, bomb_n, coin_n)
    aw = max(
        _num_width(int(length_avg), int(wait_avg), int(bomb_avg), int(coin_avg), goal),
        len(f"{length_avg:.1f}"),
        len(f"{wait_avg:.1f}"),
        len(f"{bomb_avg:.1f}"),
        len(f"{coin_avg:.1f}"),
    )
    lines = [
        f"長さ   回数 {length_n:>{nw}} / 平均 {length_avg:>{aw}.1f}",
        f"待ち   回数 {wait_n:>{nw}} / 平均 {wait_avg:>{aw}.1f}秒",
        f"ボム   回数 {bomb_n:>{nw}} / 平均 {bomb_avg:>{aw}.1f}秒",
        f"コイン 試合 {coin_n:>{nw}} / 平均 {coin_avg:>{aw}.1f} / 目標 {goal:>{aw}}",
        "",
    ]
    if not plays:
        return "\n".join(lines)
    clears = [int(item.get("clears") or 0) for item in plays]
    swipes = [int(item.get("swipes") or 0) for item in plays]
    cw = _num_width(*clears)
    sw = _num_width(*swipes)
    has_skill = any("skill_ok" in item for item in plays)
    has_coin = any("coin" in item for item in plays)
    ok_w = 1
    tap_w = 1
    coin_w = 1
    if has_skill:
        oks = [int(item.get("skill_ok") or 0) for item in plays if "skill_ok" in item]
        taps = [int(item.get("skills") or 0) for item in plays if "skill_ok" in item]
        ok_w = _num_width(*oks)
        tap_w = _num_width(*taps)
    if has_coin:
        coins = [int(item.get("coin") or 0) for item in plays if "coin" in item]
        coin_w = _num_width(*coins)
    for item in reversed(plays):
        line = f"消し {int(item.get('clears') or 0):>{cw}} / なぞり {int(item.get('swipes') or 0):>{sw}}"
        if has_skill:
            if "skill_ok" in item:
                skill = (
                    f"{int(item.get('skill_ok') or 0):>{ok_w}}/"
                    f"{int(item.get('skills') or 0):>{tap_w}}"
                )
                line += f" / スキル {skill}"
            elif has_coin:
                line += f" / スキル {' ' * (ok_w + 1 + tap_w)}"
        if has_coin:
            if "coin" in item:
                line += f" / コイン {int(item.get('coin') or 0):>{coin_w}}"
            else:
                line += f" / コイン {'':>{coin_w}}"
        waits = _play_waits(item)
        if waits:
            line += " / LossTime / " + " ".join(f"{wait:.1f}s" for wait in waits)
        lines.append(line)
    return "\n".join(lines)


def _play_waits(item: dict) -> list[float]:
    raw = item.get("waits")
    if not isinstance(raw, list):
        return []
    shown: list[float] = []
    for part in raw:
        try:
            shown.append(round(max(0.0, float(part)), 1))
        except (TypeError, ValueError):
            continue
    shown.sort(reverse=True)
    return shown[:3]


def _num_width(*nums: int) -> int:
    return max((len(str(int(n))) for n in nums), default=1)


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
        "goal_coin": int(raw.get("goal_coin") or GOAL_COIN),
        "choices": choices,
    }


def _rl_length_from(raw) -> dict:
    empty = _empty_rl_length()
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
        "choices": choices,
    }


def _rl_key(options: list[int], picked: int) -> str:
    return ",".join(str(n) for n in options) + f":{picked}"


def order_found(
    found: list[list[dict[str, int]]],
    leftovers: list[int] | None = None,
    leftover_fn: Callable[[list[dict[str, int]]], int] | None = None,
) -> tuple[list[list[dict[str, int]]], list[int], int]:
    if not found:
        return found, [], 0
    options = [len(item) for item in found]
    if len(found) == 1:
        return found, options, options[0]
    if leftovers is None or len(leftovers) != len(found):
        leftovers = [0] * len(found)
        cached = [False] * len(found)
    else:
        cached = [True] * len(found)
    bigs = [
        1 if any(int(piece.get("big") or 0) for piece in item) else 0
        for item in found
    ]
    data = _load()
    rl = data.get("rl_length") if isinstance(data.get("rl_length"), dict) else _empty_rl_length()
    choices = rl.get("choices") if isinstance(rl.get("choices"), dict) else {}
    matches = int(rl.get("n") or 0)
    scores: list[float] = []
    for item in found:
        key = _rl_key(options, len(item))
        entry = choices.get(key) if isinstance(choices.get(key), dict) else None
        n = int(entry.get("n") or 0) if entry else 0
        if n > 0:
            scores.append(float(entry.get("sum") or 0) / n)
        else:
            scores.append(float(len(item)))
    wait_rl = data.get("rl_wait") if isinstance(data.get("rl_wait"), dict) else _empty_rl_length()
    wait_choices = wait_rl.get("choices") if isinstance(wait_rl.get("choices"), dict) else {}
    wait_n = int(wait_rl.get("n") or 0)
    wait_base = float(wait_rl.get("baseline") or 0)
    waits: list[float] = []
    for item in found:
        key = _rl_key(options, len(item))
        entry = wait_choices.get(key) if isinstance(wait_choices.get(key), dict) else None
        n = int(entry.get("n") or 0) if entry else 0
        if n > 0:
            waits.append(round(float(entry.get("sum") or 0) / n, 1))
        else:
            waits.append(round(wait_base, 1))

    def leftover_at(index: int) -> int:
        if cached[index]:
            return leftovers[index]
        if leftover_fn is None:
            return 0
        leftovers[index] = int(leftover_fn(found[index]))
        cached[index] = True
        return leftovers[index]

    def pick_among(indices: list[int]) -> int:
        tied = list(indices)
        if wait_n > 0:
            best_wait = min(waits[i] for i in tied)
            tied = [i for i in tied if waits[i] == best_wait]
        best_len = max(scores[i] for i in tied)
        tied = [i for i in tied if scores[i] == best_len]
        lefts = [leftover_at(i) for i in tied]
        best_left = max(lefts)
        tied = [i for i in tied if leftover_at(i) == best_left]
        best_big = max(bigs[i] for i in tied)
        tied = [i for i in tied if bigs[i] == best_big]
        return tied[0]

    explore_n = wait_n if wait_n > 0 else matches
    if random.randrange(explore_n + 2) == 0:
        index = random.randrange(len(found))
    else:
        index = pick_among(list(range(len(found))))
    picked = found[index]
    rest = [item for i, item in enumerate(found) if i != index]
    return [picked] + rest, options, len(picked)


def record_rl_match(picks: list[tuple[list[int], int]], coin: int) -> None:
    kept = play_coin(coin)
    if kept is None or kept <= 0 or not picks:
        return
    data = _load()
    rl = _rl_from(data.get("rl"))
    choices = dict(rl.get("choices") or {})
    for options, picked in picks:
        if picked < 3:
            continue
        key = _rl_key(options, picked)
        item = dict(choices.get(key) or {}) if isinstance(choices.get(key), dict) else {}
        item["sum"] = float(item.get("sum") or 0) + kept
        item["n"] = int(item.get("n") or 0) + 1
        choices[key] = item
    prev_n = int(rl.get("n") or 0)
    n = prev_n + 1
    prev_base = float(rl.get("baseline") or 0)
    rl["choices"] = choices
    rl["n"] = n
    rl["baseline"] = (prev_base * prev_n + kept) / n
    data["rl"] = rl
    _save(data)


def record_rl_length(options: list[int], picked: int) -> None:
    if picked < 3:
        return
    data = _load()
    rl = _rl_length_from(data.get("rl_length"))
    choices = dict(rl.get("choices") or {})
    key = _rl_key(options, picked)
    item = dict(choices.get(key) or {}) if isinstance(choices.get(key), dict) else {}
    item["sum"] = float(item.get("sum") or 0) + picked
    item["n"] = int(item.get("n") or 0) + 1
    choices[key] = item
    prev_n = int(rl.get("n") or 0)
    n = prev_n + 1
    prev_base = float(rl.get("baseline") or 0)
    rl["choices"] = choices
    rl["n"] = n
    rl["baseline"] = (prev_base * prev_n + picked) / n
    data["rl_length"] = rl
    _save(data)


def record_rl_wait(options: list[int], picked: int, seconds: float) -> None:
    if picked < 3:
        return
    wait = max(0.0, float(seconds))
    data = _load()
    rl = _rl_length_from(data.get("rl_wait"))
    choices = dict(rl.get("choices") or {})
    key = _rl_key(options, picked)
    item = dict(choices.get(key) or {}) if isinstance(choices.get(key), dict) else {}
    item["sum"] = float(item.get("sum") or 0) + wait
    item["n"] = int(item.get("n") or 0) + 1
    choices[key] = item
    prev_n = int(rl.get("n") or 0)
    n = prev_n + 1
    prev_base = float(rl.get("baseline") or 0)
    rl["choices"] = choices
    rl["n"] = n
    rl["baseline"] = (prev_base * prev_n + wait) / n
    data["rl_wait"] = rl
    _save(data)


def should_bomb(sit: str, default: bool) -> bool:
    if not sit:
        return default
    data = _load()
    rl = _rl_length_from(data.get("rl_bomb"))
    n = int(rl.get("n") or 0)
    if n > 0 and random.randrange(n + 2) == 0:
        return random.randrange(2) == 0
    if n <= 0:
        return default
    choices = rl.get("choices") if isinstance(rl.get("choices"), dict) else {}
    tap = choices.get(f"{sit}:tap") if isinstance(choices.get(f"{sit}:tap"), dict) else None
    skip = choices.get(f"{sit}:skip") if isinstance(choices.get(f"{sit}:skip"), dict) else None
    tap_n = int(tap.get("n") or 0) if tap else 0
    skip_n = int(skip.get("n") or 0) if skip else 0
    if tap_n <= 0 or skip_n <= 0:
        return default
    tap_avg = float(tap.get("sum") or 0) / tap_n
    skip_avg = float(skip.get("sum") or 0) / skip_n
    if tap_avg < skip_avg:
        return True
    if skip_avg < tap_avg:
        return False
    return default


def record_rl_bomb(sit: str, pressed: bool, seconds: float) -> None:
    if not sit:
        return
    wait = max(0.0, float(seconds))
    data = _load()
    rl = _rl_length_from(data.get("rl_bomb"))
    choices = dict(rl.get("choices") or {})
    key = f"{sit}:{'tap' if pressed else 'skip'}"
    item = dict(choices.get(key) or {}) if isinstance(choices.get(key), dict) else {}
    item["sum"] = float(item.get("sum") or 0) + wait
    item["n"] = int(item.get("n") or 0) + 1
    choices[key] = item
    prev_n = int(rl.get("n") or 0)
    n = prev_n + 1
    prev_base = float(rl.get("baseline") or 0)
    rl["choices"] = choices
    rl["n"] = n
    rl["baseline"] = (prev_base * prev_n + wait) / n
    data["rl_bomb"] = rl
    _save(data)


def should_skill(sit: str, default: bool, skill_n: int = 0) -> bool:
    data = _load()
    coins = _rl_length_from(data.get("rl_skill_coin"))
    coin_n = int(coins.get("n") or 0)
    if coin_n > 0 and random.randrange(coin_n + 2) == 0:
        return random.randrange(2) == 0
    if coin_n <= 0:
        return default
    choices = coins.get("choices") if isinstance(coins.get("choices"), dict) else {}
    base = float(coins.get("baseline") or 0)

    def coin_at(count: int) -> tuple[int, float]:
        key = str(max(0, int(count)))
        entry = choices.get(key) if isinstance(choices.get(key), dict) else None
        n = int(entry.get("n") or 0) if entry else 0
        if n <= 0:
            return 0, base
        return n, float(entry.get("sum") or 0) / n

    now_n, now_avg = coin_at(skill_n)
    next_n, next_avg = coin_at(skill_n + 1)
    if now_n > 0 and next_n > 0:
        if next_avg > now_avg:
            return True
        if now_avg > next_avg:
            return False
    elif next_n > 0 and now_n <= 0 and next_avg > base:
        return True
    return default


def record_rl_skill(sit: str, pressed: bool, seconds: float) -> None:
    if not sit:
        return
    wait = max(0.0, float(seconds))
    data = _load()
    rl = _rl_length_from(data.get("rl_skill"))
    choices = dict(rl.get("choices") or {})
    key = f"{sit}:{'tap' if pressed else 'skip'}"
    item = dict(choices.get(key) or {}) if isinstance(choices.get(key), dict) else {}
    item["sum"] = float(item.get("sum") or 0) + wait
    item["n"] = int(item.get("n") or 0) + 1
    choices[key] = item
    prev_n = int(rl.get("n") or 0)
    n = prev_n + 1
    prev_base = float(rl.get("baseline") or 0)
    rl["choices"] = choices
    rl["n"] = n
    rl["baseline"] = (prev_base * prev_n + wait) / n
    data["rl_skill"] = rl
    _save(data)


def record_rl_skill_coin(skill_n: int, coin: int) -> None:
    kept = play_coin(coin)
    if kept is None:
        return
    data = _load()
    rl = _rl_length_from(data.get("rl_skill_coin"))

    def add(count: int, value: int) -> None:
        nonlocal rl
        choices = dict(rl.get("choices") or {})
        key = str(max(0, int(count)))
        item = dict(choices.get(key) or {}) if isinstance(choices.get(key), dict) else {}
        item["sum"] = float(item.get("sum") or 0) + value
        item["n"] = int(item.get("n") or 0) + 1
        choices[key] = item
        prev_n = int(rl.get("n") or 0)
        n = prev_n + 1
        prev_base = float(rl.get("baseline") or 0)
        rl = {
            "choices": choices,
            "n": n,
            "baseline": (prev_base * prev_n + value) / n,
        }

    if int(rl.get("n") or 0) <= 0:
        for item in data.get("plays") or []:
            if not isinstance(item, dict) or "coin" not in item:
                continue
            value = play_coin(item.get("coin"))
            if value is None:
                continue
            add(int(item.get("skill_ok") or 0), value)
        data["rl_skill_coin"] = rl
        _save(data)
        return
    add(skill_n, kept)
    data["rl_skill_coin"] = rl
    _save(data)


def record_play(
    clears: int,
    swipes: int,
    skills: int,
    skill_ok: int,
    bombs: int,
    fans: int,
    coin: int | None = None,
    waits: list[float] | None = None,
) -> None:
    data = _load()
    plays = list(data.get("plays") or [])
    item = {
        "clears": int(clears),
        "swipes": int(swipes),
        "skills": int(skills),
        "skill_ok": int(skill_ok),
        "bombs": int(bombs),
        "fans": int(fans),
    }
    if coin is not None:
        kept = play_coin(coin)
        if kept is not None:
            item["coin"] = kept
    shown_waits = _play_waits({"waits": waits or []})
    if shown_waits:
        item["waits"] = shown_waits
    plays.append(item)
    data["plays"] = plays[-40:]
    _save(data)
    if item.get("coin") is not None:
        record_rl_skill_coin(int(item.get("skill_ok") or 0), int(item["coin"]))
    flush_style()


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


def bomb_situation(sit: str, n: int) -> str:
    return f"{sit}_{max(0, int(n))}"


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
