from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from tsumtsum_analyze.coin_read import CoinReader
from tsumtsum_analyze.extractor import SamplePoint, VideoInfo, format_timecode, read_video_info
from tsumtsum_analyze.item_slots import (
    ITEM_RESULT_NAMES,
    ITEM_SLOT_KEYS,
    ItemSlotStore,
    box_means_used,
    item_coin_cost,
)
from tsumtsum_analyze.item_teach import TsumReader, shown_tsum_name, tsum_id_for_name
from tsumtsum_analyze.scene_labels import OTHER_KEY, SceneLabels
from tsumtsum_analyze.scene_scan import extract_scene_frames, find_scene_points
from tsumtsum_analyze.skill_read import count_skill_uses


@dataclass
class AnalysisResult:
    video_path: Path
    duration: str
    go_timeup: str = "—"
    fever_count: str = "—"
    skill_count: str = "—"
    used_tsum: str = "—"
    used_items: str = "—"
    item_cost: str = "—"
    play_coin: str = "—"
    result_coin: str = "—"
    play_net: str = "—"
    result_net: str = "—"
    coin_ratio: str = "—"
    play_per_min: str = "—"
    result_per_min: str = "—"
    points: list[SamplePoint] = field(default_factory=list)
    message: str = ""


def _is_item(labels: SceneLabels, point: SamplePoint) -> bool:
    kind = str(getattr(point, "kind", "") or "")
    if not kind or kind in {"sample", OTHER_KEY}:
        return False
    name = labels.name_of(kind).lower()
    return kind in labels.keys_named("item") or name == "item"


def _coin_key(labels: SceneLabels, point: SamplePoint) -> str | None:
    kind = str(getattr(point, "kind", "") or "")
    if not kind or kind in {"sample", OTHER_KEY}:
        return None
    name = labels.name_of(kind).lower()
    if kind in labels.keys_named("result") or name == "result":
        return "result_coin"
    if kind in labels.keys_named("coin", "コイン") or name in {"coin", "コイン"}:
        return "coin"
    return None


def _go_timeup_pairs(labels: SceneLabels, points: list[SamplePoint]) -> list[tuple[float, float]]:
    go_keys = set(labels.keys_named("go"))
    timeup_keys = set(labels.keys_named("timeup", "time up", "time_up"))
    goes = sorted((p for p in points if getattr(p, "kind", "") in go_keys), key=lambda p: p.seconds)
    timeups = sorted((p for p in points if getattr(p, "kind", "") in timeup_keys), key=lambda p: p.seconds)
    used: set[int] = set()
    pairs: list[tuple[float, float]] = []
    for go in goes:
        nxt = next((item for item in timeups if item.seconds > go.seconds and id(item) not in used), None)
        if nxt is None:
            continue
        used.add(id(nxt))
        pairs.append((go.seconds, nxt.seconds))
    return pairs


def _join_numbers(values: list[str]) -> str:
    cleaned = [value for value in values if value]
    if not cleaned:
        return "—"
    return "、".join(cleaned)


def _coin_int(text: str) -> int | None:
    digits = "".join(char for char in (text or "") if char.isdigit())
    if not digits:
        return None
    return int(digits)


def _coin_ints(hits: list[tuple[float, str]]) -> list[tuple[float, int]]:
    numbers: list[tuple[float, int]] = []
    for seconds, text in sorted(hits, key=lambda item: item[0]):
        number = _coin_int(text)
        if number is not None:
            numbers.append((seconds, number))
    return numbers


def _pick_number_in_window(
    numbers: list[tuple[float, int]],
    start: float,
    end: float,
    after: float,
) -> int | None:
    in_window = [item for item in numbers if start < item[0] < end]
    later = [item for item in in_window if item[0] >= after]
    if later:
        return later[0][1]
    if in_window:
        return in_window[0][1]
    return None


def _format_net(amount: int | None) -> str:
    if amount is None:
        return "—"
    return f"{amount:,}"


def _format_per_min(amount: int | None, duration_sec: float) -> str:
    if amount is None or duration_sec <= 0:
        return "—"
    return f"{(amount / duration_sec) * 60.0:.2f} /m"


def _format_ratio(result: int, coin: int) -> str:
    if coin <= 0:
        return "—"
    times = result / coin
    if abs(times - round(times)) < 0.05:
        return f"{int(round(times))}倍"
    return f"{times:.2f}倍"


def _rate_lines(values: list[str]) -> str:
    if not values:
        return "—"
    if len(values) == 1:
        return values[0]
    return "\n".join(f"{index}回目  {text}" for index, text in enumerate(values, start=1))


def _item_cost_before_go(
    item_reads: list[tuple[float, int]],
    prev_end: float,
    go: float,
) -> int:
    items = [item for item in item_reads if prev_end < item[0] <= go]
    if not items:
        return 0
    return items[-1][1]


def _fill_coin_efficiency(
    result: AnalysisResult,
    pairs: list[tuple[float, float]],
    play_hits: list[tuple[float, str]],
    result_hits: list[tuple[float, str]],
    item_reads: list[tuple[float, int]],
) -> None:
    coins = _coin_ints(play_hits)
    results = _coin_ints(result_hits)
    games: list[tuple[float, int | None, int | None]] = []
    prev_end = 0.0
    for index, (go, timeup) in enumerate(pairs):
        next_go = pairs[index + 1][0] if index + 1 < len(pairs) else float("inf")
        cost = _item_cost_before_go(item_reads, prev_end, go)
        play = _pick_number_in_window(coins, go, next_go, timeup)
        result_n = _pick_number_in_window(results, go, next_go, timeup)
        games.append(
            (
                timeup - go,
                None if play is None else play - cost,
                None if result_n is None else result_n - cost,
            )
        )
        prev_end = timeup
    if games:
        result.play_net = _rate_lines([_format_net(play) for _duration, play, _result in games])
        result.result_net = _rate_lines(
            [_format_net(result_n) for _duration, _play, result_n in games]
        )
        result.play_per_min = _rate_lines(
            [_format_per_min(play, duration) for duration, play, _result in games]
        )
        result.result_per_min = _rate_lines(
            [_format_per_min(result_n, duration) for duration, _play, result_n in games]
        )
    if coins and results:
        lines: list[str] = []
        for seconds, result_number in results:
            previous = [item for item in coins if item[0] <= seconds]
            play_number = previous[-1][1] if previous else coins[0][1]
            lines.append(_format_ratio(result_number, play_number))
        result.coin_ratio = "\n".join(lines)


_PROGRESS_TOTAL = 1000
_SEARCH_SPAN = 550
_SAVE_SPAN = 50
_READ_SPAN = 100
_SKILL_SPAN = 300


def _map_progress(current: int, total: int, start: int, span: int) -> int:
    if total <= 0:
        return start
    return start + int(span * max(0, min(current, total)) / total)


def analyze_video(
    path: Path,
    output_dir: Path,
    progress=None,
    should_stop=None,
) -> AnalysisResult:
    info = read_video_info(path)
    labels = SceneLabels()
    want = set(labels.extract_keys()) | set(labels.hidden_keys())

    def emit(current: int, message: str) -> None:
        if progress:
            progress(current, _PROGRESS_TOTAL, message)

    emit(0, "画面を探しています")

    def search_progress(current: int, total: int, _name: str) -> None:
        emit(_map_progress(current, total, 0, _SEARCH_SPAN), "画面を探しています")

    points = find_scene_points(
        info,
        progress=search_progress if progress else None,
        want_kinds=want,
        should_stop=should_stop,
    )
    if should_stop and should_stop():
        raise RuntimeError("解析を中止")
    fever_keys = set(labels.keys_named("fever"))
    fever_n = sum(1 for point in points if getattr(point, "kind", "") in fever_keys)
    show = set(labels.extract_keys())
    visible = [point for point in points if getattr(point, "kind", "") in show]
    path_by_index: dict[int, Path] = {}
    if visible:
        emit(_SEARCH_SPAN, "画面を保存しています")

        def save_progress(current: int, total: int, _name: str) -> None:
            emit(
                _map_progress(current, total, _SEARCH_SPAN, _SAVE_SPAN),
                "画面を保存しています",
            )

        saved_paths = extract_scene_frames(
            info,
            visible,
            output_dir,
            progress=save_progress if progress else None,
            should_stop=should_stop,
        )
        path_by_index = {
            point.index: dest
            for point, dest in zip(visible, saved_paths)
            if dest is not None
        }
    result = AnalysisResult(
        video_path=path,
        duration=info.format_duration(),
        fever_count=f"{fever_n}回" if fever_n else "—",
        points=visible,
    )
    pairs = _go_timeup_pairs(labels, visible)
    if pairs:
        if len(pairs) == 1:
            start, end = pairs[0]
            result.go_timeup = format_timecode(end - start)
        else:
            result.go_timeup = "\n".join(
                f"{index}回目  {format_timecode(end - start)}"
                for index, (start, end) in enumerate(pairs, start=1)
            )

    coin_reader = CoinReader()
    item_store = ItemSlotStore()
    tsum_reader = TsumReader()
    play_hits: list[tuple[float, str]] = []
    result_hits: list[tuple[float, str]] = []
    tsum_names: list[str] = []
    used_item_lines: list[str] = []
    costs: list[str] = []
    item_reads: list[tuple[float, int]] = []
    item_tsum_by_point: dict[int, str] = {}

    pending_coins = [p for p in visible if _coin_key(labels, p)]
    item_points = [p for p in visible if _is_item(labels, p)]
    total_reads = max(len(pending_coins) + len(item_points), 1)
    read_start = _SEARCH_SPAN + _SAVE_SPAN
    done = 0
    for point in pending_coins:
        if should_stop and should_stop():
            raise RuntimeError("解析を中止")
        done += 1
        emit(
            _map_progress(done, total_reads, read_start, _READ_SPAN),
            f"コインを読んでいます  {done}/{len(pending_coins)}",
        )
        image_path = path_by_index.get(point.index)
        key = _coin_key(labels, point)
        number = ""
        try:
            if image_path is not None and image_path.is_file() and key:
                _box, number = coin_reader.inspect_path(image_path, key)
        except Exception:
            number = ""
        if key == "coin":
            play_hits.append((point.seconds, number or ""))
        elif key == "result_coin":
            result_hits.append((point.seconds, number or ""))

    for point in item_points:
        if should_stop and should_stop():
            raise RuntimeError("解析を中止")
        done += 1
        emit(
            _map_progress(done, total_reads, read_start, _READ_SPAN),
            f"アイテムを読んでいます  {done}/{len(item_points)}",
        )
        image_path = path_by_index.get(point.index)
        used: set[str] = set()
        tsum_name = ""
        try:
            if image_path is not None and image_path.is_file():
                with Image.open(image_path) as opened:
                    rgb = opened.convert("RGB")
                width, height = rgb.size
                for slot in ITEM_SLOT_KEYS:
                    box = item_store.box_for(slot, width, height)
                    if box is None:
                        continue
                    if box_means_used(rgb, box):
                        used.add(slot)
                tsum_name = tsum_reader.read_screen(rgb)
        except Exception:
            pass
        if tsum_name:
            tsum_names.append(shown_tsum_name(tsum_name))
            item_tsum_by_point[id(point)] = tsum_name
        used_labels = [ITEM_RESULT_NAMES.get(slot, slot) for slot in ITEM_SLOT_KEYS if slot in used]
        used_item_lines.append("、".join(used_labels) if used_labels else "なし")
        costs.append(f"{item_coin_cost(used):,}")
        item_reads.append((point.seconds, item_coin_cost(used)))

    result.play_coin = _join_numbers([text for _seconds, text in play_hits])
    result.result_coin = _join_numbers([text for _seconds, text in result_hits])
    result.used_tsum = "\n".join(tsum_names) if tsum_names else "—"
    result.used_items = "\n".join(used_item_lines) if used_item_lines else "—"
    result.item_cost = "\n".join(costs) if costs else "—"
    _fill_coin_efficiency(result, pairs, play_hits, result_hits, item_reads)

    windows: list[tuple[float, float, str]] = []
    prev_end = 0.0
    for go, timeup in pairs:
        items = [
            point
            for point in visible
            if _is_item(labels, point) and prev_end < point.seconds <= go
        ]
        tsum_id = ""
        if items:
            tsum_id = tsum_id_for_name(item_tsum_by_point.get(id(items[-1]), "")) or ""
        elif len(item_points) == 1:
            tsum_id = tsum_id_for_name(item_tsum_by_point.get(id(item_points[0]), "")) or ""
        if tsum_id:
            windows.append((go, timeup, tsum_id))
        prev_end = timeup
    skill_n = None
    if windows:
        skill_start = _SEARCH_SPAN + _SAVE_SPAN + _READ_SPAN
        emit(skill_start, "スキルを数えています")

        def skill_progress(current: int, total: int, _name: str) -> None:
            emit(
                _map_progress(current, total, skill_start, _SKILL_SPAN),
                "スキルを数えています",
            )

        skill_n = count_skill_uses(info, windows, progress=skill_progress)
    if skill_n is None:
        result.skill_count = "—"
    else:
        result.skill_count = f"{skill_n}回"
    emit(_PROGRESS_TOTAL, result.message or "解析しています")
    if visible:
        result.message = f"{labels.extract_names()} を {len(visible)} 枚見つけました。"
    else:
        result.message = f"{labels.extract_names()} の画面は見つかりませんでした。"
    return result
