from __future__ import annotations

import json
import threading
import time

from app.paths import APP_ROOT

PATH = APP_ROOT / "data" / "game_records.jsonl"
_lock = threading.Lock()


def load_game_records() -> list[dict]:
    if not PATH.is_file():
        return []
    with _lock:
        text = PATH.read_text(encoding="utf-8")
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def append_game_record(
    started: str,
    tsum: str,
    items: list[str] | None,
    play_time: int | None,
    coin: int | None,
    result_coin: int | None,
) -> dict:
    names = [str(name) for name in (items or []) if str(name)]
    item = {
        "id": time.time_ns(),
        "started": str(started or ""),
        "tsum": str(tsum or ""),
        "items": names,
        "play_time": None if play_time is None else int(play_time),
        "coin": None if coin is None else int(coin),
        "result_coin": None if result_coin is None else int(result_coin),
    }
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def set_result_coin(record_id: int, result_coin: int) -> dict | None:
    if record_id is None or result_coin is None:
        return None
    with _lock:
        if not PATH.is_file():
            return None
        lines = PATH.read_text(encoding="utf-8").splitlines()
        found = None
        index = -1
        for row in range(len(lines) - 1, -1, -1):
            raw = lines[row].strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("id") == record_id:
                found = item
                index = row
                break
        if found is None or found.get("result_coin") is not None:
            return None
        found["result_coin"] = int(result_coin)
        lines[index] = json.dumps(found, ensure_ascii=False)
        PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return found
