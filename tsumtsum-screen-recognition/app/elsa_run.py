from __future__ import annotations

import math

from app.regions import is_tsum_kind


def elsa_three_chains(pieces: list[dict], game: dict | None = None) -> list[dict]:
    tsums = [
        piece
        for piece in pieces
        if is_tsum_kind(str(piece.get("kind") or "")) and int(piece.get("group") or 0) > 0
    ]
    if len(tsums) < 3:
        return []
    candidates = _straight_threes(tsums, _game_rect(game, tsums), _board_spacing(tsums))
    if not candidates:
        return []
    return _emit(_from_edge(candidates), tsums)


def elsa_freeze_most(
    pieces: list[dict],
    game: dict | None = None,
    locked: list[dict] | None = None,
) -> list[dict]:
    tsums = [
        piece
        for piece in pieces
        if is_tsum_kind(str(piece.get("kind") or "")) and int(piece.get("group") or 0) > 0
    ]
    if len(tsums) < 3:
        return []
    candidates = _straight_threes(
        tsums,
        _game_rect(game, tsums),
        _board_spacing(tsums),
        _locked_indexes(tsums, locked or []),
    )
    if not candidates:
        return []
    return _emit(_clear_from_edge(candidates), tsums)


def _emit(chains: list[dict], tsums: list[dict]) -> list[dict]:
    out: list[dict] = []
    for number, item in enumerate(chains, start=1):
        blocked = int(item["blocked"])
        out.append(
            {
                "x1": item["x1"],
                "y1": item["y1"],
                "x2": item["x2"],
                "y2": item["y2"],
                "group": item["group"],
                "n": number,
                "trace": [tsums[index] for index in item["trace"]],
                "ice": [tsums[index] for index in range(len(tsums)) if blocked & (1 << index)],
            }
        )
    return out


def _most_ice(candidates: list[dict]) -> list[dict]:
    count = len(candidates)
    if count > 16:
        frozen = 0
        taken = 0
        picked: list[dict] = []
        order = sorted(range(count), key=lambda index: -int(candidates[index]["blocked"]).bit_count())
        for index in order:
            item = candidates[index]
            if _blocked(item, frozen, taken):
                continue
            picked.append(item)
            frozen |= int(item["blocked"])
            taken |= int(item["members"])
        return picked
    blocked = [int(item["blocked"]) for item in candidates]
    members = [int(item["members"]) for item in candidates]
    best_score = -1
    best_mask = 0
    for mask in range(1 << count):
        frozen = 0
        taken = 0
        score = 0
        ok = True
        for index in range(count):
            if mask & (1 << index) == 0:
                continue
            if members[index] & frozen or blocked[index] & taken:
                ok = False
                break
            score += (blocked[index] & ~frozen).bit_count()
            frozen |= blocked[index]
            taken |= members[index]
        if ok and score > best_score:
            best_score = score
            best_mask = mask
    return [candidates[index] for index in range(count) if best_mask & (1 << index)]


def _board_spacing(tsums: list[dict]) -> float:
    nearest: list[float] = []
    for index, piece in enumerate(tsums):
        best = None
        for other in range(len(tsums)):
            if other == index:
                continue
            dist = _dist(piece, tsums[other])
            if best is None or dist < best:
                best = dist
        if best is not None and best > 0:
            nearest.append(best)
    nearest.sort()
    return nearest[len(nearest) // 2] if nearest else 80.0


def _game_rect(game: dict | None, tsums: list[dict]) -> tuple[float, float, float, float]:
    if game and int(game.get("w") or 0) > 0 and int(game.get("h") or 0) > 0:
        left = float(game["x"])
        top = float(game["y"])
        return left, top, left + float(game["w"]), top + float(game["h"])
    xs = [float(piece["x"]) for piece in tsums]
    ys = [float(piece["y"]) for piece in tsums]
    pad = max(float(piece.get("r") or 12) for piece in tsums)
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def _locked_indexes(tsums: list[dict], locked: list[dict]) -> set[int]:
    found: set[int] = set()
    for index, piece in enumerate(tsums):
        radius = float(piece.get("r") or 0)
        if radius <= 0:
            continue
        x = float(piece["x"])
        y = float(piece["y"])
        limit = radius * radius
        for old in locked:
            dx = x - float(old["x"])
            dy = y - float(old["y"])
            if dx * dx + dy * dy <= limit:
                found.add(index)
                break
    return found


def _straight_threes(
    tsums: list[dict],
    rect: tuple[float, float, float, float],
    spacing: float,
    skip: set[int] | None = None,
) -> list[dict]:
    line_limit = max(spacing * 0.80, 12.0)
    bend_limit = max(spacing * 0.91, 12.0)
    reach = spacing * 1.65
    long_step = spacing * 1.60
    groups: dict[int, list[int]] = {}
    for index, piece in enumerate(tsums):
        group = int(piece.get("group") or 0)
        groups.setdefault(group, []).append(index)
    locked = skip or set()
    found: list[dict] = []
    seen: set[frozenset[int]] = set()
    for group, indexes in groups.items():
        indexes = [index for index in indexes if index not in locked]
        if len(indexes) < 3:
            continue
        for left in range(len(indexes)):
            for right in range(left + 1, len(indexes)):
                start = indexes[left]
                end = indexes[right]
                if _dist(tsums[start], tsums[end]) > reach * 2:
                    continue
                middles = [
                    index
                    for index in indexes
                    if index != start
                    and index != end
                    and _between(tsums[index], tsums[start], tsums[end], bend_limit)
                ]
                if len(middles) != 1:
                    continue
                middle = middles[0]
                if not _clear_step(tsums, start, middle, end, reach, line_limit, long_step):
                    continue
                if not _clear_step(tsums, middle, end, start, reach, line_limit, long_step):
                    continue
                if _other_on_segment(tsums, start, end, middle, group, line_limit):
                    continue
                triple = frozenset((start, middle, end))
                if triple in seen:
                    continue
                seen.add(triple)
                members = 0
                for index in triple:
                    members |= 1 << index
                if members.bit_count() < 3:
                    continue
                extended = _extend_to_rect(
                    float(tsums[start]["x"]),
                    float(tsums[start]["y"]),
                    float(tsums[end]["x"]),
                    float(tsums[end]["y"]),
                    rect,
                )
                if extended is None:
                    continue
                x1, y1, x2, y2 = extended
                frozen = members
                for index, piece in enumerate(tsums):
                    if members & (1 << index):
                        continue
                    radius = float(piece.get("r") or 0)
                    if radius <= 0:
                        continue
                    if _line_distance(piece, x1, y1, x2, y2) <= radius * 0.85:
                        frozen |= 1 << index
                xs = [float(tsums[index]["x"]) for index in triple]
                ys = [float(tsums[index]["y"]) for index in triple]
                sides = (
                    min(x - rect[0] for x in xs),
                    min(rect[2] - x for x in xs),
                    min(y - rect[1] for y in ys),
                    min(rect[3] - y for y in ys),
                )
                found.append(
                    {
                        "x1": int(round(x1)),
                        "y1": int(round(y1)),
                        "x2": int(round(x2)),
                        "y2": int(round(y2)),
                        "group": group,
                        "members": members,
                        "trace": (start, middle, end),
                        "blocked": frozen,
                        "edge": min(sides),
                        "sides": sides,
                    }
                )
    return found


def _angle_diff(left: float, right: float) -> float:
    diff = abs(left - right) % 180.0
    return min(diff, 180.0 - diff)


def _line_angle(item: dict) -> float:
    return math.degrees(math.atan2(item["y2"] - item["y1"], item["x2"] - item["x1"])) % 180.0


def _axis(angle: float) -> float:
    if _angle_diff(angle, 90.0) <= _angle_diff(angle, 0.0):
        return 90.0
    return 0.0


def _blocked(item: dict, frozen: int, taken: int) -> bool:
    return bool(item["members"] & frozen or item["blocked"] & taken)


def _straightness(item: dict) -> float:
    angle = _line_angle(item)
    return min(_angle_diff(angle, 0.0), _angle_diff(angle, 90.0))


def _from_edge(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    nearest = min(range(len(candidates)), key=lambda index: (candidates[index]["edge"], index))
    start = candidates[nearest]
    side = min(range(4), key=lambda index: (start["sides"][index], index))
    axis = _axis(_line_angle(start))
    order = sorted(
        (index for index in range(len(candidates)) if index != nearest),
        key=lambda index: (candidates[index]["sides"][side], index),
    )
    picked = [start]
    frozen = int(start["blocked"])
    taken = int(start["members"])
    for position, index in enumerate(order):
        item = candidates[index]
        if _blocked(item, frozen, taken):
            continue
        off = _angle_diff(_line_angle(item), axis)
        trial_frozen = frozen | int(item["blocked"])
        trial_taken = taken | int(item["members"])
        blocks_straighter = False
        for later_index in order[position + 1 :]:
            later = candidates[later_index]
            if _blocked(later, frozen, taken):
                continue
            if _angle_diff(_line_angle(later), axis) >= off:
                continue
            if _blocked(later, trial_frozen, trial_taken):
                blocks_straighter = True
                break
        if blocks_straighter:
            continue
        picked.append(item)
        frozen = trial_frozen
        taken = trial_taken
    return picked


def _clear_from_edge(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    order = sorted(
        range(len(candidates)),
        key=lambda index: (
            candidates[index]["edge"],
            _straightness(candidates[index]),
            index,
        ),
    )
    picked: list[dict] = []
    frozen = 0
    taken = 0
    for position, index in enumerate(order):
        item = candidates[index]
        if _blocked(item, frozen, taken):
            continue
        off = _straightness(item)
        trial_frozen = frozen | int(item["blocked"])
        trial_taken = taken | int(item["members"])
        blocks_straighter = False
        for later_index in order[position + 1 :]:
            later = candidates[later_index]
            if _blocked(later, frozen, taken):
                continue
            if _straightness(later) >= off:
                continue
            if _blocked(later, trial_frozen, trial_taken):
                blocks_straighter = True
                break
        if blocks_straighter:
            continue
        picked.append(item)
        frozen = trial_frozen
        taken = trial_taken
    return picked


def _extend_to_rect(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return None
    scale = max(rect[2] - rect[0], rect[3] - rect[1], length) * 4
    ux = dx / length
    uy = dy / length
    return _clip_segment(
        x1 - ux * scale,
        y1 - uy * scale,
        x1 + ux * scale,
        y1 + uy * scale,
        rect,
    )


def _clip_segment(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    left, top, right, bottom = rect
    dx = x2 - x1
    dy = y2 - y1
    params = ((-dx, x1 - left), (dx, right - x1), (-dy, y1 - top), (dy, bottom - y1))
    enter = -math.inf
    leave = math.inf
    for direction, distance in params:
        if abs(direction) < 1e-9:
            if distance < 0:
                return None
            continue
        hit = distance / direction
        if direction < 0:
            enter = max(enter, hit)
        else:
            leave = min(leave, hit)
    if enter > leave:
        return None
    return (x1 + enter * dx, y1 + enter * dy, x1 + leave * dx, y1 + leave * dy)


def _other_on_segment(
    tsums: list[dict],
    start: int,
    end: int,
    middle: int,
    group: int,
    limit: float,
) -> bool:
    mid_dist, _ = _segment_hit(tsums[middle], tsums[start], tsums[end])
    radius = float(tsums[middle].get("r") or 0)
    straight = radius > 0 and mid_dist <= radius * 0.5
    for index, piece in enumerate(tsums):
        if index in (start, end, middle):
            continue
        if int(piece.get("group") or 0) == group:
            continue
        dist, tee = _segment_hit(piece, tsums[start], tsums[end])
        if not (0.0 < tee < 1.0):
            continue
        other_radius = float(piece.get("r") or 0)
        if other_radius > 0 and dist <= other_radius * 0.5:
            return True
        if straight:
            continue
        if dist <= limit and mid_dist < dist:
            return True
    return False


def _line_distance(piece: dict, x1: float, y1: float, x2: float, y2: float) -> float:
    px, py = float(piece["x"]), float(piece["y"])
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return 0.0
    return abs(dx * (y1 - py) - (x1 - px) * dy) / length


def _clear_step(
    tsums: list[dict],
    start: int,
    end: int,
    skip: int,
    reach: float,
    limit: float,
    long_step: float,
) -> bool:
    step = _dist(tsums[start], tsums[end])
    if step > reach:
        return False
    ax, ay = float(tsums[start]["x"]), float(tsums[start]["y"])
    bx, by = float(tsums[end]["x"]), float(tsums[end]["y"])
    group = int(tsums[start].get("group") or 0)
    positive = False
    negative = False
    for index, piece in enumerate(tsums):
        if index in (start, end, skip):
            continue
        dist, tee = _segment_hit(piece, tsums[start], tsums[end])
        if not (0.25 < tee < 0.75 and dist <= limit):
            continue
        if int(piece.get("group") or 0) == group:
            return False
        cross = (bx - ax) * (float(piece["y"]) - ay) - (by - ay) * (float(piece["x"]) - ax)
        if cross > 0:
            positive = True
        elif cross < 0:
            negative = True
        if positive and negative:
            return False
    if step > long_step and (positive or negative):
        return False
    return True


def _between(piece: dict, start: dict, end: dict, limit: float) -> bool:
    dist, tee = _segment_hit(piece, start, end)
    return 0.15 < tee < 0.85 and dist <= limit


def _segment_hit(piece: dict, start: dict, end: dict) -> tuple[float, float]:
    px, py = float(piece["x"]), float(piece["y"])
    ax, ay = float(start["x"]), float(start["y"])
    bx, by = float(end["x"]), float(end["y"])
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length < 1e-6:
        return math.hypot(px - ax, py - ay), 0.0
    tee = ((px - ax) * dx + (py - ay) * dy) / length
    clamped = min(1.0, max(0.0, tee))
    qx = ax + clamped * dx
    qy = ay + clamped * dy
    return math.hypot(px - qx, py - qy), tee


def _dist(left: dict, right: dict) -> float:
    return math.hypot(float(left["x"]) - float(right["x"]), float(left["y"]) - float(right["y"]))
