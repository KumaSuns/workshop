from __future__ import annotations

import math

from app.regions import is_tsum_kind

CANDIDATE_COUNT = 5
MIN_CHAIN = 3
TURN_DOT = -0.5


def _turn_ok(px: float, py: float, dx: float, dy: float) -> bool:
    denom = math.hypot(px, py) * math.hypot(dx, dy)
    if denom < 1e-9:
        return True
    return (px * dx + py * dy) / denom >= TURN_DOT


def max_tsum_chain(pieces: list[dict[str, int]]) -> int:
    candidates = tsum_chain_candidates(pieces)
    return len(candidates[0]) if candidates else 0


def longest_tsum_chain(pieces: list[dict[str, int]]) -> list[dict[str, int]]:
    candidates = tsum_chain_candidates(pieces)
    return candidates[0] if candidates else []


def tsum_chain_candidates(
    pieces: list[dict[str, int]],
    limit: int = CANDIDATE_COUNT,
) -> list[list[dict[str, int]]]:
    return _pick_diverse(_blob_paths(pieces), limit)


def tsum_chain_best_per_group(
    pieces: list[dict[str, int]],
    limit: int = 8,
) -> list[list[dict[str, int]]]:
    return _pick_diverse(_blob_paths(pieces), limit)


def _blob_paths(pieces: list[dict[str, int]]) -> list[list[dict[str, int]]]:
    tsums: list[dict[str, int]] = []
    for piece in pieces:
        if not is_tsum_kind(str(piece.get("kind") or "")):
            continue
        item = dict(piece)
        if str(item.get("kind") or "") == "big":
            item["big"] = 1
        tsums.append(item)
    if len(tsums) < MIN_CHAIN:
        return []
    spacing = _typical_spacing(tsums)
    bombs = [
        piece
        for piece in pieces
        if str(piece.get("kind") or "") == "bomb"
    ]
    phys = _physical_links(tsums, spacing, blockers=bombs)
    found = _paths_from_blobs(tsums, phys)
    longest = max((len(path) for path in found), default=0)
    biggest = 0
    counts: dict[int, int] = {}
    for piece in tsums:
        group = int(piece.get("group") or 1)
        counts[group] = counts.get(group, 0) + 1
        if counts[group] > biggest:
            biggest = counts[group]
    if not found or longest < biggest:
        phys = _physical_links(tsums, spacing, scale=1.12, blockers=bombs)
        extra = _paths_from_blobs(tsums, phys)
        if extra and (not found or max(len(path) for path in extra) > longest):
            found = extra
    found.sort(key=len, reverse=True)
    return found


def _paths_from_blobs(
    tsums: list[dict[str, int]],
    phys: list[list[int]],
) -> list[list[dict[str, int]]]:
    found: list[list[dict[str, int]]] = []
    seen: set[frozenset[int]] = set()
    for index in range(len(tsums)):
        blob = _type_blob(index, tsums, phys)
        if len(blob) < MIN_CHAIN:
            continue
        key = frozenset(blob)
        if key in seen:
            continue
        seen.add(key)
        local = _induced_links(phys, blob)
        xs = [int(tsums[i]["x"]) for i in blob]
        ys = [int(tsums[i]["y"]) for i in blob]
        orders = [
            order
            for order in _collect_paths(local, xs, ys)
            if len(order) >= MIN_CHAIN
        ]
        for order in orders:
            found.append([tsums[blob[item]] for item in order])
        covered = set(orders[0]) if orders else set()
        while True:
            rest = [item for item in range(len(blob)) if item not in covered]
            if len(rest) < MIN_CHAIN:
                break
            sub = _induced_sub(local, rest)
            rest_orders = [
                order
                for order in _collect_paths(
                    sub,
                    [xs[item] for item in rest],
                    [ys[item] for item in rest],
                )
                if len(order) >= MIN_CHAIN
            ]
            if not rest_orders:
                break
            for order in rest_orders:
                found.append([tsums[blob[rest[item]]] for item in order])
            covered.update(rest[item] for item in rest_orders[0])
    return found


def _induced_sub(links: list[list[int]], nodes: list[int]) -> list[list[int]]:
    index = {old: new for new, old in enumerate(nodes)}
    out: list[list[int]] = [[] for _ in nodes]
    for new, old in enumerate(nodes):
        for nxt in links[old]:
            mapped = index.get(nxt)
            if mapped is not None:
                out[new].append(mapped)
    return out


def _induced_links(phys: list[list[int]], blob: list[int]) -> list[list[int]]:
    index = {global_i: local for local, global_i in enumerate(blob)}
    links: list[list[int]] = [[] for _ in blob]
    for local, global_i in enumerate(blob):
        for nxt in phys[global_i]:
            if nxt in index:
                links[local].append(index[nxt])
    return links


def _physical_links(
    tsums: list[dict[str, int]],
    spacing: float,
    scale: float = 1.0,
    blockers: list[dict[str, int]] | None = None,
) -> list[list[int]]:
    count = len(tsums)
    radii = [max(4, int(piece.get("r") or 12)) for piece in tsums]
    typical_r = sorted(radii)[len(radii) // 2] if radii else 12
    reach = typical_r * 2.6 * scale
    close = typical_r * 2.4 * scale
    if 0 < spacing <= typical_r * 3.0:
        reach = max(reach, spacing * 1.32 * scale)
        close = max(close, spacing * 1.22 * scale)
    reach = min(reach, typical_r * 2.9 * scale)
    close = min(close, typical_r * 2.7 * scale)
    min_dist = typical_r * 0.4
    xs = [int(piece["x"]) for piece in tsums]
    ys = [int(piece["y"]) for piece in tsums]
    groups = [int(piece.get("group") or 1) for piece in tsums]
    bigs = [bool(int(piece.get("big") or 0)) for piece in tsums]
    gap = spacing if spacing > 0 else typical_r * 2.0
    extra_x = [int(piece["x"]) for piece in (blockers or [])]
    extra_y = [int(piece["y"]) for piece in (blockers or [])]
    links: list[list[int]] = [[] for _ in range(count)]

    def add(left: int, right: int) -> None:
        if _segment_blocked(xs, ys, left, right, gap, extra_x, extra_y):
            return
        if right not in links[left]:
            links[left].append(right)
        if left not in links[right]:
            links[right].append(left)

    for index in range(count):
        bins: list[tuple[float, int] | None] = [None] * 6
        ax, ay = xs[index], ys[index]
        group = groups[index]
        for other in range(count):
            if other == index or groups[other] != group:
                continue
            dx = xs[other] - ax
            dy = ys[other] - ay
            dist = math.hypot(dx, dy)
            lim = reach
            if bigs[index] or bigs[other]:
                lim = (radii[index] + radii[other]) * 1.32 * scale
            if dist < min_dist or dist > lim:
                continue
            slot = int((math.atan2(dy, dx) + math.pi + 1e-9) / (math.pi / 3)) % 6
            prev = bins[slot]
            if prev is None or dist < prev[0]:
                bins[slot] = (dist, other)
        for item in bins:
            if item is not None:
                add(index, item[1])
    for index in range(count):
        ax, ay = xs[index], ys[index]
        group = groups[index]
        for other in range(index + 1, count):
            if groups[other] != group:
                continue
            dist = math.hypot(xs[other] - ax, ys[other] - ay)
            lim = close
            if bigs[index] or bigs[other]:
                lim = (radii[index] + radii[other]) * 1.22 * scale
            if dist < min_dist or dist > lim:
                continue
            add(index, other)
    return links


def _segment_blocked(
    xs: list[int],
    ys: list[int],
    left: int,
    right: int,
    spacing: float,
    extra_x: list[int] | None = None,
    extra_y: list[int] | None = None,
) -> bool:
    ax, ay = xs[left], ys[left]
    bx, by = xs[right], ys[right]
    vx, vy = bx - ax, by - ay
    length = vx * vx + vy * vy
    if length < 1:
        return False
    thresh = (0.4 * spacing) ** 2
    points: list[tuple[int, int]] = []
    for index, (px, py) in enumerate(zip(xs, ys)):
        if index == left or index == right:
            continue
        points.append((px, py))
    if extra_x and extra_y:
        points.extend(zip(extra_x, extra_y))
    for px, py in points:
        t = ((px - ax) * vx + (py - ay) * vy) / length
        if t <= 0.12 or t >= 0.88:
            continue
        qx = ax + t * vx
        qy = ay + t * vy
        dx = px - qx
        dy = py - qy
        if dx * dx + dy * dy < thresh:
            return True
    return False


def _type_blob(
    seed: int,
    tsums: list[dict[str, int]],
    phys: list[list[int]],
) -> list[int]:
    start = tsums[seed]
    start_group = int(start.get("group") or 1)
    seen = {seed}
    stack = [seed]
    blob: list[int] = []
    while stack:
        current = stack.pop()
        blob.append(current)
        for nxt in phys[current]:
            if nxt in seen:
                continue
            if int(tsums[nxt].get("group") or 1) != start_group:
                continue
            seen.add(nxt)
            stack.append(nxt)
    return blob


def _typical_spacing(tsums: list[dict[str, int]]) -> float:
    if len(tsums) < 2:
        return 0.0
    radii = sorted(max(4, int(piece.get("r") or 12)) for piece in tsums)
    typical_r = radii[len(radii) // 2]
    min_real = typical_r * 1.2
    nearest: list[float] = []
    for index, left in enumerate(tsums):
        ax, ay = int(left["x"]), int(left["y"])
        best = 1e18
        for other, right in enumerate(tsums):
            if other == index:
                continue
            dx = ax - int(right["x"])
            dy = ay - int(right["y"])
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < min_real:
                continue
            if dist < best:
                best = dist
        if best < 1e18:
            nearest.append(best)
    if nearest:
        nearest.sort()
        return nearest[len(nearest) // 2]
    return typical_r * 2.0


def _paths_in_group(
    nodes: list[dict[str, int]],
    tsums: list[dict[str, int]],
    spacing: float,
) -> list[list[dict[str, int]]]:
    count = len(nodes)
    if count < MIN_CHAIN:
        return []
    links = [[] for _ in range(count)]
    for index, left in enumerate(nodes):
        for other, right in enumerate(nodes[index + 1 :], start=index + 1):
            if not _adjacent(left, right, tsums, spacing):
                continue
            links[index].append(other)
            links[other].append(index)
    orders = _collect_paths(links)
    return [[nodes[index] for index in order] for order in orders if len(order) >= MIN_CHAIN]


def _adjacent(
    left: dict[str, int],
    right: dict[str, int],
    tsums: list[dict[str, int]],
    spacing: float,
) -> bool:
    dx = int(left["x"]) - int(right["x"])
    dy = int(left["y"]) - int(right["y"])
    dist2 = dx * dx + dy * dy
    radius = max(4, int(left.get("r") or 0))
    other_r = max(4, int(right.get("r") or 0))
    by_r = (radius + other_r) * RADIUS_NEIGHBOR
    if spacing <= 0:
        limit = by_r
    elif spacing <= by_r * 0.5:
        limit = by_r
    else:
        limit = max(by_r, spacing * SPACING_NEIGHBOR)
        limit = min(limit, spacing * 1.5)
    if dist2 > limit * limit:
        return False
    if spacing <= 0:
        return True
    return not _blocked_by_other(left, right, tsums, spacing)


def _blocked_by_other(
    left: dict[str, int],
    right: dict[str, int],
    tsums: list[dict[str, int]],
    spacing: float,
) -> bool:
    ax, ay = int(left["x"]), int(left["y"])
    bx, by = int(right["x"]), int(right["y"])
    vx, vy = bx - ax, by - ay
    length = vx * vx + vy * vy
    if length < 1:
        return False
    thresh = (BLOCK_FRACTION * spacing) ** 2
    for piece in tsums:
        px, py = int(piece["x"]), int(piece["y"])
        if (px, py) == (ax, ay) or (px, py) == (bx, by):
            continue
        t = ((px - ax) * vx + (py - ay) * vy) / length
        if t <= 0.12 or t >= 0.88:
            continue
        qx = ax + t * vx
        qy = ay + t * vy
        ddx = px - qx
        ddy = py - qy
        if ddx * ddx + ddy * ddy < thresh:
            return True
    return False


def _components(links: list[list[int]]) -> list[list[int]]:
    seen = [False] * len(links)
    found: list[list[int]] = []
    for index in range(len(links)):
        if seen[index]:
            continue
        stack = [index]
        seen[index] = True
        comp: list[int] = []
        while stack:
            node = stack.pop()
            comp.append(node)
            for nxt in links[node]:
                if seen[nxt]:
                    continue
                seen[nxt] = True
                stack.append(nxt)
        if len(comp) >= MIN_CHAIN:
            found.append(comp)
    return found


def _collect_paths(
    links: list[list[int]],
    xs: list[int] | None = None,
    ys: list[int] | None = None,
) -> list[list[int]]:
    found: list[list[int]] = []
    for comp in _components(links):
        found.extend(_paths_in_component(links, comp, xs, ys))
    found.sort(key=len, reverse=True)
    return found


def _paths_in_component(
    links: list[list[int]],
    nodes: list[int],
    xs: list[int] | None = None,
    ys: list[int] | None = None,
) -> list[list[int]]:
    found: dict[frozenset[int], list[int]] = {}

    def consider(path: list[int]) -> None:
        if len(path) < MIN_CHAIN:
            return
        key = frozenset(path)
        prev = found.get(key)
        if prev is None or len(path) > len(prev):
            found[key] = path[:]

    for path in _greedy_on(links, nodes, xs, ys):
        consider(path)
    if len(nodes) > 18:
        return sorted(found.values(), key=len, reverse=True)

    allowed = set(nodes)
    walks = 0
    budget = 200000 if len(nodes) <= 10 else 30000
    per_start = max(800, budget // max(1, len(nodes)))
    if len(nodes) <= 10:
        per_start = budget
    starts = sorted(
        nodes,
        key=lambda node: (sum(1 for nxt in links[node] if nxt in allowed), node),
    )

    def walk(current: int, used: int, path: list[int], remaining: list[int]) -> None:
        nonlocal walks
        walks += 1
        remaining[0] -= 1
        if remaining[0] <= 0 or walks > budget:
            consider(path)
            return
        extended = False
        for nxt in links[current]:
            if nxt not in allowed:
                continue
            bit = 1 << nxt
            if used & bit:
                continue
            if (
                xs is not None
                and ys is not None
                and len(path) >= 2
                and not _turn_ok(
                    xs[current] - xs[path[-2]],
                    ys[current] - ys[path[-2]],
                    xs[nxt] - xs[current],
                    ys[nxt] - ys[current],
                )
            ):
                continue
            extended = True
            path.append(nxt)
            walk(nxt, used | bit, path, remaining)
            path.pop()
            if remaining[0] <= 0 or walks > budget:
                return
        if not extended:
            consider(path)

    for start in starts:
        walk(start, 1 << start, [start], [per_start])
    return sorted(found.values(), key=len, reverse=True)


def _greedy_on(
    links: list[list[int]],
    nodes: list[int],
    xs: list[int] | None = None,
    ys: list[int] | None = None,
) -> list[list[int]]:
    allowed = set(nodes)
    found: dict[frozenset[int], list[int]] = {}
    for start in nodes:
        for dense in (True, False):
            used = {start}
            path = [start]
            current = start
            while True:
                choices = [
                    nxt for nxt in links[current] if nxt not in used and nxt in allowed
                ]
                if not choices:
                    break
                if xs is not None and ys is not None and len(path) >= 2:
                    px = xs[current] - xs[path[-2]]
                    py = ys[current] - ys[path[-2]]
                    ahead = [
                        nxt
                        for nxt in choices
                        if _turn_ok(
                            px,
                            py,
                            xs[nxt] - xs[current],
                            ys[nxt] - ys[current],
                        )
                    ]
                    if ahead:
                        choices = ahead
                    else:
                        break
                if xs is not None and ys is not None:
                    cx, cy = xs[current], ys[current]
                    nxt = min(
                        choices,
                        key=lambda node: (xs[node] - cx) ** 2 + (ys[node] - cy) ** 2,
                    )
                else:
                    nxt = max(
                        choices,
                        key=lambda node: (
                            sum(
                                1
                                for other in links[node]
                                if other not in used and other in allowed
                            )
                            if dense
                            else -sum(
                                1
                                for other in links[node]
                                if other not in used and other in allowed
                            )
                        ),
                    )
                used.add(nxt)
                path.append(nxt)
                current = nxt
            if len(path) < MIN_CHAIN:
                continue
            key = frozenset(path)
            prev = found.get(key)
            if prev is None or len(path) > len(prev):
                found[key] = path
    return sorted(found.values(), key=len, reverse=True)


def _pick_diverse(
    paths: list[list[dict[str, int]]],
    limit: int,
) -> list[list[dict[str, int]]]:
    selected: list[list[dict[str, int]]] = []
    keys: list[frozenset[tuple[int, int, int]]] = []
    for path in paths:
        if len(path) < MIN_CHAIN:
            continue
        key = frozenset(
            (int(piece["x"]), int(piece["y"]), int(piece.get("group") or 1))
            for piece in path
        )
        if any(key & old for old in keys):
            continue
        selected.append(path)
        keys.append(key)
        if len(selected) >= limit:
            break
    return selected
