"""Sheet layout: places views, dimensions, notes, pictures and the bottom
information strip on paper.

Produces a flat list of drawing items in paper millimetres (origin top-left,
y down) that every exporter (PDF, SVG, DXF) consumes, so all file formats
show the same sheet.
"""

import math
from dataclasses import dataclass, field

from . import cleanup, dims as D

PAPER_SIZES = {          # landscape, millimetres
    'A4': (297.0, 210.0),
    'A3': (420.0, 297.0),
    'A2': (594.0, 420.0),
    'A1': (841.0, 594.0),
    'A0': (1189.0, 841.0),
}

SCALES = [1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250, 500, 1000]

RED = (0.816, 0.125, 0.165)
BLACK = (0.0, 0.0, 0.0)
GREY = (0.45, 0.45, 0.45)
DIM_GREY = (0.30, 0.30, 0.30)
FRAME_GREY = (0.55, 0.55, 0.55)

# Layer names are shared by SVG groups and DXF layers.
L_FRAME = "FRAME"
L_VISIBLE = "VISIBLE"
L_HIDDEN = "HIDDEN"
L_LIGHTS = "LIGHTS"
L_TEXT = "TEXT"
L_DIMS = "DIMENSIONS"
L_NOTES = "NOTES"
L_PICTURES = "PICTURES"


@dataclass
class Line:
    points: list                 # [(x, y), ...] paper mm
    layer: str = L_VISIBLE
    color: tuple = BLACK
    width: float = 0.18          # mm
    dash: tuple = ()             # mm on/off
    closed: bool = False
    fill: tuple = None           # fill colour for closed shapes


@dataclass
class Text:
    x: float
    y: float                     # baseline
    text: str
    size: float = 2.8            # font size in mm
    layer: str = L_TEXT
    color: tuple = BLACK
    bold: bool = False
    anchor: str = 'start'        # start | middle | end
    rotation: float = 0.0        # degrees, counter-clockwise


@dataclass
class Fill:
    x: float
    y: float
    w: float
    h: float
    color: tuple
    layer: str = L_FRAME


@dataclass
class Picture:
    path: str
    x: float
    y: float
    w: float
    h: float
    layer: str = L_PICTURES


@dataclass
class Dim:
    """A linear dimension. p1/p2 are the measured points, a/b the ends of the
    dimension line (a belongs to p1, b to p2)."""
    p1: tuple
    p2: tuple
    a: tuple
    b: tuple
    text: str
    size: float = 2.2
    layer: str = L_DIMS
    color: tuple = DIM_GREY
    width: float = 0.10
    bold: bool = False
    text_level: int = 0          # 0 = above the line; 1, 2 = below it (text too wide for the gap)
    text_shift: float = 0.0      # slide the text along the line, as a share of its length

    def text_position(self):
        """(x, y, rotation in degrees) of the middle of the text baseline."""
        ax, ay = self.a
        bx, by = self.b
        length = math.hypot(bx - ax, by - ay) or 1.0
        ux, uy = (bx - ax) / length, (by - ay) / length
        # Reading direction: left to right, or bottom to top.
        if ux < -1e-9 or (abs(ux) <= 1e-9 and uy > 0):
            ux, uy = -ux, -uy
        nx, ny = uy, -ux                      # "above" the line as it is read
        off = self.size * (0.32 if self.text_level == 0 else -(0.95 + 1.1 * (self.text_level - 1)))
        mx = (ax + bx) / 2.0 + ux * length * self.text_shift
        my = (ay + by) / 2.0 + uy * length * self.text_shift
        return mx + nx * off, my + ny * off, math.degrees(math.atan2(-uy, ux))


@dataclass
class Leader:
    """An arrow from a point on the drawing to a piece of text."""
    points: list                 # first point is the arrow tip
    text: str
    size: float = 2.2
    layer: str = L_NOTES
    color: tuple = DIM_GREY
    width: float = 0.10
    anchor: str = 'start'
    bold: bool = False
    arrow: float = 1.6           # arrow head length, 0 for none


def expand(item):
    """Break a Dim or Leader into plain Line and Text items."""
    if isinstance(item, Dim):
        return _expand_dim(item)
    if isinstance(item, Leader):
        return _expand_leader(item)
    return [item]


def _expand_dim(d):
    out = []
    ax, ay = d.a
    bx, by = d.b
    length = math.hypot(bx - ax, by - ay)
    if length < 1e-6:
        return out
    ux, uy = (bx - ax) / length, (by - ay) / length
    # Reading direction: left to right, or bottom to top.
    if ux < -1e-9 or (abs(ux) <= 1e-9 and uy > 0):
        ux, uy = -ux, -uy
    nx, ny = uy, -ux                      # "above" the line as it is read
    tick = d.size * 0.42
    for p, q in ((d.p1, d.a), (d.p2, d.b)):
        ex, ey = q[0] - p[0], q[1] - p[1]
        el = math.hypot(ex, ey)
        if el > 1.2:
            ex, ey = ex / el, ey / el
            out.append(Line([(p[0] + ex * 0.8, p[1] + ey * 0.8), (q[0] + ex * 1.0, q[1] + ey * 1.0)],
                            d.layer, d.color, d.width))
        out.append(Line([(q[0] - (ux + nx) * tick, q[1] - (uy + ny) * tick),
                         (q[0] + (ux + nx) * tick, q[1] + (uy + ny) * tick)],
                        d.layer, d.color, d.width * 2.2))
    out.append(Line([d.a, d.b], d.layer, d.color, d.width))
    tx, ty, rotation = d.text_position()
    out.append(Text(tx, ty, d.text, d.size, d.layer, d.color,
                    bold=d.bold, anchor='middle', rotation=rotation))
    return out


def _expand_leader(l):
    out = []
    pts = l.points
    if len(pts) >= 2:
        out.append(Line(list(pts), l.layer, l.color, l.width))
        (x0, y0), (x1, y1) = pts[0], pts[1]
        length = math.hypot(x1 - x0, y1 - y0)
        if l.arrow and length > l.arrow:
            ux, uy = (x1 - x0) / length, (y1 - y0) / length
            w = l.arrow * 0.22
            out.append(Line([(x0, y0),
                             (x0 + ux * l.arrow - uy * w, y0 + uy * l.arrow + ux * w),
                             (x0 + ux * l.arrow + uy * w, y0 + uy * l.arrow - ux * w)],
                            l.layer, l.color, 0.0, closed=True, fill=l.color))
    ex, ey = pts[-1]
    gap = 0.8 if l.anchor == 'start' else -0.8
    out.append(Text(ex + gap, ey + l.size * 0.33, l.text, l.size, l.layer, l.color,
                    bold=l.bold, anchor=l.anchor))
    return out


@dataclass
class SheetSettings:
    paper: str = 'A3'
    project_name: str = ""
    client: str = ""
    drawing_title: str = ""
    drawn_by: str = ""
    notes: list = field(default_factory=list)       # general notes, list of str
    swatches: list = field(default_factory=list)    # list of (name, (r,g,b))
    pictures: list = field(default_factory=list)    # list of (path, pixel_w, pixel_h)
    hidden_lines: bool = False
    dimensions: bool = True
    fmt: object = None                              # dims.Format
    detail: str = 'MEDIUM'
    radii: bool = True
    object_notes: list = field(default_factory=list)    # list of (object name, text)
    forced_parts: list = field(default_factory=list)    # object names with their own dimensions
    dim_text_size: float = 2.1


@dataclass
class Placement:
    """Where a view landed on the sheet: paper = origin + (model - min) * k."""
    view: object
    x: float           # paper x of the view's left edge
    y: float           # paper y of the view's top edge
    k: float           # paper mm per model metre

    def to_paper(self, mx, my):
        return (self.x + (mx - self.view.min_x) * self.k,
                self.y + (self.view.max_y - my) * self.k)

    @property
    def right(self):
        return self.x + self.view.width * self.k

    @property
    def bottom(self):
        return self.y + self.view.height * self.k


@dataclass
class Sheet:
    width: float
    height: float
    items: list
    placements: dict
    scale: int
    title: str
    fmt: object = None


MARGIN = 8.0
STRIP_H = 30.0
STRIP_HEAD_H = 7.0
CELL_GAP = 8.0           # paper mm between view cells
LABEL_H = 7.0
DIM_STEP = 7.5           # distance between dimension levels
NOTE_GAP = 9.0           # view edge to the note text


def _arrangements(views):
    """Candidate layouts as rows of view names. Top view under the front view
    first (the house style), then everything in one row."""
    names = [n for n in ('FRONT', 'RIGHT', 'LEFT', 'BACK') if n in views]
    top = ['TOP'] if 'TOP' in views else []
    cands = []
    if names and top:
        cands.append([names, top])
        cands.append([names + top])
        if len(names) > 1:
            cands.append([names[:1] + top, names[1:]])
    else:
        cands.append([names + top])
    return cands


def _block_size(rows, views, k, margins):
    widths, heights = [], []
    for row in rows:
        w = sum(views[n].width * k + margins[n][0] + margins[n][1] for n in row) + CELL_GAP * (len(row) - 1)
        h = max(views[n].height * k for n in row) + max(margins[n][2] + margins[n][3] for n in row)
        widths.append(w)
        heights.append(h)
    return max(widths), sum(heights) + CELL_GAP * (len(rows) - 1)


def _choose_layout(views, avail_w, avail_h, margins):
    best = None
    for rows in _arrangements(views):
        for scale in SCALES:
            k = 1000.0 / scale
            w, h = _block_size(rows, views, k, margins)
            if w <= avail_w and h <= avail_h:
                if best is None or scale < best[0]:
                    best = (scale, rows)
                break
    if best is None:
        best = (SCALES[-1], _arrangements(views)[0])
    return best


def _assign_notes(views, object_notes):
    """Give every note to the view that shows its object largest."""
    per_view = {name: [] for name in views}
    order = [n for n in ('FRONT', 'TOP', 'RIGHT', 'LEFT', 'BACK') if n in views]
    for obj_name, text in object_notes:
        best, best_area = None, -1.0
        for name in order:
            box = views[name].parts.get(obj_name)
            if not box:
                continue
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area > best_area * 1.0001:
                best, best_area = name, area
        if best:
            per_view[best].append((obj_name, text))
    return per_view


def _strip(items, settings, left, right, bottom, strip_top, scale):
    items.append(Line([(left, strip_top), (right, strip_top)], L_FRAME, FRAME_GREY, 0.25))
    head_bottom = strip_top + STRIP_HEAD_H
    items.append(Line([(left, head_bottom), (right, head_bottom)], L_FRAME, FRAME_GREY, 0.18))
    total = right - left
    fractions = [("Project Name", 0.123), ("Client", 0.167), ("General  Notes", 0.358),
                 ("Pantone Color Code", 0.198), ("Drawing By", 0.154)]
    col_x = [left]
    for _, frac in fractions:
        col_x.append(col_x[-1] + total * frac)
    col_x[-1] = right
    for x in col_x[1:-1]:
        items.append(Line([(x, strip_top), (x, bottom)], L_FRAME, FRAME_GREY, 0.18))
    for i, (label, _) in enumerate(fractions):
        cx = (col_x[i] + col_x[i + 1]) / 2.0 if i != 2 else col_x[i] + 5.0
        items.append(Text(cx, strip_top + 4.7, label, 2.6, L_TEXT, RED,
                          anchor='middle' if i != 2 else 'start'))

    body_mid = (head_bottom + bottom) / 2.0 + 1.0
    c0 = (col_x[0] + col_x[1]) / 2
    if settings.drawing_title:
        items.append(Text(c0, body_mid - 2.0, settings.project_name, 3.0, anchor='middle'))
        items.append(Text(c0, body_mid + 3.2, settings.drawing_title, 2.3, L_TEXT, GREY, anchor='middle'))
    else:
        items.append(Text(c0, body_mid, settings.project_name, 3.0, anchor='middle'))
    items.append(Text((col_x[1] + col_x[2]) / 2, body_mid, settings.client, 3.0, anchor='middle'))
    items.append(Text((col_x[4] + col_x[5]) / 2, body_mid, settings.drawn_by, 3.0, anchor='middle'))

    sw = settings.swatches
    if sw:
        box, gap = 12.0, 3.0
        n = min(len(sw), 5)
        if n > 4:
            box, gap = 9.5, 2.5
        sx = col_x[3] + 4.0
        sy = head_bottom + 3.5
        for name, color in sw[:n]:
            rgb = tuple(color[:3])
            items.append(Fill(sx, sy, box, box, rgb))
            light = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] > 0.6
            items.append(Text(sx + box / 2, sy + box + 3.2, name, 1.5, L_TEXT,
                              GREY if light else rgb, bold=True, anchor='middle'))
            sx += box + gap

    notes = [n for n in settings.notes if n.strip()]
    notes.append("SCALE 1:%d ON %s." % (scale, settings.paper))
    ny = head_bottom + 5.0
    size = 2.4 if len(notes) <= 4 else 1.9
    step = (bottom - head_bottom - 4.0) / max(len(notes), 4)
    for i, note in enumerate(notes[:7]):
        items.append(Text(col_x[2] + 5.0, ny + i * step, "%d." % (i + 1), size))
        items.append(Text(col_x[2] + 12.0, ny + i * step, note, size))


def _pictures(items, pics, area_left, area_top, area_bottom, col_w):
    slot_h = (area_bottom - area_top - 6.0 * (len(pics) - 1)) / len(pics)
    slot_h = min(slot_h, col_w * 0.75)
    used = slot_h * len(pics) + 6.0 * (len(pics) - 1)
    py = area_top + (area_bottom - area_top - used) / 2.0
    for path, iw, ih in pics:
        aspect = iw / ih if ih else 1.0
        w, h = col_w, col_w / aspect
        if h > slot_h:
            h, w = slot_h, slot_h * aspect
        items.append(Picture(path, area_left + (col_w - w) / 2.0, py + (slot_h - h) / 2.0, w, h))
        py += slot_h + 6.0


def _chain(items, pairs, texts, size):
    """Add a chain of dimensions; text that is wider than its gap drops below
    the line, alternating between two rows so neighbours do not collide."""
    from .export_pdf import text_width
    row = 0
    for (p0, p1, a, b), text in zip(pairs, texts):
        gap = math.hypot(b[0] - a[0], b[1] - a[1])
        if text_width(text, size) + 1.0 <= gap:
            level, row = 0, 0
        else:
            row = 2 if row == 1 else 1
            level = row
        items.append(Dim(p0, p1, a, b, text, size, text_level=level))


def _view_dimensions(items, pl, settings):
    v, k, fmt, size = pl.view, pl.k, settings.fmt, settings.dim_text_size
    vd = D.compute(v, fmt, k, size, settings.detail, settings.forced_parts, settings.radii)

    # Horizontal: chain just below the view, overall below the chain.
    level = 1
    y_edge = pl.bottom
    if len(vd.x_chain) > 2:
        y = y_edge + DIM_STEP * level
        pairs, texts = [], []
        for x0, x1 in zip(vd.x_chain[:-1], vd.x_chain[1:]):
            p0, p1 = pl.to_paper(x0, v.min_y), pl.to_paper(x1, v.min_y)
            pairs.append((p0, p1, (p0[0], y), (p1[0], y)))
            texts.append(fmt.text(x1 - x0))
        _chain(items, pairs, texts, size)
        level += 1
    y = y_edge + DIM_STEP * level
    p0, p1 = pl.to_paper(v.min_x, v.min_y), pl.to_paper(v.max_x, v.min_y)
    items.append(Dim(p0, p1, (p0[0], y), (p1[0], y), fmt.text(v.width), size))

    # Vertical: chain just left of the view, overall left of the chain.
    level = 1
    if len(vd.y_chain) > 2:
        x = pl.x - DIM_STEP * level
        pairs, texts = [], []
        for y0, y1 in zip(vd.y_chain[:-1], vd.y_chain[1:]):
            p0, p1 = pl.to_paper(v.min_x, y0), pl.to_paper(v.min_x, y1)
            pairs.append((p0, p1, (x, p0[1]), (x, p1[1])))
            texts.append(fmt.text(y1 - y0))
        _chain(items, pairs, texts, size)
        level += 1
    x = pl.x - DIM_STEP * level
    p0, p1 = pl.to_paper(v.min_x, v.min_y), pl.to_paper(v.min_x, v.max_y)
    items.append(Dim(p0, p1, (x, p0[1]), (x, p1[1]), fmt.text(v.height), size))

    # Radii: a short leader pointing at the arc, away from its centre.
    cx_view = (v.min_x + v.max_x) / 2.0
    for arc in vd.arcs:
        mx, my = arc.mid_point()
        tip = pl.to_paper(mx, my)
        dx, dy = mx - arc.cx, -(my - arc.cy)          # paper y points down
        length = math.hypot(dx, dy) or 1.0
        dx, dy = dx / length, dy / length
        elbow = (tip[0] + dx * 7.0, tip[1] + dy * 7.0)
        side = 1.0 if (dx > 0 or (dx == 0 and mx >= cx_view)) else -1.0
        end = (elbow[0] + side * 2.5, elbow[1])
        label = ("Ø" + fmt.number(arc.r * 2.0)) if arc.full else ("R" + fmt.number(arc.r))
        items.append(Leader([tip, elbow, end], label, size, L_DIMS,
                            anchor='start' if side > 0 else 'end'))


def _view_notes(items, pl, notes, size):
    """Leaders from parts to note text stacked on the right of the view."""
    if not notes:
        return
    v = pl.view
    merged = {}
    boxes = {name: v.parts[name] for name, _ in notes}

    def area(bx):
        return (bx[2] - bx[0]) * (bx[3] - bx[1])

    for obj_name, text in notes:
        box = boxes[obj_name]
        # Point at the middle of the part, unless a smaller noted part sits
        # there; then pick a spot on this part that is clear of it.
        smaller = [bx for n, bx in boxes.items() if n != obj_name and area(bx) < area(box)]
        spot = None
        for fx, fy in ((0.5, 0.5), (0.8, 0.5), (0.8, 0.8), (0.8, 0.2), (0.5, 0.8), (0.5, 0.2), (0.2, 0.5)):
            x = box[0] + (box[2] - box[0]) * fx
            y = box[1] + (box[3] - box[1]) * fy
            if not any(bx[0] <= x <= bx[2] and bx[1] <= y <= bx[3] for bx in smaller):
                spot = (x, y)
                break
        if spot is None:
            spot = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        anchor = pl.to_paper(*spot)
        # One callout per distinct text; point at the part nearest the text column.
        if text not in merged or anchor[0] > merged[text][0]:
            merged[text] = anchor
    entries = sorted(merged.items(), key=lambda kv: kv[1][1])
    x_text = pl.right + NOTE_GAP
    step = size * 1.9
    ys = []
    for _text, anchor in entries:
        y = anchor[1] if not ys else max(anchor[1], ys[-1] + step)
        ys.append(y)
    # Keep the stack inside the view's height where possible.
    overflow = ys[-1] - pl.bottom if ys else 0.0
    if overflow > 0:
        ys = [max(pl.y, y - overflow) for y in ys]
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i - 1] + step)
    for (text, anchor), y in zip(entries, ys):
        items.append(Leader([anchor, (x_text - 3.0, y), (x_text, y)], text, size, L_NOTES))


def build_sheet(views, settings):
    """Lay out `views` ({name: engine.View}) on one sheet."""
    from .export_pdf import text_width

    if settings.fmt is None:
        settings.fmt = D.Format()
    pw, ph = PAPER_SIZES[settings.paper]
    items = []

    left, right = MARGIN, pw - MARGIN
    top, bottom = MARGIN, ph - MARGIN
    strip_top = bottom - STRIP_H
    items.append(Line([(left, top), (right, top), (right, bottom), (left, bottom)],
                      L_FRAME, FRAME_GREY, 0.25, closed=True))

    area_left = left + 4.0
    area_top = top + 4.0
    area_bottom = strip_top - 4.0
    pics = settings.pictures[:3]
    if pics:
        col_w = (right - left) * 0.28
        _pictures(items, pics, area_left, area_top, area_bottom, col_w)
        area_left += col_w + 6.0

    # Space each view needs around it: (left, right, top, bottom) in paper mm.
    notes_by_view = _assign_notes(views, settings.object_notes)
    size = settings.dim_text_size
    margins = {}
    for name in views:
        dim_room = DIM_STEP * 2 + size + 2.0 if settings.dimensions else 2.0
        note_room = 3.0
        if notes_by_view[name]:
            note_room = NOTE_GAP + 2.0 + max(text_width(t, size) for _, t in notes_by_view[name])
        margins[name] = (dim_room, note_room, LABEL_H, dim_room)

    avail_w = right - area_left - 4.0
    avail_h = area_bottom - area_top
    scale, rows = _choose_layout(views, avail_w, avail_h, margins)
    k = 1000.0 / scale
    block_w, block_h = _block_size(rows, views, k, margins)
    bx = area_left + (avail_w - block_w) / 2.0
    by = area_top + (avail_h - block_h) / 2.0

    placements = {}
    y = by
    for row in rows:
        row_h = max(views[n].height * k for n in row)
        row_top = max(margins[n][2] for n in row)
        row_bottom = max(margins[n][3] for n in row)
        x = bx
        for name in row:
            v = views[name]
            ml, mr, _mt, _mb = margins[name]
            # Views in a row share a ground line (bottom aligned).
            vy = y + row_top + (row_h - v.height * k)
            placements[name] = Placement(v, x + ml, vy, k)
            items.append(Text(x + ml, vy - 3.2, v.label, 2.5, L_TEXT, RED, bold=True))
            x += ml + v.width * k + mr + CELL_GAP
        y += row_top + row_h + row_bottom + CELL_GAP

    for name, pl in placements.items():
        v = pl.view
        if settings.hidden_lines:
            for poly in cleanup.chain(cleanup.clean_segments(v.hidden)):
                items.append(Line([pl.to_paper(px, py_) for px, py_ in poly],
                                  L_HIDDEN, GREY, 0.09, dash=(1.2, 0.8)))
        for poly in cleanup.chain(cleanup.clean_segments(v.polylines)):
            items.append(Line([pl.to_paper(px, py_) for px, py_ in poly], L_VISIBLE, BLACK, 0.13))
        for colour, polys in v.lights:
            for poly in cleanup.chain(cleanup.clean_segments(polys)):
                items.append(Line([pl.to_paper(px, py_) for px, py_ in poly], L_LIGHTS, colour, 0.25))
        if settings.dimensions:
            _view_dimensions(items, pl, settings)
        _view_notes(items, pl, notes_by_view[name], size)

    _strip(items, settings, left, right, bottom, strip_top, scale)
    return Sheet(pw, ph, items, placements, scale, settings.drawing_title, settings.fmt)
