from __future__ import annotations

import colorsys
import json
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

from PySide6.QtCore import QPoint, QRect, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from app.bluestacks import capture_play_frame, capture_screen_path, reset_swipe_mouse, swipe_path, tap
from app.intro import (
    Stopped,
    _check_stop,
    _continue_button,
    _match_start_button,
    _play_button,
    _slow_tap,
)
from app.play_style import add_unlike, load_unlike, record_pick, unlike_hit
from app.trainer_bridge import TRAINER_ROOT, load_play_tools, save_erase_lesson, save_play_board

MIN_CHAIN = 3
BOARD_TSUMS = 8
SETTLE_WAIT = 2.0
TIMEUP_SCORE = 0.18
COIN_SCENE_SCORE = 0.18
COIN_SCENE_WAIT = 20.0
COIN_GOAL_4 = 500
COIN_GOAL_5 = 120

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
        save_boards: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._stop = stop
        self._start_match = start_match
        self._kind_count = kind_count
        self._save_boards = save_boards

    def run(self) -> None:
        try:
            run_play(
                self.status.emit,
                self._stop,
                start_match=self._start_match,
                preview=self.preview.emit,
                kind_count=self._kind_count,
                save_boards=self._save_boards,
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
    save_boards: Callable[[], bool] | None = None,
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
    if getattr(predictor, "coin_scene_model", None) is None:
        raise RuntimeError("coin 画面のモデルがありません。")
    if getattr(predictor, "coin_reader", None) is None:
        raise RuntimeError("コインの読み取りがありません。")

    say("プレイを開始します")
    reset_swipe_mouse()
    unlike = load_unlike()
    pending_chain: list[dict[str, int]] | None = None
    pending_spots: list[tuple[int, int, int, tuple[float, float, float] | None]] | None = None
    pending_image: QImage | None = None
    pending_pieces: list[dict[str, int]] | None = None
    pending_game: dict[str, int] | None = None
    pending_options: list[int] = []
    pending_n = 0
    pending_at = 0.0
    settle_key: tuple[tuple[int, int], ...] | None = None
    skip_chains: set[tuple[tuple[int, int], ...]] = set()
    saved_boards: set[tuple[tuple[int, int], ...]] = set()
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
            image = capture_play_frame()
            rgb = _qimage_rgb(image)
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.25, stop)
            continue
        if rgb is None or image.isNull():
            say("画面を待っています")
            _sleep_stop(0.25, stop)
            continue
        boxes = predictor.predict_all(Path("."), rgb=rgb)
        if boxes.get("game"):
            game = boxes["game"]
        timeup = _timeup_score(predictor, rgb)
        if timeup >= TIMEUP_SCORE:
            say(f"TIME UP {timeup:.0%}")
            _read_coin_scene_goal(predictor, kinds, say, stop)
            return
        _check_stop(stop)
        if not kinds_locked:
            used = _five_to_four_used_pil(rgb)
            if used is not None:
                kinds = 4 if used else 5
                kinds_locked = True
                say(f"5＞4 {'使用' if used else '未使用'} / 種類 {kinds}")
        pieces = predictor.predict_pieces(Path("."), game, kinds=kinds, rgb=rgb)
        tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        if len(tsums) < BOARD_TSUMS and not saw_board:
            pieces = predictor.predict_pieces(Path("."), None, kinds=kinds, rgb=rgb)
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
        if pending_spots is not None and pending_chain is not None:
            erased = pending_n > 0 and len(tsums) <= pending_n - MIN_CHAIN
            waited = time.time() - pending_at
            if not erased and waited < SETTLE_WAIT:
                say("消えるのを待っています")
                continue
            if not erased:
                say("消えていない")
                record_pick(pending_options, len(pending_chain), False)
                skip_chains.add(_chain_key(pending_chain))
                pair = _unlike_from_chain(pending_chain)
                if pair is not None and add_unlike(unlike, pair[0], pair[1]):
                    say("別種類として覚えます")
            else:
                key = _board_key(tsums)
                if waited < SETTLE_WAIT and (settle_key is None or key != settle_key):
                    settle_key = key
                    say("落ちるのを待っています")
                    continue
                record_pick(pending_options, len(pending_chain), True)
                skip_chains.clear()
            pending_chain = None
            pending_spots = None
            pending_image = None
            pending_pieces = None
            pending_game = None
            pending_options = []
            pending_n = 0
            pending_at = 0.0
            settle_key = None
        _attach_type_vecs(predictor, rgb, pieces)
        if save_boards is not None and save_boards() and saw_board:
            board = _board_key(tsums)
            if board not in saved_boards:
                saved_boards.add(board)
                try:
                    if save_play_board(predictor, image, game):
                        say("消す前の盤面を取り込みました")
                except Exception:
                    say("盤面を取り込めませんでした")
        say(_group_counts_line(tsums))
        chain, option_lens = _pick_chain(
            predictor, rgb, pieces, candidates, unlike, skip_chains, say
        )
        if chain:
            if not _swipe_chain(chain, pieces, image, game, len(tsums), say, stop, preview):
                _sleep_stop(0.08, stop)
                continue
            pending_chain = chain
            pending_spots = _chain_spots(rgb, chain)
            pending_image = image
            pending_pieces = pieces
            pending_game = game
            pending_options = option_lens
            pending_n = len(tsums)
            pending_at = time.time()
            settle_key = None
            continue
        if preview is not None:
            preview(_draw_plan(image, pieces, [], game))
        if saw_board and _tap_biggest_bomb(pieces, say, stop):
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


def _chain_spots(rgb, chain: list[dict[str, int]]) -> list[tuple[int, int, int, tuple[float, float, float] | None]]:
    spots: list[tuple[int, int, int, tuple[float, float, float] | None]] = []
    for piece in chain:
        x, y = int(piece["x"]), int(piece["y"])
        radius = max(6, int(piece.get("r") or 12))
        spots.append((x, y, radius, _spot_mean(rgb, x, y, radius)))
    return spots


def _spots_lingered(
    after,
    spots: list[tuple[int, int, int, tuple[float, float, float] | None]],
) -> bool:
    hits = 0
    for x, y, radius, old in spots:
        if old is None:
            continue
        new = _spot_mean(after, x, y, radius)
        if new is None:
            continue
        dist = sum((a - b) ** 2 for a, b in zip(old, new)) ** 0.5
        if dist < 36:
            hits += 1
    return hits >= MIN_CHAIN


def _spot_mean(image, x: int, y: int, radius: int) -> tuple[float, float, float] | None:
    span = max(4, radius // 2)
    box = (x - span, y - span, x + span + 1, y + span + 1)
    crop = image.crop(box)
    pixels = list(crop.getdata())
    if not pixels:
        return None
    count = len(pixels)
    return (
        sum(pixel[0] for pixel in pixels) / count,
        sum(pixel[1] for pixel in pixels) / count,
        sum(pixel[2] for pixel in pixels) / count,
    )


def _unlike_from_chain(
    chain: list[dict[str, int]],
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    vecs = [piece.get("_vec") for piece in chain]
    if any(vec is None for vec in vecs) or len(chain) < 2:
        return None
    cut = _weakest_cut(chain)
    left_v, right_v = vecs[cut - 1], vecs[cut]
    if left_v is None or right_v is None:
        return None
    left = [vecs[index] for index in range(cut)]
    right = [vecs[index] for index in range(cut, len(vecs))]
    if not left or not right:
        return None
    return (_mean_vec(left), _mean_vec(right))


def _weakest_cut(chain: list[dict[str, int]]) -> int:
    vecs = [piece.get("_vec") for piece in chain]
    cut = 1
    worst = 2.0
    for index in range(1, len(chain)):
        left, right = vecs[index - 1], vecs[index]
        if left is None or right is None:
            continue
        sim = _cosine(left, right)
        if sim < worst:
            worst = sim
            cut = index
    return cut


def _mean_vec(vecs: list[tuple[float, ...]]) -> tuple[float, ...]:
    dim = len(vecs[0])
    count = len(vecs)
    return tuple(sum(vec[index] for vec in vecs) / count for index in range(dim))


def _remember_mixed(predictor, image: QImage, game, pieces, chain) -> None:
    from tempfile import gettempdir

    path = Path(gettempdir()) / "tsum_autoplay_mixed.png"
    if not image.save(str(path), "PNG"):
        return
    cut = _weakest_cut(chain)
    chain_ids = {id(piece) for piece in chain}
    labeled: list[dict[str, int]] = []
    for piece in pieces:
        item = {
            key: value
            for key, value in piece.items()
            if key in {"x", "y", "r", "kind", "group"}
        }
        if id(piece) in chain_ids:
            index = next(i for i, member in enumerate(chain) if id(member) == id(piece))
            item["group"] = 1 if index < cut else 2
        labeled.append(item)
    try:
        save_erase_lesson(predictor, path, game, labeled)
    except Exception:
        return


def _tap_biggest_bomb(pieces: list[dict[str, int]], say: StatusFn, stop: Event | None) -> bool:
    bombs = [piece for piece in pieces if str(piece.get("kind") or "") == "bomb"]
    if not bombs:
        return False
    bomb = max(bombs, key=lambda piece: int(piece.get("r") or 0))
    say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
    tap(int(bomb["x"]), int(bomb["y"]))
    _sleep_stop(0.18, stop)
    return True


def _remaining_after_erase(
    pieces: list[dict[str, int]],
    chain: list[dict[str, int]],
) -> list[dict[str, int]]:
    gone = {id(piece) for piece in chain}
    leftover = [dict(piece) for piece in pieces if id(piece) not in gone]
    _drop_down(leftover, pieces)
    return leftover


def _drop_down(remaining: list[dict[str, int]], before: list[dict[str, int]]) -> None:
    origins = [
        piece
        for piece in before
        if str(piece.get("kind") or "") in {"tsum", "bomb"}
    ]
    movers = [
        piece
        for piece in remaining
        if str(piece.get("kind") or "") in {"tsum", "bomb"}
    ]
    tsums = [piece for piece in origins if str(piece.get("kind") or "") == "tsum"]
    spacing = _median_spacing(tsums or origins)
    if spacing <= 0 or not movers or not origins:
        return
    col_w = spacing * 0.5
    centers: list[float] = []
    orig_cols: list[list[dict[str, int]]] = []
    for piece in origins:
        x = float(piece["x"])
        best_i = None
        best_d = col_w
        for index, cx in enumerate(centers):
            dist = abs(x - cx)
            if dist < best_d:
                best_d = dist
                best_i = index
        if best_i is None:
            centers.append(x)
            orig_cols.append([piece])
            continue
        orig_cols[best_i].append(piece)
        count = len(orig_cols[best_i])
        centers[best_i] += (x - centers[best_i]) / count
    rest_cols: list[list[dict[str, int]]] = [[] for _ in centers]
    for piece in movers:
        x = float(piece["x"])
        best_i = min(range(len(centers)), key=lambda index: abs(x - centers[index]))
        rest_cols[best_i].append(piece)
    for orig, kept in zip(orig_cols, rest_cols):
        if not kept:
            continue
        ys = sorted(int(piece["y"]) for piece in orig)
        bottom = ys[-1]
        gaps = [ys[index + 1] - ys[index] for index in range(len(ys) - 1) if ys[index + 1] > ys[index]]
        step = gaps[len(gaps) // 2] if gaps else int(round(spacing))
        if step < 1:
            step = max(1, int(round(spacing)))
        kept.sort(key=lambda piece: int(piece["y"]))
        for index, piece in enumerate(reversed(kept)):
            piece["y"] = int(round(bottom - index * step))


def _median_spacing(tsums: list[dict[str, int]]) -> float:
    if len(tsums) < 2:
        return 0.0
    nearest: list[float] = []
    for index, left in enumerate(tsums):
        ax, ay = int(left["x"]), int(left["y"])
        best = 1e18
        for other, right in enumerate(tsums):
            if other == index:
                continue
            dx = ax - int(right["x"])
            dy = ay - int(right["y"])
            dist = dx * dx + dy * dy
            if dist < best:
                best = dist
        if best < 1e18:
            nearest.append(best ** 0.5)
    if not nearest:
        return 0.0
    nearest.sort()
    return nearest[len(nearest) // 2]


def _qimage_rgb(image: QImage):
    from PIL import Image as PILImage

    if image.isNull():
        return None
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width = converted.width()
    height = converted.height()
    stride = converted.bytesPerLine()
    ptr = converted.constBits()
    size = converted.sizeInBytes()
    try:
        buf = bytes(ptr[:size])
    except Exception:
        buf = memoryview(ptr)[:size].tobytes()
    if stride == width * 3:
        return PILImage.frombytes("RGB", (width, height), buf)
    rows = [buf[row * stride : row * stride + width * 3] for row in range(height)]
    return PILImage.frombytes("RGB", (width, height), b"".join(rows))


def _timeup_score(predictor, rgb) -> float:
    model = getattr(predictor, "scene_model", None)
    transform = getattr(predictor, "_scene_transform", None)
    if model is None or transform is None:
        return 0.0
    import torch

    view = _portrait_frame(rgb)
    tensor = transform(view).unsqueeze(0).to(predictor.device)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    classes = getattr(predictor, "scene_classes", None) or ("other", "go", "timeup")
    if "timeup" in classes:
        return float(probs[classes.index("timeup")].item())
    if probs.numel() < 3:
        return 0.0
    return float(probs[2].item())


def _coin_scene_best(predictor, rgb) -> tuple[str, float]:
    model = getattr(predictor, "coin_scene_model", None)
    transform = getattr(predictor, "_scene_transform", None)
    classes = getattr(predictor, "coin_scene_classes", None) or ()
    if model is None or transform is None or rgb is None or not classes:
        return "", 0.0
    import torch

    view = _portrait_frame(rgb)
    tensor = transform(view).unsqueeze(0).to(predictor.device)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    scores: dict[str, float] = {}
    for index, key in enumerate(classes):
        if index >= int(probs.numel()):
            break
        scores[str(key)] = float(probs[index].item())
    if not scores:
        return "", 0.0
    name = max(scores, key=scores.get)
    return name, scores[name]


def _coin_goal(kinds: int) -> int:
    return COIN_GOAL_4 if kinds <= 4 else COIN_GOAL_5


def _say_coin_goal(coins: int, kinds: int, say: StatusFn) -> None:
    goal = _coin_goal(kinds)
    if coins <= 0:
        say(f"目標 {goal}枚（コインは読めませんでした）")
        return
    mark = "達成" if coins >= goal else "未達"
    say(f"コイン {coins}枚 / 目標 {goal}枚 {mark}")


def _parse_coin_text(text: str) -> int | None:
    digits = "".join(char for char in str(text) if char.isdigit())
    if not digits:
        return None
    value = int(digits)
    if value <= 0:
        return None
    if len(digits) >= 3 and len(set(digits)) == 1:
        return None
    return value


def _read_coin(predictor) -> int | None:
    reader = getattr(predictor, "coin_reader", None)
    if reader is None:
        return None
    import tempfile

    from PIL import Image as PILImage

    temp = None
    try:
        path = capture_screen_path()
        with PILImage.open(path) as opened:
            view = _portrait_frame(opened.convert("RGB"))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp = Path(handle.name)
        view.save(temp, format="PNG")
        boxes = reader.candidate_boxes_for_path(temp, "coin")
        hud = reader._hud

        def predict(crop, key: str = "coin") -> str:
            raw = reader._predict_digits(crop, key)
            if _parse_coin_text(raw) is None:
                return ""
            return raw

        for box in boxes:
            _crop, number = hud.read_coin_number(temp, box, predict_fn=predict)
            value = _parse_coin_text(number)
            if value is not None:
                return value
    except Exception:
        return None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return None


def _read_coin_scene_goal(predictor, kinds: int, say: StatusFn, stop: Event | None) -> None:
    if getattr(predictor, "coin_scene_model", None) is None:
        say("coin 画面のモデルがありません")
        _say_coin_goal(0, kinds, say)
        return
    if getattr(predictor, "coin_reader", None) is None:
        say("coin の読み取りがありません")
        _say_coin_goal(0, kinds, say)
        return
    say("coin 画面を待っています")
    started = time.time()
    deadline = started + COIN_SCENE_WAIT
    last = 0
    hits = 0
    tapped = False
    saw_coin = False
    coin_at = 0.0
    while time.time() < deadline:
        _check_stop(stop)
        try:
            image = capture_play_frame()
            rgb = _qimage_rgb(image)
        except Exception:
            _sleep_stop(0.3, stop)
            continue
        if rgb is None or image.isNull():
            _sleep_stop(0.3, stop)
            continue
        name, score = _coin_scene_best(predictor, rgb)
        if name == "coin" and score >= COIN_SCENE_SCORE:
            if not saw_coin:
                say(f"coin 画面 {score:.0%}")
                saw_coin = True
                coin_at = time.time()
            if time.time() - coin_at < 1.2:
                _sleep_stop(0.3, stop)
                continue
            coins = _read_coin(predictor)
            if coins is not None:
                if coins == last:
                    hits += 1
                else:
                    last = coins
                    hits = 1
                if hits >= 3:
                    break
        elif (
            name == "timeup"
            and not tapped
            and not saw_coin
            and time.time() - started >= 1.5
        ):
            _slow_tap(image.width() // 2, image.height() // 2)
            tapped = True
        _sleep_stop(0.3, stop)
    _say_coin_goal(last, kinds, say)


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


def _group_counts_line(tsums: list[dict[str, int]]) -> str:
    counts: dict[int, int] = {}
    for piece in tsums:
        group = int(piece.get("group") or 0)
        if group <= 0:
            continue
        counts[group] = counts.get(group, 0) + 1
    if not counts:
        return "この盤面の種類は分かっていません"
    sizes = [counts[group] for group in sorted(counts)]
    kinds = len(sizes)
    bodies = "、".join(f"{n}体" for n in sizes)
    return f"この盤面は{kinds}種類に分けた（多い順 {bodies}）"


def _pick_chain(
    predictor,
    rgb,
    pieces: list[dict[str, int]],
    candidates,
    unlike,
    skip_chains: set[tuple[tuple[int, int], ...]],
    say: StatusFn,
) -> tuple[list[dict[str, int]], list[int]]:
    found = [chain for chain in candidates(pieces, 8) if len(chain) >= MIN_CHAIN]
    found = [chain for chain in found if _chain_key(chain) not in skip_chains]
    if not found:
        return [], []
    say("候補 " + " / ".join(str(len(chain)) for chain in found))
    options = [len(item) for item in found]
    return max(
        found,
        key=lambda item: (
            len(item),
            _leftover_len(pieces, item, candidates),
            0 if _chain_has_unlike(item, unlike) else 1,
        ),
    ), options


def _chain_key(chain: list[dict[str, int]]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted((int(piece["x"]) // 8, int(piece["y"]) // 8) for piece in chain))


def _chain_has_unlike(chain: list[dict[str, int]], unlike) -> bool:
    if not unlike:
        return False
    for index in range(1, len(chain)):
        if unlike_hit(chain[index - 1].get("_vec"), chain[index].get("_vec"), unlike):
            return True
    return False


def _leftover_len(
    pieces: list[dict[str, int]],
    chain: list[dict[str, int]],
    candidates,
) -> int:
    leftover = _remaining_after_erase(pieces, chain)
    found = [item for item in candidates(leftover, 1) if len(item) >= MIN_CHAIN]
    return max((len(item) for item in found), default=0)


def _board_key(tsums: list[dict[str, int]]) -> tuple[tuple[int, int], ...]:
    return tuple(
        sorted((int(piece["x"]) // 12, int(piece["y"]) // 12) for piece in tsums)
    )


def _attach_type_vecs(
    predictor,
    rgb,
    pieces: list[dict[str, int]],
) -> None:
    tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
    if not tsums:
        return
    vecs = _type_vectors(predictor, rgb, tsums)
    if vecs is None:
        return
    for piece, vec in zip(tsums, vecs):
        piece["_vec"] = vec


def _type_vectors(predictor, rgb, pieces: list[dict[str, int]]):
    if not pieces or getattr(predictor, "type_model", None) is None:
        return None
    embed = getattr(predictor, "_tsum_embeddings", None)
    if embed is None or rgb is None:
        return None
    return embed(rgb, pieces)


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
        if key == old or key <= old:
            return True
    return False

