"""Automatic dimensions, measured from the model's own geometry.

Rules (no AI): a view is dimensioned where it has long straight edges.
Every vertical edge position is a candidate break for the horizontal chain,
weighted by how much edge length sits on it; the same for horizontal edges
and the vertical chain. Overall sizes are always given. Arcs get a radius.
"""

import math
from collections import defaultdict

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


def compute(view, fmt, k, text_size, detail='MEDIUM', forced_parts=(), radii=True):
    """Work out the dimensions of one view.

    k: paper millimetres per model metre (so text fitting can be checked)
    text_size: dimension text size in paper mm
    forced_parts: names of objects whose edges must appear in the chains
    """
    from .export_pdf import text_width

    segs = cleanup.to_segments(view.polylines)
    horizontal, vertical, _other = cleanup.split_axis_aligned(segs)
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
        return (text_width(fmt.text(length), text_size) + 1.6) / k

    out = ViewDims()
    xb = _breaks(vertical, view.min_x, view.max_x, view.height, threshold, fx)
    yb = _breaks(horizontal, view.min_y, view.max_y, view.width, threshold, fy)
    out.x_chain = _prune(xb, min_gap)
    out.y_chain = _prune(yb, min_gap)

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
