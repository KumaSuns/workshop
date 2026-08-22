from __future__ import annotations

REGION_SPECS: list[tuple[str, str, str]] = [
    ("game", "ゲーム範囲", "#5CFF9E"),
    ("score", "スコア", "#7EC8FF"),
    ("coin", "コイン", "#FFD166"),
    ("timer", "タイマー", "#FF8AD4"),
    ("skill", "スキルボタン", "#C084FC"),
    ("fan", "扇風機", "#80E0D0"),
    ("pause", "一時停止", "#FF9F7A"),
    ("fever", "フィーバーゲージ", "#F472B6"),
]

REGION_LABELS = {key: label for key, label, _color in REGION_SPECS}
REGION_COLORS = {key: color for key, _label, color in REGION_SPECS}
REGION_KEYS = [key for key, _label, _color in REGION_SPECS]

PIECE_SPECS: list[tuple[str, str, str]] = [
    ("tsum", "ツム", "#FFE066"),
    ("bomb", "ボム", "#FF5C5C"),
]
PIECE_LABELS = {key: label for key, label, _color in PIECE_SPECS}
PIECE_COLORS = {key: color for key, _label, color in PIECE_SPECS}
PIECE_KEYS = [key for key, _label, _color in PIECE_SPECS]
SCENE_SPECS: list[tuple[str, str, str]] = [
    ("go", "GO", "#7CFF7C"),
    ("timeup", "TIME UP", "#FF6B8A"),
]
SCENE_LABELS = {key: label for key, label, _color in SCENE_SPECS}
SCENE_COLORS = {key: color for key, _label, color in SCENE_SPECS}
SCENE_KEYS = [key for key, _label, _color in SCENE_SPECS]
PLACE_SPECS = REGION_SPECS + PIECE_SPECS
PLACE_LABELS = {**REGION_LABELS, **PIECE_LABELS, **SCENE_LABELS, "coin_digits": "コイン数値"}
PLACE_COLORS = {**REGION_COLORS, **PIECE_COLORS, **SCENE_COLORS}
COIN_DIGIT_KEY = "coin_digits"

TSUM_GROUP_COLORS = [
    "#FFE066",
    "#7EC8FF",
    "#FF8AD4",
    "#5CFF9E",
    "#FF9F43",
    "#C084FC",
    "#4ECDC4",
    "#FF6B6B",
    "#F472B6",
    "#80E0D0",
    "#A5B4FC",
    "#FFD166",
]


def tsum_group_color(group: int) -> str:
    index = max(1, min(12, int(group or 1))) - 1
    return TSUM_GROUP_COLORS[index]


def is_piece_key(key: str) -> bool:
    return key in PIECE_KEYS


def is_scene_key(key: str) -> bool:
    return key in SCENE_KEYS


def piece_radius_from_game(width: float, kind: str = "tsum") -> int:
    span = max(1.0, float(width))
    divisor = 12.0 if kind == "bomb" else 15.0
    return max(8, int(round(span / divisor)))


def model_filename(key: str) -> str:
    if key == "game":
        return "game_region.pt"
    if key == "pieces":
        return "pieces.pt"
    if key == "coin_digits":
        return "coin_digits.pt"
    if key == "scene":
        return "scene.pt"
    return f"{key}.pt"
