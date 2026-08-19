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


def model_filename(key: str) -> str:
    return "game_region.pt" if key == "game" else f"{key}.pt"
