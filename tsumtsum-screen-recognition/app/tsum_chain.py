from __future__ import annotations

CANDIDATE_COUNT = 3
SPACING_NEIGHBOR = 1.5
RADIUS_NEIGHBOR = 1.12
BLOCK_FRACTION = 0.4


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
    tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
    spacing = _typical_spacing(tsums)
    groups: dict[int, list[dict[str, int]]] = {}
    for piece in tsums:
        groups.setdefault(int(piece.get("group") or 1), []).append(piece)
    found: list[list[dict[str, int]]] = []
    for nodes in groups.values():
        found.extend(_paths_in_group(nodes, tsums, spacing))
    found.sort(key=len, reverse=True)
    return _pick_diverse(found, limit)


def _typical_spacing(tsums: list[dict[str, int]]) -> float:
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
            dist2 = dx * dx + dy * dy
            if dist2 < best:
                best = dist2
        if best < 1e18:
            nearest.append(best ** 0.5)
    if not nearest:
        return 0.0
    nearest.sort()
    return nearest[len(nearest) // 2]


def _paths_in_group(
    nodes: list[dict[str, int]],
    tsums: list[dict[str, int]],
    spacing: float,
) -> list[list[dict[str, int]]]:
    count = len(nodes)
    if count <= 1:
        return []
    links = [[] for _ in range(count)]
    for index, left in enumerate(nodes):
        for other, right in enumerate(nodes[index + 1 :], start=index + 1):
            if not _adjacent(left, right, tsums, spacing):
                continue
            links[index].append(other)
            links[other].append(index)
    orders = _collect_paths(links)
    return [[nodes[index] for index in order] for order in orders if len(order) >= 2]


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
    limit = (radius + other_r) * RADIUS_NEIGHBOR
    if spacing > 0:
        limit = max(limit, spacing * SPACING_NEIGHBOR)
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
        if piece is left or piece is right:
            continue
        px, py = int(piece["x"]), int(piece["y"])
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


def _collect_paths(links: list[list[int]]) -> list[list[int]]:
    count = len(links)
    if count <= 1:
        return []
    if count > 16:
        return _greedy_paths(links)
    found: dict[frozenset[int], list[int]] = {}
    walks = 0
    walk_limit = 8000

    def consider(path: list[int]) -> None:
        if len(path) < 2:
            return
        key = frozenset(path)
        prev = found.get(key)
        if prev is None or len(path) > len(prev):
            found[key] = path[:]

    def walk(current: int, used: int, path: list[int]) -> None:
        nonlocal walks
        walks += 1
        if walks > walk_limit:
            return
        extended = False
        for nxt in links[current]:
            bit = 1 << nxt
            if used & bit:
                continue
            extended = True
            path.append(nxt)
            walk(nxt, used | bit, path)
            path.pop()
            if walks > walk_limit:
                return
        if not extended:
            consider(path)

    for start in range(count):
        walk(start, 1 << start, [start])
        if walks > walk_limit:
            break
    if not found:
        return _greedy_paths(links)
    return sorted(found.values(), key=len, reverse=True)


def _greedy_paths(links: list[list[int]]) -> list[list[int]]:
    found: dict[frozenset[int], list[int]] = {}
    for start in range(len(links)):
        used = {start}
        path = [start]
        current = start
        while True:
            choices = [nxt for nxt in links[current] if nxt not in used]
            if not choices:
                break
            nxt = max(
                choices,
                key=lambda node: sum(1 for other in links[node] if other not in used),
            )
            used.add(nxt)
            path.append(nxt)
            current = nxt
        if len(path) < 2:
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
        if len(path) < 2:
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
