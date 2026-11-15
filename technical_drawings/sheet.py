"""Sheet layout: places views, pictures and the bottom information strip on paper.

Produces a flat list of drawing items in paper millimetres (origin top-left,
y down) that every exporter (PDF, SVG, DXF) consumes, so all file formats
show the same sheet.
"""

from dataclasses import dataclass, field

PAPER_SIZES = {          # landscape, millimetres
    'A4': (297.0, 210.0),
    'A3': (420.0, 297.0),
    'A2': (594.0, 420.0),
    'A1': (841.0, 594.0),
    'A0': (1189.0, 841.0),
}

SCALES = [1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 500, 1000]

RED = (0.816, 0.125, 0.165)
BLACK = (0.0, 0.0, 0.0)
GREY = (0.45, 0.45, 0.45)
FRAME_GREY = (0.55, 0.55, 0.55)

# Layer names are shared by SVG groups and DXF layers.
L_FRAME = "FRAME"
L_VISIBLE = "VISIBLE"
L_HIDDEN = "HIDDEN"
L_TEXT = "TEXT"
L_DIMS = "DIMENSIONS"
L_PICTURES = "PICTURES"


@dataclass
class Line:
    points: list                 # [(x, y), ...] paper mm
    layer: str = L_VISIBLE
    color: tuple = BLACK
    width: float = 0.18          # mm
    dash: tuple = ()             # mm on/off
    closed: bool = False


@dataclass
class Text:
    x: float
    y: float                     # baseline
    text: str
    size: float = 2.8            # cap-ish height driver, in mm (font size)
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
class SheetSettings:
    paper: str = 'A3'
    project_name: str = ""
    client: str = ""
    drawing_title: str = ""
    drawn_by: str = ""
    notes: list = field(default_factory=list)       # list of str
    swatches: list = field(default_factory=list)    # list of (name, (r,g,b))
    pictures: list = field(default_factory=list)    # list of (path, pixel_w, pixel_h)
    unit_label: str = "CENTIMETERS"
    hidden_lines: bool = False


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


@dataclass
class Sheet:
    width: float
    height: float
    items: list
    placements: dict
    scale: int
    title: str


MARGIN = 8.0
STRIP_H = 30.0
STRIP_HEAD_H = 7.0
VIEW_GAP = 26.0          # paper mm between views (room for labels and dimensions)
VIEW_PAD = 16.0          # paper mm kept clear around the view block
LABEL_H = 7.0


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


def _block_size(rows, views, k):
    """Paper size (mm) of an arrangement at k mm per metre."""
    widths, heights = [], []
    for row in rows:
        w = sum(views[n].width * k for n in row) + VIEW_GAP * (len(row) - 1)
        h = max(views[n].height * k for n in row) + LABEL_H
        widths.append(w)
        heights.append(h)
    return max(widths), sum(heights) + VIEW_GAP * (len(rows) - 1)


def _choose_layout(views, avail_w, avail_h):
    best = None
    for rows in _arrangements(views):
        for scale in SCALES:
            k = 1000.0 / scale
            w, h = _block_size(rows, views, k)
            if w <= avail_w and h <= avail_h:
                if best is None or scale < best[0]:
                    best = (scale, rows)
                break
    if best is None:
        best = (SCALES[-1], _arrangements(views)[0])
    return best


def build_sheet(views, settings):
    """Lay out `views` ({name: engine.View}) on one sheet."""
    pw, ph = PAPER_SIZES[settings.paper]
    items = []

    left, right = MARGIN, pw - MARGIN
    top, bottom = MARGIN, ph - MARGIN
    strip_top = bottom - STRIP_H

    # Frame: outer border and the information strip.
    items.append(Line([(left, top), (right, top), (right, bottom), (left, bottom)],
                      L_FRAME, FRAME_GREY, 0.25, closed=True))
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
    if settings.drawing_title:
        items.append(Text((col_x[0] + col_x[1]) / 2, body_mid - 2.0, settings.project_name, 3.0, anchor='middle'))
        items.append(Text((col_x[0] + col_x[1]) / 2, body_mid + 3.2, settings.drawing_title, 2.3,
                          L_TEXT, GREY, anchor='middle'))
    else:
        items.append(Text((col_x[0] + col_x[1]) / 2, body_mid, settings.project_name, 3.0, anchor='middle'))
    items.append(Text((col_x[1] + col_x[2]) / 2, body_mid, settings.client, 3.0, anchor='middle'))
    items.append(Text((col_x[4] + col_x[5]) / 2, body_mid, settings.drawn_by, 3.0, anchor='middle'))

    # Pantone swatches.
    sw = settings.swatches
    if sw:
        box = 12.0
        gap = 3.0
        n = min(len(sw), 5)
        if n > 4:
            box, gap = 9.5, 2.5
        sx = col_x[3] + 4.0
        sy = head_bottom + 3.5
        for name, color in sw[:n]:
            items.append(Fill(sx, sy, box, box, tuple(color[:3])))
            rgb = tuple(color[:3])
            light = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] > 0.6
            items.append(Text(sx + box / 2, sy + box + 3.2, name, 1.5, L_TEXT,
                              GREY if light else rgb, bold=True, anchor='middle'))
            sx += box + gap

    # Pictures column on the left.
    area_left = left + 4.0
    area_top = top + 4.0
    area_bottom = strip_top - 4.0
    pics = settings.pictures[:3]
    if pics:
        col_w = (right - left) * 0.30
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
        area_left += col_w + 6.0

    # Views.
    avail_w = right - area_left - 2 * VIEW_PAD
    avail_h = area_bottom - area_top - 2 * VIEW_PAD
    scale, rows = _choose_layout(views, avail_w, avail_h)
    k = 1000.0 / scale
    block_w, block_h = _block_size(rows, views, k)
    bx = area_left + VIEW_PAD + (avail_w - block_w) / 2.0
    by = area_top + VIEW_PAD + (avail_h - block_h) / 2.0

    placements = {}
    y = by
    for row in rows:
        row_h = max(views[n].height * k for n in row)
        x = bx
        for name in row:
            v = views[name]
            # Views in a row share a ground line (bottom aligned).
            vy = y + LABEL_H + (row_h - v.height * k)
            placements[name] = Placement(v, x, vy, k)
            items.append(Text(x, vy - 3.2, v.label, 2.5, L_TEXT, RED, bold=True))
            x += v.width * k + VIEW_GAP
        y += LABEL_H + row_h + VIEW_GAP

    for name, pl in placements.items():
        if settings.hidden_lines:
            for poly in pl.view.hidden:
                items.append(Line([pl.to_paper(px, py_) for px, py_ in poly],
                                  L_HIDDEN, GREY, 0.09, dash=(1.2, 0.8)))
        for poly in pl.view.polylines:
            items.append(Line([pl.to_paper(px, py_) for px, py_ in poly], L_VISIBLE, BLACK, 0.13))

    # General notes (numbered), scale appended automatically.
    notes = [n for n in settings.notes if n.strip()]
    notes.append("SCALE 1:%d ON %s." % (scale, settings.paper))
    ny = head_bottom + 5.0
    size = 2.4 if len(notes) <= 4 else 1.9
    step = (bottom - head_bottom - 4.0) / max(len(notes), 4)
    for i, note in enumerate(notes[:7]):
        items.append(Text(col_x[2] + 5.0, ny + i * step, "%d." % (i + 1), size))
        items.append(Text(col_x[2] + 12.0, ny + i * step, note, size))

    return Sheet(pw, ph, items, placements, scale, settings.drawing_title)
