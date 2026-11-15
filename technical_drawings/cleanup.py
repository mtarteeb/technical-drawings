"""2D line clean-up: removes duplicate lines, joins collinear pieces, chains
segments into polylines and recognises true arcs and circles.

All coordinates are metres. Pure geometry, deterministic.
"""

import math
from collections import defaultdict

import numpy as np

SNAP = 1e-5          # 0.01 mm: points closer than this are the same point
AXIS_TOL = 2e-6      # a segment is horizontal/vertical when it deviates less than this


def _key(v):
    return int(round(v / SNAP))


def to_segments(polylines):
    """Polylines -> (N, 4) array of segments x0, y0, x1, y1."""
    parts = []
    for pl in polylines:
        pl = np.asarray(pl, dtype=np.float64)
        if len(pl) >= 2:
            parts.append(np.hstack((pl[:-1], pl[1:])))
    if not parts:
        return np.empty((0, 4))
    return np.vstack(parts)


def split_axis_aligned(segments):
    """Return (horizontal, vertical, other).

    horizontal: list of (y, x0, x1) with x0 < x1, merged and de-duplicated
    vertical:   list of (x, y0, y1) with y0 < y1, merged and de-duplicated
    other:      (M, 4) array of remaining segments, exact duplicates removed
    """
    if len(segments) == 0:
        return [], [], np.empty((0, 4))
    dx = np.abs(segments[:, 2] - segments[:, 0])
    dy = np.abs(segments[:, 3] - segments[:, 1])
    length = np.hypot(dx, dy)
    segments = segments[length > SNAP]
    dx = np.abs(segments[:, 2] - segments[:, 0])
    dy = np.abs(segments[:, 3] - segments[:, 1])
    is_h = dy <= AXIS_TOL
    is_v = (dx <= AXIS_TOL) & ~is_h

    def merge(const, a, b):
        groups = defaultdict(list)
        for c, lo, hi in zip(const, np.minimum(a, b), np.maximum(a, b)):
            groups[_key(c)].append((lo, hi, c))
        out = []
        for items in groups.values():
            items.sort()
            c = items[0][2]
            lo, hi = items[0][0], items[0][1]
            for nlo, nhi, _ in items[1:]:
                if nlo <= hi + SNAP:
                    hi = max(hi, nhi)
                else:
                    out.append((c, lo, hi))
                    lo, hi = nlo, nhi
            out.append((c, lo, hi))
        return out

    h = segments[is_h]
    v = segments[is_v]
    horizontal = merge((h[:, 1] + h[:, 3]) / 2.0, h[:, 0], h[:, 2])
    vertical = merge((v[:, 0] + v[:, 2]) / 2.0, v[:, 1], v[:, 3])

    rest = segments[~(is_h | is_v)]
    seen = set()
    keep = []
    for i, (x0, y0, x1, y1) in enumerate(rest):
        a = (_key(x0), _key(y0))
        b = (_key(x1), _key(y1))
        k = (a, b) if a <= b else (b, a)
        if k not in seen:
            seen.add(k)
            keep.append(i)
    return horizontal, vertical, rest[keep]


def clean_segments(polylines):
    """Polylines -> de-duplicated (N, 4) segment array."""
    h, v, other = split_axis_aligned(to_segments(polylines))
    rows = [(x0, y, x1, y) for y, x0, x1 in h] + [(x, y0, x, y1) for x, y0, y1 in v]
    if rows:
        return np.vstack((np.array(rows), other)) if len(other) else np.array(rows)
    return other


def chain(segments):
    """Join segments end to end into polylines. Returns list of (N, 2) arrays;
    a closed loop repeats its first point at the end."""
    if len(segments) == 0:
        return []
    nodes = {}
    coords = []

    def node(x, y):
        k = (_key(x), _key(y))
        idx = nodes.get(k)
        if idx is None:
            idx = len(coords)
            nodes[k] = idx
            coords.append((x, y))
        return idx

    edges = []
    adjacency = defaultdict(list)
    for x0, y0, x1, y1 in segments:
        a, b = node(x0, y0), node(x1, y1)
        if a == b:
            continue
        adjacency[a].append((b, len(edges)))
        adjacency[b].append((a, len(edges)))
        edges.append((a, b))

    used = [False] * len(edges)
    result = []

    def walk(start, first_edge):
        path = [start]
        current = start
        edge = first_edge
        while edge is not None:
            used[edge] = True
            a, b = edges[edge]
            current = b if a == current else a
            path.append(current)
            edge = None
            if len(adjacency[current]) == 2 and current != start:
                for _, e in adjacency[current]:
                    if not used[e]:
                        edge = e
        return path

    # Open chains start at nodes that are not simple pass-through points.
    for n, links in adjacency.items():
        if len(links) != 2:
            for _, e in links:
                if not used[e]:
                    result.append(walk(n, e))
    # What is left are closed loops.
    for e, (a, _) in enumerate(edges):
        if not used[e]:
            result.append(walk(a, e))
    return [np.array([coords[i] for i in path]) for path in result]


class Arc:
    """A circular arc found in a polyline (centre, radius, angles in radians,
    counter-clockwise from start to end). `full` marks a complete circle."""

    def __init__(self, cx, cy, r, a0, a1, full, i0, i1):
        self.cx, self.cy, self.r = cx, cy, r
        self.a0, self.a1, self.full = a0, a1, full
        self.i0, self.i1 = i0, i1          # index range of the points it replaces

    @property
    def sweep(self):
        return 2 * math.pi if self.full else (self.a1 - self.a0) % (2 * math.pi)

    def mid_point(self):
        a = self.a0 + self.sweep / 2.0
        return self.cx + self.r * math.cos(a), self.cy + self.r * math.sin(a)


def _circumcircle(p0, p1, p2):
    ax, ay = p0
    bx, by = p1
    cx, cy = p2
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-14:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy), d > 0


def find_arcs(polyline, min_points=5, min_sweep=math.radians(25.0), tol=0.01):
    """Find runs of points that lie on one circle. Returns list of Arc."""
    pts = np.asarray(polyline, dtype=np.float64)
    n = len(pts)
    closed = n > 3 and np.hypot(*(pts[0] - pts[-1])) <= SNAP
    if n < min_points:
        return []
    circles = [None] * n
    for i in range(1, n - 1):
        circles[i] = _circumcircle(pts[i - 1], pts[i], pts[i + 1])

    arcs = []
    i = 1
    while i < n - 1:
        c = circles[i]
        if c is None:
            i += 1
            continue
        cx, cy, r, ccw = c
        j = i
        sx, sy, sr, count = cx, cy, r, 1
        while j + 1 < n - 1 and circles[j + 1] is not None:
            nx, ny, nr, nccw = circles[j + 1]
            mr = sr / count
            if nccw != ccw or abs(nr - mr) > tol * mr or math.hypot(nx - sx / count, ny - sy / count) > tol * mr:
                break
            sx, sy, sr, count = sx + nx, sy + ny, sr + nr, count + 1
            j += 1
        i0, i1 = i - 1, j + 1
        if i1 - i0 + 1 >= min_points:
            cx, cy = sx / count, sy / count
            run = pts[i0:i1 + 1]
            r = float(np.mean(np.hypot(run[:, 0] - cx, run[:, 1] - cy)))
            a_start = math.atan2(run[0, 1] - cy, run[0, 0] - cx)
            a_end = math.atan2(run[-1, 1] - cy, run[-1, 0] - cx)
            steps = np.unwrap(np.arctan2(run[:, 1] - cy, run[:, 0] - cx))
            sweep = abs(steps[-1] - steps[0])
            # A real arc is made of many short facets. Four corners of a
            # rectangle also share one circle, so reject coarse steps.
            if np.abs(np.diff(steps)).max() > math.radians(32.0):
                i = j + 1
                continue
            full = closed and i0 == 0 and i1 == n - 1 and sweep > math.radians(340.0)
            if sweep >= min_sweep or full:
                a0, a1 = (a_start, a_end) if ccw else (a_end, a_start)
                arcs.append(Arc(cx, cy, r, a0, a1, full, i0, i1))
        i = j + 1
    return arcs


def slanted_edges(segments, angle_step=math.radians(0.5), offset_step=5e-4):
    """Straight edges that are neither horizontal nor vertical.

    Collinear pieces (Line Art splits an edge wherever something crosses it)
    are joined back into whole edges. Returns a list of
    (x0, y0, x1, y1, length, angle) with the first point the lower one and
    `angle` the edge's slope from the horizontal in radians (0..pi/2).
    """
    if len(segments) == 0:
        return []
    groups = defaultdict(list)
    for x0, y0, x1, y1 in segments:
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length <= SNAP:
            continue
        ux, uy = dx / length, dy / length
        if uy < 0 or (uy == 0 and ux < 0):
            ux, uy = -ux, -uy
        theta = math.atan2(uy, ux)                    # 0..pi
        offset = x0 * uy - y0 * ux                    # signed distance of the line from the origin
        t0, t1 = x0 * ux + y0 * uy, x1 * ux + y1 * uy
        groups[(round(theta / angle_step), round(offset / offset_step))].append(
            (min(t0, t1), max(t0, t1), ux, uy, offset, length))
    edges = []
    for items in groups.values():
        items.sort()
        # Direction and position from the longest piece: the most accurate one.
        _, _, ux, uy, offset, _ = max(items, key=lambda it: it[5])
        lo, hi = items[0][0], items[0][1]
        runs = []
        for nlo, nhi, *_rest in items[1:]:
            if nlo <= hi + 1e-4:
                hi = max(hi, nhi)
            else:
                runs.append((lo, hi))
                lo, hi = nlo, nhi
        runs.append((lo, hi))
        for lo, hi in runs:
            # Point on the line at parameter t: t * u + offset * (uy, -ux)
            bx, by = offset * uy, -offset * ux
            x0, y0 = bx + lo * ux, by + lo * uy
            x1, y1 = bx + hi * ux, by + hi * uy
            slope = math.atan2(abs(uy), abs(ux))
            edges.append((x0, y0, x1, y1, hi - lo, slope))
    return edges
