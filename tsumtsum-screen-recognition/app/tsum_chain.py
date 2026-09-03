from __future__ import annotations

import math

CANDIDATE_COUNT = 3
MIN_CHAIN = 3


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
    tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
    if len(tsums) < MIN_CHAIN:
        return []
    spacing = _typical_spacing(tsums)
    phys = _physical_links(tsums, spacing)
    found = _paths_from_blobs(tsums, phys)
    if not found:
        phys = _physical_links(tsums, spacing, scale=1.12)
        found = _paths_from_blobs(tsums, phys)
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
        for order in _collect_paths(local):
            if len(order) >= MIN_CHAIN:
                found.append([tsums[blob[item]] for item in order])
    return found


def _induced_links(phys: list[list[int]], blob: list[int]) -> list[list[int]]:
    index = {global_i: local for local, global_i in enumerate(blob)}
    links: list[list[int]] = [[] for _ in blob]
    for local, global_i in enumerate(blob):
        for nxt in phys[global_i]:
            if nxt in index:
                links[local].append(index[nxt])
    return links


def _physical_links(
    tsums: list[dict[str, int]], spacing: float, scale: float = 1.0
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
    gap = spacing if spacing > 0 else typical_r * 2.0
    links: list[list[int]] = [[] for _ in range(count)]

    def add(left: int, right: int) -> None:
        if _segment_blocked(xs, ys, left, right, gap):
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
            if dist < min_dist or dist > reach:
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
            if dist < min_dist or dist > close:
                continue
            add(index, other)
    return links


def _segment_blocked(
    xs: list[int],
    ys: list[int],
    left: int,
    right: int,
    spacing: float,
) -> bool:
    ax, ay = xs[left], ys[left]
    bx, by = xs[right], ys[right]
    vx, vy = bx - ax, by - ay
    length = vx * vx + vy * vy
    if length < 1:
        return False
    thresh = (0.4 * spacing) ** 2
    for index, (px, py) in enumerate(zip(xs, ys)):
        if index == left or index == right:
            continue
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


def _collect_paths(links: list[list[int]]) -> list[list[int]]:
    found: list[list[int]] = []
    for comp in _components(links):
        found.extend(_paths_in_component(links, comp))
    found.sort(key=len, reverse=True)
    return found


def _paths_in_component(links: list[list[int]], nodes: list[int]) -> list[list[int]]:
    found: dict[frozenset[int], list[int]] = {}

    def consider(path: list[int]) -> None:
        if len(path) < MIN_CHAIN:
            return
        key = frozenset(path)
        prev = found.get(key)
        if prev is None or len(path) > len(prev):
            found[key] = path[:]

    for path in _greedy_on(links, nodes):
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


def _greedy_on(links: list[list[int]], nodes: list[int]) -> list[list[int]]:
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
        if any(key <= old or old <= key for old in keys):
            continue
        selected.append(path)
        keys.append(key)
        if len(selected) >= limit:
            break
    return selected
