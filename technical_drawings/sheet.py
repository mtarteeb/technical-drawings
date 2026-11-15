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
class Shape:
    """A filled outline with curves (used for the company logo).
    subpaths: lists of ('M', x, y) / ('L', x, y) / ('C', x1, y1, x2, y2, x, y)
    in paper mm; every subpath is closed."""
    subpaths: list
    fill: tuple
    even_odd: bool = False
    layer: str = "FRAME"


def logo_shapes(x, y, width, ink=(0.0, 0.0, 0.0), paper=(1.0, 1.0, 1.0)):
    """The company logo placed with its top-left corner at (x, y)."""
    from . import logo_data
    out = []
    for kind, even_odd, subs in logo_data.SHAPES:
        placed = []
        for sub in subs:
            cmds = []
            for c in sub:
                vals = list(c[1:])
                for i in range(0, len(vals), 2):
                    vals[i] = x + vals[i] * width
                    vals[i + 1] = y + vals[i + 1] * width
                cmds.append((c[0],) + tuple(vals))
            placed.append(cmds)
        out.append(Shape(placed, ink if kind == 'ink' else paper, even_odd))
    return out


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
    text_level: int = 0          # 0 = on the line; -1 = a second row further out; 1, 2 = on the other side
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
        if self.text_level <= 0:
            off = self.size * (0.32 + 1.15 * -self.text_level)
        else:
            off = -self.size * (0.95 + 1.1 * (self.text_level - 1))
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
    if d.text_level == 0 and abs(d.text_shift) > 0.5:
        # Text sits outside the gap: carry the dimension line on underneath it.
        from .export_pdf import text_width
        half = text_width(d.text, d.size, d.bold) / 2.0 + 0.6
        side = 1.0 if d.text_shift > 0 else -1.0
        cx = (ax + bx) / 2.0 + ux * length * d.text_shift
        cy = (ay + by) / 2.0 + uy * length * d.text_shift
        near = ((ax + bx) / 2.0 + ux * side * length / 2.0, (ay + by) / 2.0 + uy * side * length / 2.0)
        out.append(Line([near, (cx + ux * side * half, cy + uy * side * half)], d.layer, d.color, d.width))
    if d.text_level:
        # The text is not on its own gap: tie it back with a short line.
        reach = -0.12 if d.text_level < 0 else 0.8
        out.append(Line([((ax + bx) / 2.0, (ay + by) / 2.0),
                         (tx + nx * d.size * reach, ty + ny * d.size * reach)],
                        d.layer, d.color, d.width))
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
    logo: bool = True                                   # company logo in the title block
    layout: str = 'TEMPLATE'                            # TEMPLATE = company title block, STRIP = bottom strip
    checked_by: str = ""
    approved_by: str = ""
    date: str = ""
    architect: str = ""
    project_no: str = ""
    drawing_no: str = ""
    revision_no: str = ""
    dim_text_size: float = 12.0 * 25.4 / 72.0           # dimension text: 12 pt on paper, at any scale
    fit: str = 'ONE'                                    # ONE = one sheet, PAPER = bigger paper, SHEETS = split views


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
    paper: str = 'A3'
    text_size: float = 12.0 * 25.4 / 72.0
    number: int = 1
    count: int = 1


MARGIN = 8.0
STRIP_H = 30.0
STRIP_HEAD_H = 7.0
CELL_GAP = 8.0           # paper mm between view cells
LABEL_H = 7.0
NOTE_GAP = 9.0           # view edge to the note text
PAPER_ORDER = ['A4', 'A3', 'A2', 'A1', 'A0']


def _dim_step(size):
    """Distance between dimension levels; leaves room for two rows of text."""
    return size * 3.0


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


def _choose_layout(views, avail_w, avail_h, margins, min_scale=1):
    best = None
    for rows in _arrangements(views):
        for scale in SCALES:
            if scale < min_scale:
                continue
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


def _strip(items, settings, left, right, bottom, strip_top, scale, paper, number, count):
    items.append(Line([(left, strip_top), (right, strip_top)], L_FRAME, FRAME_GREY, 0.25))
    head_bottom = strip_top + STRIP_HEAD_H
    items.append(Line([(left, head_bottom), (right, head_bottom)], L_FRAME, FRAME_GREY, 0.18))
    total = right - left
    if settings.logo:
        fractions = [("Project Name", 0.118), ("Client", 0.150), ("General  Notes", 0.322),
                     ("Pantone Color Code", 0.172), ("Drawing By", 0.112), ("Company", 0.126)]
    else:
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
    if settings.logo:
        from . import logo_data
        box_w, box_h = col_x[6] - col_x[5], bottom - head_bottom
        logo_w = min(box_w - 8.0, (box_h - 8.0) / logo_data.ASPECT)
        logo_h = logo_w * logo_data.ASPECT
        items.extend(logo_shapes(col_x[5] + (box_w - logo_w) / 2.0,
                                 head_bottom + (box_h - logo_h) / 2.0, logo_w))

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
    notes.append("SCALE 1:%d ON %s." % (scale, paper))
    if count > 1:
        notes.append("SHEET %d OF %d." % (number, count))
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


def _chain(items, pairs, texts, size, start_outside=True, outer_level=1):
    """Add a chain of dimensions (or a single one).

    Text that is wider than its gap is never dropped. At either end of the
    chain it moves outside, beside the gap, on an extended dimension line
    (normal drafting practice). In the middle of a chain it moves to a second
    row further out, tied to its gap by a short line, and slides along until
    it is clear of its neighbours.
    """
    from .export_pdf import text_width
    if not pairs:
        return
    a0, b_last = pairs[0][2], pairs[-1][3]
    total = math.hypot(b_last[0] - a0[0], b_last[1] - a0[1]) or 1.0
    ux, uy = (b_last[0] - a0[0]) / total, (b_last[1] - a0[1]) / total
    if ux < -1e-9 or (abs(ux) <= 1e-9 and uy > 0):       # reading direction, as in Dim.text_position
        ux, uy = -ux, -uy

    def along(p):
        return (p[0] - a0[0]) * ux + (p[1] - a0[1]) * uy

    order = sorted(zip(pairs, texts), key=lambda e: along(e[0][2]) + along(e[0][3]))
    cursor = None            # end of the last text placed on the second row
    last = len(order) - 1
    for i, ((p0, p1, a, b), text) in enumerate(order):
        lo, hi = sorted((along(a), along(b)))
        gap, mid = hi - lo, (lo + hi) / 2.0
        width = text_width(text, size)
        if width + 1.0 <= gap or gap <= 1e-9:
            items.append(Dim(p0, p1, a, b, text, size))
            continue
        if i == last:
            centre, level = hi + 1.6 + width / 2.0, 0
        elif i == 0 and start_outside:
            centre, level = lo - 1.6 - width / 2.0, 0
        else:
            centre = mid if cursor is None else max(mid, cursor + width / 2.0 + 1.2)
            cursor = centre + width / 2.0
            level = outer_level          # the row on the side away from the view
        items.append(Dim(p0, p1, a, b, text, size, text_level=level, text_shift=(centre - mid) / gap))


def _fits(text, size, gap):
    from .export_pdf import text_width
    return text_width(text, size) + 1.0 <= gap


def _view_dimensions(items, pl, settings):
    v, k, fmt, size = pl.view, pl.k, settings.fmt, settings.dim_text_size
    vd = D.compute(v, fmt, k, size, settings.detail, settings.forced_parts, settings.radii)

    DIM_STEP = _dim_step(size)
    x_gaps = list(zip(vd.x_chain[:-1], vd.x_chain[1:])) if len(vd.x_chain) > 2 else []
    y_gaps = list(zip(vd.y_chain[:-1], vd.y_chain[1:])) if len(vd.y_chain) > 2 else []
    # Both chains start at the bottom-left corner. If both begin with a gap too
    # small for its text, only the vertical one moves its text outside there.
    y_first_small = bool(y_gaps) and not _fits(fmt.text(y_gaps[0][1] - y_gaps[0][0]), size,
                                               (y_gaps[0][1] - y_gaps[0][0]) * k)

    # Horizontal: chain just below the view, overall below the chain.
    level = 1
    if x_gaps:
        y = pl.bottom + DIM_STEP * level
        pairs = []
        for x0, x1 in x_gaps:
            p0, p1 = pl.to_paper(x0, v.min_y), pl.to_paper(x1, v.min_y)
            pairs.append((p0, p1, (p0[0], y), (p1[0], y)))
        _chain(items, pairs, [fmt.text(x1 - x0) for x0, x1 in x_gaps], size,
               start_outside=not y_first_small)
        level += 1
    y = pl.bottom + DIM_STEP * level
    p0, p1 = pl.to_paper(v.min_x, v.min_y), pl.to_paper(v.max_x, v.min_y)
    _chain(items, [(p0, p1, (p0[0], y), (p1[0], y))], [fmt.text(v.width)], size)

    # Vertical: chain just left of the view, overall left of the chain.
    level = 1
    if y_gaps:
        x = pl.x - DIM_STEP * level
        pairs = []
        for y0, y1 in y_gaps:
            p0, p1 = pl.to_paper(v.min_x, y0), pl.to_paper(v.min_x, y1)
            pairs.append((p0, p1, (x, p0[1]), (x, p1[1])))
        _chain(items, pairs, [fmt.text(y1 - y0) for y0, y1 in y_gaps], size, outer_level=-1)
        level += 1
    x = pl.x - DIM_STEP * level
    p0, p1 = pl.to_paper(v.min_x, v.min_y), pl.to_paper(v.min_x, v.max_y)
    _chain(items, [(p0, p1, (x, p0[1]), (x, p1[1]))], [fmt.text(v.height)], size)

    # Angled edges: true length along the edge, and the angle from the horizontal.
    centre = ((pl.x + pl.right) / 2.0, (pl.y + pl.bottom) / 2.0)
    angles_shown = set()
    for x0, y0, x1, y1, length, slope in vd.slanted:
        p0, p1 = pl.to_paper(x0, y0), pl.to_paper(x1, y1)          # p0 is the lower end
        ex, ey = p1[0] - p0[0], p1[1] - p0[1]
        plen = math.hypot(ex, ey) or 1.0
        ex, ey = ex / plen, ey / plen
        nx, ny = -ey, ex
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        if (mid[0] - centre[0]) * nx + (mid[1] - centre[1]) * ny < 0:      # push away from the view
            nx, ny = -nx, -ny
        degrees = round(math.degrees(slope))
        show_angle = degrees not in angles_shown
        angles_shown.add(degrees)
        radius = max(size * 1.6, min(size * 2.4, plen * 0.55))
        # The length sits outside the angle arc, so the two never overlap.
        off = radius + size * 1.3 if show_angle else size * 1.5
        items.append(Dim(p0, p1, (p0[0] + nx * off, p0[1] + ny * off),
                         (p1[0] + nx * off, p1[1] + ny * off), fmt.text(length), size))
        if not show_angle:
            continue
        # Angle from the horizontal: a reference line, an arc and the value,
        # at the end of the edge where the angle opens to the outside.
        a = slope / 2.0
        chosen = None
        for vertex, towards in ((p0, 1.0), (p1, -1.0)):      # towards: along the edge, away from this end
            side = 1.0 if ex * towards >= 0 else -1.0        # horizontal direction of the reference line
            up = -1.0 if ey * towards < 0 else 1.0           # the edge leaves this end upwards (-1) or downwards (+1)
            facing = side * math.cos(a) * nx + up * math.sin(a) * ny
            if chosen is None or facing > chosen[0]:
                chosen = (facing, vertex, side, up)
        _, vertex, side, up = chosen
        items.append(Line([vertex, (vertex[0] + side * radius * 1.25, vertex[1])], L_DIMS, DIM_GREY, 0.10))
        steps = max(4, int(degrees / 6.0))
        items.append(Line([(vertex[0] + side * radius * math.cos(slope * i / steps),
                            vertex[1] + up * radius * math.sin(slope * i / steps))
                           for i in range(steps + 1)], L_DIMS, DIM_GREY, 0.10))
        label_r = radius * 0.62
        items.append(Text(vertex[0] + side * label_r * math.cos(a),
                          vertex[1] + up * label_r * math.sin(a) + size * 0.28,
                          "%d\u00b0" % degrees, size * 0.7, L_DIMS, DIM_GREY, anchor='middle'))

    # Radii: a short leader pointing at the arc, away from its centre.
    cx_view = (v.min_x + v.max_x) / 2.0
    placed_labels = []
    for arc in vd.arcs:
        mx, my = arc.mid_point()
        tip = pl.to_paper(mx, my)
        dx, dy = mx - arc.cx, -(my - arc.cy)          # paper y points down
        length = math.hypot(dx, dy) or 1.0
        dx, dy = dx / length, dy / length
        elbow = (tip[0] + dx * size * 2.6, tip[1] + dy * size * 2.6)
        side = 1.0 if (dx > 0 or (dx == 0 and mx >= cx_view)) else -1.0
        # Keep radius labels from landing on top of each other.
        for _ in range(8):
            if all(abs(elbow[1] - py) >= size * 1.15 or abs(elbow[0] - px) >= size * 6.0
                   for px, py in placed_labels):
                break
            elbow = (elbow[0], elbow[1] - size * 1.2)
        placed_labels.append(elbow)
        end = (elbow[0] + side * size, elbow[1])
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


def _wrap(text, size, width):
    """Break text into lines no wider than `width`."""
    from .export_pdf import text_width
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if line and text_width(trial, size) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


# Title block of the company template, in millimetres on A3 (scaled for other sizes).
_LABELS = [            # text, x, baseline y, font size
    ("GENERAL NOTES", 364.4, 16.8, 2.5), ("PROJECT NAME:", 363.0, 126.4, 2.5),
    ("DRAWING TITLE:", 363.0, 139.5, 2.5), ("DRAWN BY:", 363.0, 153.7, 2.5),
    ("CHECKED BY:", 387.6, 153.7, 2.5), ("APPROVED BY:", 362.8, 164.9, 2.5),
    ("DATE:", 387.5, 164.9, 2.5), ("COMPANY NAME:", 362.9, 177.8, 2.5),
    ("ARCHITECT:", 362.8, 212.3, 2.5), ("PROJECT NO:", 362.9, 245.7, 1.67),
    ("SCALE", 388.4, 245.7, 1.67), ("SHEET SIZE", 399.2, 245.7, 1.67),
    ("DRAWING NO:", 362.9, 256.9, 1.67), ("SHEET NO:", 387.7, 256.9, 1.67),
    ("REVISION NO:", 362.9, 268.3, 1.67), ("UNIT:", 362.9, 279.4, 1.67),
]
_UNIT_WORDS = {'CM': "CENTIMETER", 'MM': "MILLIMETER", 'M': "METER", 'IN': "INCH"}


def _title_block(items, settings, paper, scale, number, count):
    """The company title block down the right-hand side of the sheet."""
    from . import template_data
    from .export_pdf import text_width
    f = PAPER_SIZES[paper][0] / 420.0

    def fit(text, size, width):
        """Shrink text that is too wide for its box."""
        w = text_width(text, size)
        return size if w <= width or not text else size * width / w

    for i, outline in enumerate(template_data.FRAME):
        items.append(Line([(x * f, y * f) for x, y in outline], L_FRAME, BLACK,
                          0.35 if i == 0 else 0.18, closed=True))
    for part in template_data.COMPASS:
        if part[0] == 'fill':
            subs = [[(c[0],) + tuple(v * f for v in c[1:]) for c in sub] for sub in part[2]]
            items.append(Shape(subs, part[1]))
        else:
            items.append(Line([(x * f, y * f) for x, y in part[2]], L_FRAME, part[1], 0.18, closed=part[3]))
    for text, x, y, size in _LABELS:
        items.append(Text(x * f, y * f, text, size * f, L_TEXT, BLACK))

    def value(text, cx, y, size, width):
        if text:
            size = fit(text, size * f, width * f)
            items.append(Text(cx * f, y * f, text, size, L_TEXT, BLACK, anchor='middle'))

    value(settings.project_name.upper(), 385.0, 131.3, 4.5, 44.0)
    value(settings.drawing_title.upper(), 385.0, 144.9, 3.2, 44.0)
    value(settings.drawn_by, 372.5, 158.0, 2.4, 20.0)
    value(settings.checked_by, 397.5, 158.0, 2.4, 20.0)
    value(settings.approved_by, 372.5, 169.2, 2.4, 20.0)
    value(settings.date, 397.5, 169.2, 2.4, 20.0)
    value(settings.project_no, 372.5, 250.4, 2.4, 20.0)
    value("1:%d" % scale, 391.25, 250.4, 2.2, 8.5)
    value(paper, 403.75, 250.6, 3.4, 8.5)
    value(settings.drawing_no, 372.5, 261.6, 2.4, 20.0)
    value("%d OF %d" % (number, count), 397.5, 261.6, 2.0, 20.0)
    value(settings.revision_no, 372.5, 273.0, 2.4, 20.0)
    value(_UNIT_WORDS.get(settings.fmt.unit, ""), 372.5, 282.5, 2.1, 20.0)

    # Architect: wrapped text inside its box.
    y = 219.0
    for line in _wrap(settings.architect, 2.6, 43.0)[:5]:
        items.append(Text(385.0 * f, y * f, line, 2.6 * f, L_TEXT, BLACK, anchor='middle'))
        y += 4.0

    if settings.logo:
        items.extend(logo_shapes(372.3 * f, 186.8 * f, 26.1 * f))

    # General notes: numbered and wrapped inside the notes box.
    notes = [n.strip() for n in settings.notes if n.strip()]
    size, y = 2.2, 23.0
    for i, note in enumerate(notes):
        lines = _wrap(note, size, 38.0)
        if y + len(lines) * 3.3 > 104.0:
            break
        items.append(Text(364.4 * f, y * f, "%d." % (i + 1), size * f, L_TEXT, BLACK))
        for line in lines:
            items.append(Text(369.0 * f, y * f, line, size * f, L_TEXT, BLACK))
            y += 3.3
        y += 1.5

    # Pantone swatches sit at the bottom of the notes box.
    sw = settings.swatches[:4]
    if sw:
        box, gap = 8.0, 3.2
        sx = 385.0 - (len(sw) * box + (len(sw) - 1) * gap) / 2.0
        for name, color in sw:
            rgb = tuple(color[:3])
            items.append(Fill(sx * f, 106.0 * f, box * f, box * f, rgb))
            light = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] > 0.6
            items.append(Text((sx + box / 2) * f, 117.3 * f, name, fit(name, 1.4 * f, (box + gap - 0.6) * f),
                              L_TEXT, GREY if light else rgb, bold=True, anchor='middle'))
            sx += box + gap


def _areas(paper, has_pictures, layout='TEMPLATE'):
    pw, ph = PAPER_SIZES[paper]
    if layout == 'TEMPLATE':
        f = pw / 420.0
        left, right = 8.0 * f, 360.0 * f           # the title block starts at 360 mm on A3
        top, bottom = 8.0 * f, 289.0 * f
        strip_top = bottom
        area_left = left + 4.0
        col_w = (right - left) * 0.28 if has_pictures else 0.0
        views_left = area_left + (col_w + 6.0 if has_pictures else 0.0)
        return dict(pw=pw, ph=ph, left=left, right=right, top=top, bottom=bottom, strip_top=strip_top,
                    area_left=area_left, area_top=top + 4.0, area_bottom=bottom - 4.0,
                    col_w=col_w, views_left=views_left)
    left, right = MARGIN, pw - MARGIN
    top, bottom = MARGIN, ph - MARGIN
    strip_top = bottom - STRIP_H
    area_left = left + 4.0
    col_w = (right - left) * 0.28 if has_pictures else 0.0
    views_left = area_left + (col_w + 6.0 if has_pictures else 0.0)
    return dict(pw=pw, ph=ph, left=left, right=right, top=top, bottom=bottom, strip_top=strip_top,
                area_left=area_left, area_top=top + 4.0, area_bottom=strip_top - 4.0,
                col_w=col_w, views_left=views_left)


def _margins(views, settings, notes_by_view):
    """Space each view needs around it: (left, right, top, bottom) in paper mm."""
    from .export_pdf import text_width
    size = settings.dim_text_size
    step = _dim_step(size)
    out = {}
    for name in views:
        dim_room = step * 2 + size + 2.0 if settings.dimensions else 2.0
        note_room = 3.0
        if notes_by_view[name]:
            note_room = NOTE_GAP + 2.0 + max(text_width(t, size) for _, t in notes_by_view[name])
        # Top: the view label, plus room for a narrow gap's text placed past the chain end.
        top_room = LABEL_H + size * 0.6 + (size * 2.6 if settings.dimensions else 0.0)
        out[name] = (dim_room, note_room, top_room, dim_room)
    return out


def _fit_scale(views, paper, has_pictures, margins, layout='TEMPLATE'):
    a = _areas(paper, has_pictures, layout)
    avail_w = a['right'] - a['views_left'] - 4.0
    avail_h = a['area_bottom'] - a['area_top']
    best = None
    for rows in _arrangements(views):          # the largest drawing any arrangement allows
        for scale in SCALES:
            w, h = _block_size(rows, views, 1000.0 / scale, margins)
            if w <= avail_w and h <= avail_h:
                if best is None or scale < best:
                    best = scale
                break
    return best


def _groupings(views):
    """Ways to spread the views over sheets, fewest sheets first."""
    names = [n for n in ('FRONT', 'RIGHT', 'LEFT', 'BACK', 'TOP') if n in views]
    out = [[names]]
    elevations = [n for n in names if n != 'TOP']
    if 'TOP' in names and elevations:
        out.append([elevations, ['TOP']])
    if len(names) > 1 and [[n] for n in names] not in out:
        out.append([[n] for n in names])
    return out


def _plan(views, settings, margins):
    """Decide paper size, how views are spread over sheets, and the scale.

    The dimension text has a fixed size on paper, so the model must be drawn
    large enough for the dimensions to stay readable. When that does not fit
    the chosen paper, views move to more sheets or the paper steps up to the
    next standard size, as the user chose.
    """
    has_pics = bool(settings.pictures)
    wanted = 0.0
    if settings.dimensions:
        wanted = max(D.needed_k(v, settings.fmt, settings.dim_text_size, settings.detail,
                                settings.forced_parts) for v in views.values())
    # Largest scale denominator that still keeps the dimensions readable.
    readable = SCALES[-1]
    if wanted > 0:
        ok = [s for s in SCALES if 1000.0 / s >= wanted]
        readable = ok[-1] if ok else SCALES[0]

    def evaluate(paper, groups):
        worst = 0
        for i, group in enumerate(groups):
            sub = {n: views[n] for n in group}
            s = _fit_scale(sub, paper, has_pics and i == 0, margins, settings.layout)
            if s is None:
                return None
            worst = max(worst, s)
        return worst

    start = PAPER_ORDER.index(settings.paper)
    candidates = []
    if settings.fit == 'ONE':
        candidates.append((settings.paper, _groupings(views)[0]))
    elif settings.fit == 'PAPER':
        for paper in PAPER_ORDER[start:]:
            candidates.append((paper, _groupings(views)[0]))
    else:
        for groups in _groupings(views):
            candidates.append((settings.paper, groups))
    # Take the first candidate that is readable. If none is, take the one with
    # the largest drawing; more sheets or bigger paper are only used when they
    # actually make the drawing larger.
    best = None
    for paper, groups in candidates:
        scale = evaluate(paper, groups)
        if scale is None:
            continue
        # Without reaching "readable", another sheet or paper size is only
        # worth it when the drawing gets clearly larger (more than a quarter).
        if best is None or scale < best[2] * 0.75:
            best = (paper, groups, scale)
        if scale <= readable:
            best = (paper, groups, scale)
            break
    if best is None:
        paper, groups = candidates[-1]
        best = (paper, groups, SCALES[-1])
    return best


def _build_one(views, settings, paper, scale, notes_by_view, margins, pictures, number, count):
    a = _areas(paper, bool(pictures), settings.layout)
    pw, ph = a['pw'], a['ph']
    left, right, top, bottom, strip_top = a['left'], a['right'], a['top'], a['bottom'], a['strip_top']
    template = settings.layout == 'TEMPLATE'
    items = [] if template else [Line([(left, top), (right, top), (right, bottom), (left, bottom)],
                                      L_FRAME, FRAME_GREY, 0.25, closed=True)]
    if pictures:
        _pictures(items, pictures[:3], a['area_left'], a['area_top'], a['area_bottom'], a['col_w'])

    size = settings.dim_text_size
    avail_w = right - a['views_left'] - 4.0
    avail_h = a['area_bottom'] - a['area_top']
    scale, rows = _choose_layout(views, avail_w, avail_h, margins, min_scale=scale)
    k = 1000.0 / scale
    block_w, block_h = _block_size(rows, views, k, margins)
    bx = a['views_left'] + (avail_w - block_w) / 2.0
    by = a['area_top'] + (avail_h - block_h) / 2.0

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
            items.append(Text(x + ml, vy - 3.2, v.label, size * 0.85, L_TEXT, RED, bold=True))
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

    if template:
        _title_block(items, settings, paper, scale, number, count)
    else:
        _strip(items, settings, left, right, bottom, strip_top, scale, paper, number, count)
    return Sheet(pw, ph, items, placements, scale, settings.drawing_title, settings.fmt,
                 paper, size, number, count)


def build_sheets(views, settings):
    """Lay out `views` ({name: engine.View}) on one or more sheets."""
    if settings.fmt is None:
        settings.fmt = D.Format()
    notes_by_view = _assign_notes(views, settings.object_notes)
    margins = _margins(views, settings, notes_by_view)
    paper, groups, scale = _plan(views, settings, margins)
    sheets = []
    for i, group in enumerate(groups):
        sub = {n: views[n] for n in group}
        sheets.append(_build_one(sub, settings, paper, scale, notes_by_view, margins,
                                 settings.pictures if i == 0 else [], i + 1, len(groups)))
    return sheets
