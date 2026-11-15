"""Automatic dimensions, measured from the model's own geometry.

Rules (no AI): a view is dimensioned where it has long straight edges.
Every vertical edge position is a candidate break for the horizontal chain,
weighted by how much edge length sits on it; the same for horizontal edges
and the vertical chain. Overall sizes are always given. Arcs get a radius.
"""

import math
from collections import defaultdict

import numpy as np

from . import cleanup

UNITS = {            # name: (factor from metres, label)
    'CM': (100.0, "cm"),
    'MM': (1000.0, "mm"),
    'M': (1.0, "m"),
    'IN': (39.37007874, "in"),
}

DETAIL = {'LOW': 0.40, 'MEDIUM': 0.22, 'HIGH': 0.10}
MAX_SEGMENTS = 12
CLUSTER = 5e-4       # 0.5 mm: breaks closer than this are one break


class Format:
    """Turns a length in metres into dimension text."""

    def __init__(self, unit='CM', decimals=1, suffix='SPACED'):
        self.unit = unit
        self.factor, self.label = UNITS[unit]
        self.decimals = decimals
        self.suffix = suffix          # NONE | SPACED ("500 cm") | UPPER ("500CM")

    def number(self, metres):
        text = "%.*f" % (self.decimals, metres * self.factor)
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return "0" if text in ("-0", "") else text

    def text(self, metres):
        n = self.number(metres)
        if self.suffix == 'SPACED':
            return "%s %s" % (n, self.label)
        if self.suffix == 'UPPER':
            return n + self.label.upper()
        return n

    @property
    def dxf_post(self):
        if self.suffix == 'SPACED':
            return "<> " + self.label
        if self.suffix == 'UPPER':
            return "<>" + self.label.upper()
        return ""


def _breaks(lines, lo, hi, cross_extent, threshold, forced):
    """Significant positions along one axis.

    lines: list of (position, start, end) straight edges perpendicular to the axis
    lo, hi: extent of the view along the axis
    cross_extent: extent of the view across the axis (edges are compared to it)
    forced: positions that must be kept (edges of objects marked by the user)
    Returns {position: score}.
    """
    # Cluster nearby edges, but keep the exact position of the longest edge
    # in each cluster so the dimension value is never rounded.
    score = defaultdict(lambda: [0.0, 0.0, 0.0])      # total, longest, exact position
    for pos, a, b in lines:
        entry = score[round(pos / CLUSTER)]
        entry[0] += b - a
        if b - a > entry[1]:
            entry[1], entry[2] = b - a, pos
    out = {}
    need = threshold * cross_extent
    for total, _longest, pos in score.values():
        if total >= need:
            out[pos] = total
    for pos in forced:
        if lo - CLUSTER <= pos <= hi + CLUSTER:
            near = [p for p in out if abs(p - pos) <= CLUSTER]
            for p in near:
                del out[p]
            out[pos] = float('inf')
    # Extremes always, snapped exactly.
    out = {p: s for p, s in out.items() if lo + CLUSTER < p < hi - CLUSTER}
    out[lo] = float('inf')
    out[hi] = float('inf')
    return out


def _prune(breaks, min_gap_of):
    """Drop the weakest breaks until every chain segment has room for its text.

    min_gap_of(length) -> minimum length (model metres) a segment of that
    length needs so that its text fits.
    """
    pos = sorted(breaks)
    while len(pos) > 2:
        worst = None
        for i in range(len(pos) - 1):
            gap = pos[i + 1] - pos[i]
            if gap < min_gap_of(gap):
                # Remove the weaker of the two breaks bounding this gap.
                cands = [p for p in (pos[i], pos[i + 1]) if breaks[p] != float('inf')]
                if not cands:
                    continue
                victim = min(cands, key=lambda p: breaks[p])
                if worst is None or breaks[victim] < breaks[worst]:
                    worst = victim
        if worst is None:
            if len(pos) - 1 > MAX_SEGMENTS:
                finite = [p for p in pos if breaks[p] != float('inf')]
                if not finite:
                    break
                worst = min(finite, key=lambda p: breaks[p])
            else:
                break
        pos.remove(worst)
    return pos


class ViewDims:
    def __init__(self):
        self.x_chain = []      # sorted x positions (metres) for the horizontal chain
        self.y_chain = []      # sorted y positions for the vertical chain
        self.arcs = []         # cleanup.Arc, one per distinct radius
        self.slanted = []      # (x0, y0, x1, y1, length, slope): angled edges to dimension


def compute(view, fmt, k, text_size, detail='MEDIUM', forced_parts=(), radii=True):
    """Work out the dimensions of one view.

    k: paper millimetres per model metre (so text fitting can be checked)
    text_size: dimension text size in paper mm
    forced_parts: names of objects whose edges must appear in the chains
    """
    from .export_pdf import text_width

    segs = cleanup.to_segments(view.polylines)
    horizontal, vertical, other = cleanup.split_axis_aligned(segs)
    threshold = DETAIL[detail]

    # Lettering (text objects) is drawn but never dimensioned.
    pad = 1e-4
    boxes = [(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad) for b in getattr(view, 'text_boxes', ())]

    def in_text(x, y):
        return any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes)

    if boxes:
        horizontal = [(y, x0, x1) for y, x0, x1 in horizontal if not in_text((x0 + x1) / 2.0, y)]
        vertical = [(x, y0, y1) for x, y0, y1 in vertical if not in_text(x, (y0 + y1) / 2.0)]

    fx, fy = [], []
    for name in forced_parts:
        box = view.parts.get(name)
        if box:
            fx += [box[0], box[2]]
            fy += [box[1], box[3]]

    def min_gap(length):
        # A break is only dropped when its gap is too small to draw at all.
        # Gaps that are merely narrower than their text are kept, and the text
        # is placed beside the dimension line: an inner size such as a frame
        # thickness or an opening must never disappear.
        return 2.5 / k

    out = ViewDims()
    xb = _breaks(vertical, view.min_x, view.max_x, view.height, threshold, fx)
    yb = _breaks(horizontal, view.min_y, view.max_y, view.width, threshold, fy)
    def thin_out(breaks, pos):
        """Keep a chain legible: text that does not fit its gap goes on a second
        row, and that row only has room for so much. When it would overflow,
        the least prominent breaks are dropped (never the user's own, and never
        the first or last gap, whose text goes outside the chain)."""
        pos = list(pos)
        while len(pos) > 3:
            length = (pos[-1] - pos[0]) * k
            crowd = 0.0
            for a, b in zip(pos[1:-2], pos[2:-1]):
                w = text_width(fmt.text(b - a), text_size)
                if w + 1.0 > (b - a) * k:
                    crowd += w + 1.2
            if crowd <= 0.6 * length:
                break
            finite = [p for p in pos[1:-1] if breaks[p] != float('inf')]
            if not finite:
                break
            pos.remove(min(finite, key=lambda p: breaks[p]))
        return pos

    out.x_chain = thin_out(xb, _prune(xb, min_gap))
    out.y_chain = thin_out(yb, _prune(yb, min_gap))

    # Angled edges: long straight edges that are neither horizontal nor vertical
    # get their true length and their angle. Edges on the outline come first,
    # because their dimension can sit clear of the drawing; an edge inside the
    # drawing is only taken when it is a major one. Edges of about the same
    # length and angle (the two sides of one bar, or a mirrored pair) are given once.
    extent = max(view.width, view.height)
    share = {'LOW': 0.16, 'MEDIUM': 0.09, 'HIGH': 0.05}[detail]
    cx, cy = (view.min_x + view.max_x) / 2.0, (view.min_y + view.max_y) / 2.0
    px, py = segs[:, 0], segs[:, 1]
    dx, dy = segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]

    def on_outline(x0, y0, x1, y1):
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        length = math.hypot(x1 - x0, y1 - y0)
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        # Does a ray from the edge's middle, pointing outwards, meet any other line?
        denom = nx * dy - ny * dx
        ok = np.abs(denom) > 1e-12
        safe = np.where(ok, denom, 1.0)
        wx, wy = px - mx, py - my
        s = (wx * dy - wy * dx) / safe
        u = (wx * ny - wy * nx) / safe
        return not bool(np.any(ok & (s > 1e-4) & (u >= 0.0) & (u <= 1.0)))

    candidates = []
    for edge in cleanup.slanted_edges(other):
        x0, y0, x1, y1, length, slope = edge
        if length < share * extent or length * k < 6.0:
            continue
        if not (math.radians(1.0) < slope < math.radians(89.0)):
            continue
        if in_text((x0 + x1) / 2.0, (y0 + y1) / 2.0):
            continue
        candidates.append(edge)
    candidates.sort(key=lambda e: -e[4])
    picked = []
    for edge in candidates:
        length, slope = edge[4], edge[5]
        # The chains run down the left and along the bottom, so of two matching
        # edges (a mirrored pair) keep the one nearer the top right, where its
        # dimension has free space.
        def free_side(e):
            return ((e[0] + e[2]) / 2.0 > cx) + ((e[1] + e[3]) / 2.0 > cy)

        twin = next((i for i, o in enumerate(picked)
                     if abs(slope - o[5]) < math.radians(3.0) and abs(length - o[4]) < 0.12 * o[4]), None)
        if twin is not None:
            if free_side(edge) > free_side(picked[twin]) and (
                    on_outline(*edge[:4]) or not on_outline(*picked[twin][:4])):
                picked[twin] = edge
            continue
        # The second side of the same bar: parallel to, and close beside, a longer edge already taken.
        mx, my = (edge[0] + edge[2]) / 2.0, (edge[1] + edge[3]) / 2.0

        def beside(o):
            ox, oy = o[2] - o[0], o[3] - o[1]
            ol = math.hypot(ox, oy)
            ex_, ey_ = edge[2] - edge[0], edge[3] - edge[1]
            parallel = abs(ox * ey_ - oy * ex_) < 0.06 * ol * length
            return parallel and abs((mx - o[0]) * oy - (my - o[1]) * ox) / ol < 0.1 * extent

        if any(beside(o) for o in picked):
            continue
        if not on_outline(*edge[:4]) and length < 0.25 * extent:
            continue
        picked.append(edge)
        if len(picked) == 4:
            break
    out.slanted = picked

    if radii:
        found = {}
        for pl in cleanup.chain(cleanup.clean_segments(view.polylines)):
            for arc in cleanup.find_arcs(pl):
                if arc.r * k < 2.5:              # too small to label on paper
                    continue
                if in_text(*arc.mid_point()):
                    continue
                key = fmt.number(arc.r)
                best = found.get(key)
                if best is None or arc.sweep * arc.r > best.sweep * best.r:
                    found[key] = arc
        out.arcs = sorted(found.values(), key=lambda a: -a.r)[:8]
    return out


def needed_k(view, fmt, text_size, detail='MEDIUM', forced_parts=(), share=0.8):
    """Paper millimetres per model metre this view needs so that `share` of
    its chain dimensions have room for their text at `text_size`."""
    from .export_pdf import text_width

    segs = cleanup.to_segments(view.polylines)
    horizontal, vertical, _other = cleanup.split_axis_aligned(segs)
    pad = 1e-4
    boxes = [(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad) for b in getattr(view, 'text_boxes', ())]
    if boxes:
        def in_text(x, y):
            return any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes)
        horizontal = [(y, x0, x1) for y, x0, x1 in horizontal if not in_text((x0 + x1) / 2.0, y)]
        vertical = [(x, y0, y1) for x, y0, y1 in vertical if not in_text(x, (y0 + y1) / 2.0)]
    fx, fy = [], []
    for name in forced_parts:
        box = view.parts.get(name)
        if box:
            fx += [box[0], box[2]]
            fy += [box[1], box[3]]
    threshold = DETAIL[detail]
    needs = []
    for breaks in (_breaks(vertical, view.min_x, view.max_x, view.height, threshold, fx),
                   _breaks(horizontal, view.min_y, view.max_y, view.width, threshold, fy)):
        pos = sorted(breaks)
        extent = pos[-1] - pos[0]
        for a, b in zip(pos[:-1], pos[1:]):
            # Small details (under 5% of the view) never fit their text; they
            # are labelled beside the line and do not drive the scale.
            if b - a >= 0.05 * extent:
                needs.append((text_width(fmt.text(b - a), text_size) + 1.6) / (b - a))
    if not needs:
        return 0.0
    needs.sort()
    return needs[min(len(needs) - 1, int(math.ceil(share * len(needs))) - 1)]
