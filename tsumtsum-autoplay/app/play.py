from __future__ import annotations

import colorsys
import json
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

from PySide6.QtCore import QPoint, QRect, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from app.bluestacks import capture_screen_path, reset_swipe_mouse, swipe_path, tap
from app.intro import (
    Stopped,
    _check_stop,
    _continue_button,
    _match_start_button,
    _play_button,
    _slow_tap,
)
from app.trainer_bridge import TRAINER_ROOT, load_play_tools

MIN_CHAIN = 3
BOARD_TSUMS = 8
TIMEUP_SCORE = 0.18

StatusFn = Callable[[str], None]


class PlayWorker(QThread):
    failed = Signal(str)
    stopped = Signal()
    completed = Signal()
    status = Signal(str)
    preview = Signal(QImage)

    def __init__(
        self,
        stop: Event,
        parent=None,
        start_match: bool = False,
        kind_count: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._stop = stop
        self._start_match = start_match
        self._kind_count = kind_count

    def run(self) -> None:
        try:
            run_play(
                self.status.emit,
                self._stop,
                start_match=self._start_match,
                preview=self.preview.emit,
                kind_count=self._kind_count,
            )
        except Stopped:
            self.stopped.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit()


def run_play(
    report: StatusFn | None,
    stop: Event | None,
    start_match: bool = False,
    preview: Callable[[QImage], None] | None = None,
    kind_count: int | None = None,
) -> None:
    def say(text: str) -> None:
        if report is not None:
            report(text)

    say("モデルを読み込み中")
    try:
        predictor, candidates = load_play_tools()
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "画面認識に必要なライブラリがありません。画面認識アプリと同じ Python で起動してください。"
        ) from exc
    if getattr(predictor, "piece_model", None) is None:
        raise RuntimeError("ツムの〇モデルがありません。画面認識アプリで学習してください。")
    if getattr(predictor, "scene_model", None) is None:
        raise RuntimeError("TIME UP のモデルがありません。")

    say("プレイを開始します")
    reset_swipe_mouse()
    used_keys: list[frozenset[tuple[int, int]]] = []
    last_count = 0
    game = None
    saw_board = False
    kinds = 5
    kinds_locked = False
    if kind_count is not None and int(kind_count) >= 1:
        kinds = int(kind_count)
        kinds_locked = True
        say(f"種類 {kinds}")
    if start_match:
        seen, locked = _click_start_or_continue(say, stop)
        if not kinds_locked and locked:
            kinds = seen
            kinds_locked = True
            say(f"5＞4 {'使用' if kinds == 4 else '未使用'} / 種類 {kinds}")
    while True:
        _check_stop(stop)
        try:
            path = capture_screen_path()
            image = QImage(str(path))
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.25, stop)
            continue
        if game is None:
            boxes = predictor.predict_all(path)
            game = boxes.get("game")
        timeup = _timeup_score(predictor, path)
        if timeup >= TIMEUP_SCORE:
            say(f"TIME UP {timeup:.0%}")
            return
        _check_stop(stop)
        if not kinds_locked:
            used = _five_to_four_used_path(path)
            if used is not None:
                kinds = 4 if used else 5
                kinds_locked = True
                say(f"5＞4 {'使用' if used else '未使用'} / 種類 {kinds}")
        pieces = predictor.predict_pieces(path, game, kinds=kinds)
        tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        if len(tsums) < BOARD_TSUMS and not saw_board:
            boxes = predictor.predict_all(path)
            game = boxes.get("game")
            pieces = predictor.predict_pieces(path, None, kinds=kinds)
            tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        _check_stop(stop)
        if len(tsums) >= BOARD_TSUMS:
            saw_board = True
            kinds_locked = True
        if not saw_board:
            if len(tsums) < BOARD_TSUMS:
                say(f"ツム {len(tsums)}体（盤面が少ない）")
                if _tap_start_or_continue(image, say, stop):
                    continue
                play = None if image.isNull() else _play_button(image)
                if play is not None:
                    say("プレイをクリックします")
                    _slow_tap(play.center().x(), play.center().y())
                    _sleep_stop(2.0, stop)
                    continue
                continue
        if last_count > 0 and (
            len(tsums) <= last_count - MIN_CHAIN or len(tsums) >= last_count + 5
        ):
            used_keys.clear()
        last_count = len(tsums)
        bombs = [piece for piece in pieces if str(piece.get("kind") or "") == "bomb"]
        if bombs and saw_board:
            bomb = max(bombs, key=lambda piece: int(piece.get("r") or 0))
            say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
            tap(int(bomb["x"]), int(bomb["y"]))
            used_keys.clear()
            _sleep_stop(0.18, stop)
            continue
        _group_by_type(predictor, path, pieces, kinds)
        chain = _pick_chain(predictor, path, pieces, candidates, used_keys, say)
        if chain:
            used_keys.append(_chain_key(chain))
            if not _swipe_chain(chain, pieces, image, game, len(tsums), say, stop, preview):
                _sleep_stop(0.08, stop)
                continue
            leftover = [piece for piece in pieces if id(piece) not in {id(item) for item in chain}]
            nxt = _pick_chain(predictor, path, leftover, candidates, used_keys, say)
            if nxt:
                used_keys.append(_chain_key(nxt))
                _swipe_chain(nxt, leftover, image, game, len(leftover), say, stop, preview)
            continue
        say(f"ツム {len(tsums)}体 / なぞれる3体以上なし")
        continue


def _swipe_chain(
    chain: list[dict[str, int]],
    pieces: list[dict[str, int]],
    image: QImage,
    game: dict[str, int] | None,
    tsum_count: int,
    say: StatusFn,
    stop: Event | None,
    preview: Callable[[QImage], None] | None,
) -> bool:
    points = [(int(piece["x"]), int(piece["y"])) for piece in chain]
    cells = {(x // 24, y // 24) for x, y in points}
    if len(points) < MIN_CHAIN or len(cells) < MIN_CHAIN:
        say("同じ位置に重なっているので見送り")
        return False
    route = " → ".join(f"{x},{y}" for x, y in points)
    say(f"ツム {tsum_count}体 / チェーン {len(chain)}体")
    say(f"経路 {route}")
    if preview is not None:
        preview(_draw_plan(image, pieces, chain, game))
    say("なぞっています")
    _check_stop(stop)
    how = swipe_path(points, screen_w=image.width(), screen_h=image.height(), stop=stop)
    say(how)
    return True


def _timeup_score(predictor, path: Path) -> float:
    model = getattr(predictor, "scene_model", None)
    transform = getattr(predictor, "_scene_transform", None)
    if model is None or transform is None:
        return 0.0
    import torch
    from PIL import Image

    with Image.open(path) as board:
        view = _portrait_frame(board.convert("RGB"))
    tensor = transform(view).unsqueeze(0).to(predictor.device)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    if probs.numel() < 3:
        return 0.0
    return float(probs[2].item())


def _portrait_frame(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width <= height:
        return image
    sample_w = min(160, width)
    sample_h = max(1, int(round(height * sample_w / width)))
    sample = image.resize((sample_w, sample_h))
    left_s = 0
    while left_s < sample_w - 1 and _column_luma(sample, left_s) < 14:
        left_s += 1
    right_s = sample_w - 1
    while right_s > left_s and _column_luma(sample, right_s) < 14:
        right_s -= 1
    scale = width / sample_w
    left = int(left_s * scale)
    right = min(width, int((right_s + 1) * scale))
    if right - left < height * 0.35:
        strip_w = max(1, int(height * 9 / 16))
        left = max(0, (width - strip_w) // 2)
        right = min(width, left + strip_w)
    return image.crop((left, 0, right, height))


def _column_luma(image: Image.Image, x: int) -> float:
    height = image.size[1]
    total = 0.0
    for y in range(height):
        red, green, blue = image.getpixel((x, y))[:3]
        total += 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return total / max(height, 1)


def _sleep_stop(seconds: float, stop: Event | None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        _check_stop(stop)
        time.sleep(min(0.2, max(0.0, end - time.time())))


def _click_start_or_continue(say: StatusFn, stop: Event | None) -> tuple[int, bool]:
    deadline = time.time() + 12
    kinds = 5
    locked = False
    while time.time() < deadline:
        _check_stop(stop)
        try:
            path = capture_screen_path()
            image = QImage(str(path))
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.8, stop)
            continue
        if image.isNull():
            _sleep_stop(0.4, stop)
            continue
        used = _five_to_four_used_path(path)
        if used is not None:
            kinds = 4 if used else 5
            locked = True
        if _tap_start_or_continue(image, say, stop):
            return kinds, locked
        say("スタートまたは続けるを待っています")
        _sleep_stop(0.35, stop)
    return kinds, locked


def _tap_start_or_continue(image: QImage, say: StatusFn, stop: Event | None) -> bool:
    if image.isNull():
        return False
    start = _match_start_button(image)
    resume = _continue_button(image)
    if start is not None:
        say("スタートをクリックします")
        _slow_tap(start.center().x(), start.center().y())
        _sleep_stop(1.2, stop)
        return True
    if resume is not None:
        say("続けるをクリックします")
        _slow_tap(resume.center().x(), resume.center().y())
        _sleep_stop(1.2, stop)
        return True
    return False


_SLOT_5TO4: tuple[dict[str, int], int, int] | None | bool = False
SLOT_ON = 0.28


def _five_to_four_slot() -> tuple[dict[str, int], int, int] | None:
    global _SLOT_5TO4
    if _SLOT_5TO4 is not False:
        return _SLOT_5TO4
    path = TRAINER_ROOT / "data" / "item_slots.json"
    loaded = None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("5to4") or []:
            box = item.get("box")
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if not box or width <= 0 or height <= 0:
                continue
            loaded = (
                {
                    "x": int(box["x"]),
                    "y": int(box["y"]),
                    "w": max(1, int(box["w"])),
                    "h": max(1, int(box["h"])),
                },
                width,
                height,
            )
            break
    except Exception:
        loaded = None
    _SLOT_5TO4 = loaded
    return loaded


def _five_to_four_used_path(path: Path) -> bool | None:
    from PIL import Image

    with Image.open(path) as board:
        return _five_to_four_used_pil(board.convert("RGB"))


def _five_to_four_used_pil(image) -> bool | None:
    slot = _five_to_four_slot()
    if slot is None:
        return None
    box, src_w, src_h = slot
    view = _portrait_frame(image)
    scaled = _scale_item_box(box, src_w, src_h, view.size[0], view.size[1])
    yellow, blue = _slot_yellow_blue(view, scaled)
    if yellow + blue < SLOT_ON:
        return None
    return yellow > blue


def read_kind_count() -> int | None:
    try:
        path = capture_screen_path()
    except Exception:
        return None
    used = _five_to_four_used_path(path)
    if used is None:
        return None
    return 4 if used else 5


def _scale_item_box(
    box: dict[str, int], src_w: int, src_h: int, dst_w: int, dst_h: int
) -> dict[str, int]:
    sx = dst_w / max(src_w, 1)
    sy = dst_h / max(src_h, 1)
    x = int(round(int(box["x"]) * sx))
    y = int(round(int(box["y"]) * sy))
    w = max(1, int(round(int(box["w"]) * sx)))
    h = max(1, int(round(int(box["h"]) * sy)))
    x = max(0, min(x, max(dst_w - 1, 0)))
    y = max(0, min(y, max(dst_h - 1, 0)))
    w = min(w, max(dst_w - x, 1))
    h = min(h, max(dst_h - y, 1))
    return {"x": x, "y": y, "w": w, "h": h}


def _slot_yellow_blue(image, box: dict[str, int]) -> tuple[float, float]:
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(image.width, left + max(1, int(box["w"])))
    bottom = min(image.height, top + max(1, int(box["h"])))
    crop = image.crop((left, top, right, bottom))
    width, height = crop.size
    if width < 2 or height < 2:
        return 0.0, 0.0
    inset_x = max(1, int(width * 0.2))
    inset_y = max(1, int(height * 0.2))
    inner = crop.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    iw, ih = inner.size
    step_x = max(1, iw // 24)
    step_y = max(1, ih // 24)
    pixels = inner.load()
    total = 0
    yellow = 0
    blue = 0
    for yy in range(0, ih, step_y):
        for xx in range(0, iw, step_x):
            red, green, blue_v = pixels[xx, yy][:3]
            hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue_v / 255.0)
            total += 1
            if 0.10 <= hue <= 0.18 and sat >= 0.30 and val >= 0.35:
                yellow += 1
            elif 0.52 <= hue <= 0.72 and sat >= 0.28 and val >= 0.25:
                blue += 1
    if total <= 0:
        return 0.0, 0.0
    return yellow / total, blue / total


def _pick_chain(
    predictor,
    path: Path,
    pieces: list[dict[str, int]],
    candidates,
    used_keys: list[frozenset[tuple[int, int]]],
    say: StatusFn,
) -> list[dict[str, int]]:
    found = [chain for chain in candidates(pieces, 8) if len(chain) >= MIN_CHAIN]
    if found:
        say("候補 " + " / ".join(str(len(chain)) for chain in found))
    for chain in found:
        same = _keep_same_type(predictor, path, chain)
        if len(same) < MIN_CHAIN:
            continue
        if _chain_too_similar(same, used_keys):
            continue
        return same
    matched = []
    for chain in found:
        same = _keep_same_type(predictor, path, chain)
        if len(same) >= MIN_CHAIN:
            matched.append(same)
    if matched:
        used_keys.clear()
        return matched[0]
    return []


def _group_by_type(predictor, path: Path, pieces: list[dict[str, int]], kinds: int) -> None:
    tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
    if not tsums:
        return
    vecs = _type_vectors(predictor, path, tsums)
    if vecs is None:
        return
    for piece, vec in zip(tsums, vecs):
        piece["_vec"] = vec
    _split_mixed_groups(tsums)


def _split_mixed_groups(tsums: list[dict[str, int]], min_sim: float = 0.75) -> None:
    by_group: dict[int, list[dict[str, int]]] = {}
    for piece in tsums:
        by_group.setdefault(int(piece.get("group") or 1), []).append(piece)
    next_id = max(by_group, default=0) + 1
    for members in by_group.values():
        count = len(members)
        if count < 2:
            continue
        parent = list(range(count))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for i in range(count):
            left = members[i].get("_vec")
            if left is None:
                continue
            for j in range(i + 1, count):
                right = members[j].get("_vec")
                if right is None:
                    continue
                if _cosine(left, right) < min_sim:
                    continue
                a, b = find(i), find(j)
                if a != b:
                    parent[b] = a
        labels = [find(index) for index in range(count)]
        unique: list[int] = []
        for label in labels:
            if label not in unique:
                unique.append(label)
        if len(unique) <= 1:
            continue
        remap = {unique[0]: int(members[0].get("group") or 1)}
        for label in unique[1:]:
            remap[label] = next_id
            next_id += 1
        for piece, label in zip(members, labels):
            piece["group"] = remap[label]


def _keep_same_type(predictor, path: Path, chain: list[dict[str, int]]) -> list[dict[str, int]]:
    if len(chain) < MIN_CHAIN:
        return []
    vecs = [piece.get("_vec") for piece in chain]
    if any(vec is None for vec in vecs):
        loaded = _type_vectors(predictor, path, chain)
        if loaded is None:
            group = int(chain[0].get("group") or 0)
            if group and all(int(piece.get("group") or 0) == group for piece in chain):
                return chain
            return []
        vecs = loaded
    best: list[dict[str, int]] = []
    start = 0
    current = [chain[0]]
    for index in range(1, len(chain)):
        same_group = int(chain[index].get("group") or 0) == int(chain[start].get("group") or 0)
        close = (
            _cosine(vecs[index - 1], vecs[index]) >= 0.75
            and _cosine(vecs[start], vecs[index]) >= 0.75
        )
        if same_group and close:
            current.append(chain[index])
            continue
        if len(current) > len(best):
            best = current
        start = index
        current = [chain[index]]
    if len(current) > len(best):
        best = current
    return best if len(best) >= MIN_CHAIN else []


def _type_vectors(predictor, path: Path, pieces: list[dict[str, int]]):
    if not pieces or getattr(predictor, "type_model", None) is None:
        return None
    embed = getattr(predictor, "_tsum_embeddings", None)
    if embed is None:
        return None
    from PIL import Image

    with Image.open(path) as board:
        return embed(board.convert("RGB"), pieces)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _draw_plan(
    image: QImage,
    pieces: list[dict[str, int]],
    chain: list[dict[str, int]],
    game: dict[str, int] | None,
) -> QImage:
    if image.isNull():
        return image
    left = top = 0
    board = image
    if game is not None:
        left = max(0, int(game["x"]))
        top = max(0, int(game["y"]))
        width = max(1, int(game["w"]))
        height = max(1, int(game["h"]))
        cropped = image.copy(QRect(left, top, min(width, image.width() - left), min(height, image.height() - top)))
        if not cropped.isNull():
            board = cropped
    painted = board.copy()
    painter = QPainter(painted)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    chain_ids = {id(piece) for piece in chain}
    for piece in pieces:
        x = int(piece["x"]) - left
        y = int(piece["y"]) - top
        radius = max(6, int(piece.get("r") or 12))
        if id(piece) in chain_ids:
            continue
        if str(piece.get("kind") or "") == "bomb":
            painter.setPen(QPen(QColor("#FF5C5C"), 2))
        else:
            painter.setPen(QPen(QColor("#FFE066"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(x, y), radius, radius)
    points = [(int(piece["x"]) - left, int(piece["y"]) - top, max(8, int(piece.get("r") or 16))) for piece in chain]
    if len(points) >= 2:
        painter.setPen(QPen(QColor("#7CFF7C"), max(4, points[0][2] // 3)))
        for (x0, y0, _r0), (x1, y1, _r1) in zip(points, points[1:]):
            painter.drawLine(x0, y0, x1, y1)
    font = QFont()
    font.setBold(True)
    painter.setFont(font)
    for index, (x, y, radius) in enumerate(points, start=1):
        painter.setPen(QPen(QColor("#1A1A1A"), 2))
        painter.setBrush(QColor("#7CFF7C"))
        painter.drawEllipse(QPoint(x, y), radius, radius)
        painter.setPen(QColor("#1A1A1A"))
        painter.drawText(QRect(x - radius, y - radius, radius * 2, radius * 2), Qt.AlignmentFlag.AlignCenter, str(index))
    painter.end()
    return painted


def _chain_key(chain: list[dict[str, int]]) -> frozenset[tuple[int, int]]:
    return frozenset(_chain_cells(chain))


def _chain_cells(chain: list[dict[str, int]]) -> set[tuple[int, int]]:
    return {(int(piece["x"]) // 24, int(piece["y"]) // 24) for piece in chain}


def _chain_too_similar(
    chain: list[dict[str, int]],
    used_keys: list[frozenset[tuple[int, int]]],
) -> bool:
    key = _chain_key(chain)
    for old in used_keys:
        overlap = len(key & old)
        if overlap >= max(1, min(len(key), len(old)) * 0.5):
            return True
        if key <= old or old <= key:
            return True
    return False

