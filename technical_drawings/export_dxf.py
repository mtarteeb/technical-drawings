"""DXF writer (AutoCAD R12 format, pure Python, no dependencies).

The drawing is written at true size in the chosen unit, so a CNC shop can
cut from it and AutoCAD measures real values. Dimensions are real DIMENSION
objects (editable, they re-measure when stretched), text is real TEXT, and
curves that are true arcs are written as ARC / CIRCLE.
"""

import math

import numpy as np

from . import cleanup
from . import sheet as S

LAYERS = [                    # name, colour index, linetype
    (S.L_FRAME, 8, "CONTINUOUS"),
    (S.L_VISIBLE, 7, "CONTINUOUS"),
    (S.L_HIDDEN, 8, "DASHED"),
    (S.L_LIGHTS, 2, "CONTINUOUS"),
    (S.L_TEXT, 7, "CONTINUOUS"),
    (S.L_DIMS, 8, "CONTINUOUS"),
    (S.L_NOTES, 8, "CONTINUOUS"),
    (S.L_PICTURES, 9, "CONTINUOUS"),
    ("CUT", 7, "CONTINUOUS"),
    ("LABELS", 8, "CONTINUOUS"),
]
_ACI = [(1, (1, 0, 0)), (2, (1, 1, 0)), (3, (0, 1, 0)), (4, (0, 1, 1)),
        (5, (0, 0, 1)), (6, (1, 0, 1)), (30, (1, 0.5, 0))]
CAP = 0.72                    # capital letter height as a share of the font size


def _aci(color):
    r, g, b = color[:3]
    hi, lo = max(r, g, b), min(r, g, b)
    if hi - lo < 0.12:
        return 7 if hi < 0.2 else 8
    return min(_ACI, key=lambda e: sum((a - c) ** 2 for a, c in zip(e[1], (r, g, b))))[0]


def _dxf_text(text):
    return (text.replace("Ø", "%%c").replace("°", "%%d")
            .encode('cp1252', 'replace').decode('cp1252'))


class _Writer:
    def __init__(self):
        self.entities = []
        self.blocks = []
        self.min = [float('inf'), float('inf')]
        self.max = [float('-inf'), float('-inf')]

    def _grow(self, x, y):
        self.min[0], self.min[1] = min(self.min[0], x), min(self.min[1], y)
        self.max[0], self.max[1] = max(self.max[0], x), max(self.max[1], y)

    @staticmethod
    def _g(code, value):
        if isinstance(value, float):
            value = ('%.6f' % value).rstrip('0').rstrip('.') or '0'
            if '.' not in value:
                value += '.0'
        return "%3d\n%s\n" % (code, value)

    def _common(self, kind, layer, colour):
        s = self._g(0, kind) + self._g(8, layer)
        if colour is not None:
            s += self._g(62, colour)
        return s

    def line(self, out, p, q, layer, colour=None):
        self._grow(*p)
        self._grow(*q)
        out.append(self._common("LINE", layer, colour) + self._g(10, float(p[0])) + self._g(20, float(p[1]))
                   + self._g(11, float(q[0])) + self._g(21, float(q[1])))

    def polyline(self, out, pts, layer, colour=None, closed=False):
        if len(pts) == 2 and not closed:
            self.line(out, pts[0], pts[1], layer, colour)
            return
        s = self._common("POLYLINE", layer, colour) + self._g(66, 1) + self._g(70, 1 if closed else 0)
        for x, y in pts:
            self._grow(x, y)
            s += self._g(0, "VERTEX") + self._g(8, layer) + self._g(10, float(x)) + self._g(20, float(y))
        out.append(s + self._g(0, "SEQEND") + self._g(8, layer))

    def arc(self, out, arc, layer, colour=None):
        self._grow(arc.cx - arc.r, arc.cy - arc.r)
        self._grow(arc.cx + arc.r, arc.cy + arc.r)
        s = self._common("CIRCLE" if arc.full else "ARC", layer, colour)
        s += self._g(10, float(arc.cx)) + self._g(20, float(arc.cy)) + self._g(40, float(arc.r))
        if not arc.full:
            s += self._g(50, math.degrees(arc.a0) % 360.0) + self._g(51, math.degrees(arc.a1) % 360.0)
        out.append(s)

    def curve(self, out, pts, layer, colour=None, fit_arcs=True):
        """A polyline, with runs that lie on a circle written as true arcs."""
        pts = np.asarray(pts, dtype=np.float64)
        arcs = cleanup.find_arcs(pts) if fit_arcs and len(pts) >= 5 else []
        if not arcs:
            closed = len(pts) > 3 and float(np.hypot(*(pts[0] - pts[-1]))) <= cleanup.SNAP
            self.polyline(out, [tuple(p) for p in (pts[:-1] if closed else pts)], layer, colour, closed)
            return
        cursor = 0
        for a in arcs:
            if a.i0 > cursor:
                self.polyline(out, [tuple(p) for p in pts[cursor:a.i0 + 1]], layer, colour)
            self.arc(out, a, layer, colour)
            cursor = a.i1
        if cursor < len(pts) - 1:
            self.polyline(out, [tuple(p) for p in pts[cursor:]], layer, colour)

    def solid(self, out, pts, layer, colour=None):
        p = list(pts) + [pts[-1]] * (4 - len(pts))
        s = self._common("SOLID", layer, colour)
        for i, (x, y) in enumerate((p[0], p[1], p[3], p[2])):
            self._grow(x, y)
            s += self._g(10 + i, float(x)) + self._g(20 + i, float(y))
        out.append(s)

    def text(self, out, x, y, text, height, layer, colour=None, anchor='start', rotation=0.0):
        self._grow(x, y)
        s = self._common("TEXT", layer, colour) + self._g(10, float(x)) + self._g(20, float(y))
        s += self._g(40, float(height)) + self._g(1, _dxf_text(text)) + self._g(7, "STANDARD")
        if rotation:
            s += self._g(50, float(rotation))
        just = {'start': 0, 'middle': 1, 'end': 2}[anchor]
        if just:
            s += self._g(72, just) + self._g(11, float(x)) + self._g(21, float(y))
        out.append(s)

    def save(self, path, dim_text=2.0, tick=1.0, post="", decimals=1):
        g = self._g
        if self.min[0] == float('inf'):
            self.min, self.max = [0.0, 0.0], [1.0, 1.0]
        w, h = self.max[0] - self.min[0], self.max[1] - self.min[1]
        parts = [g(0, "SECTION"), g(2, "HEADER"),
                 g(9, "$ACADVER"), g(1, "AC1009"),
                 g(9, "$INSBASE"), g(10, 0.0), g(20, 0.0), g(30, 0.0),
                 g(9, "$EXTMIN"), g(10, float(self.min[0])), g(20, float(self.min[1])), g(30, 0.0),
                 g(9, "$EXTMAX"), g(10, float(self.max[0])), g(20, float(self.max[1])), g(30, 0.0),
                 g(9, "$LUNITS"), g(70, 2), g(9, "$LUPREC"), g(70, decimals),
                 g(9, "$DIMSCALE"), g(40, 1.0), g(9, "$DIMLFAC"), g(40, 1.0),
                 g(9, "$DIMTXT"), g(40, float(dim_text)), g(9, "$DIMASZ"), g(40, float(dim_text)),
                 g(9, "$DIMTSZ"), g(40, float(tick)),
                 g(9, "$DIMEXO"), g(40, float(dim_text * 0.5)), g(9, "$DIMEXE"), g(40, float(dim_text * 0.6)),
                 g(9, "$DIMGAP"), g(40, float(dim_text * 0.3)),
                 g(9, "$DIMTAD"), g(70, 1), g(9, "$DIMTIH"), g(70, 0), g(9, "$DIMTOH"), g(70, 0),
                 g(9, "$DIMZIN"), g(70, 8), g(9, "$DIMPOST"), g(1, post),
                 g(0, "ENDSEC"),
                 g(0, "SECTION"), g(2, "TABLES"),
                 g(0, "TABLE"), g(2, "VPORT"), g(70, 1),
                 g(0, "VPORT"), g(2, "*ACTIVE"), g(70, 0),
                 g(10, 0.0), g(20, 0.0), g(11, 1.0), g(21, 1.0),
                 g(12, float(self.min[0] + w / 2)), g(22, float(self.min[1] + h / 2)),
                 g(13, 0.0), g(23, 0.0), g(14, 1.0), g(24, 1.0), g(15, 0.0), g(25, 0.0),
                 g(16, 0.0), g(26, 0.0), g(36, 1.0), g(17, 0.0), g(27, 0.0), g(37, 0.0),
                 g(40, float(max(h, w * 0.6) * 1.05)), g(41, 1.6), g(42, 50.0), g(43, 0.0), g(44, 0.0),
                 g(50, 0.0), g(51, 0.0), g(71, 0), g(72, 100), g(73, 1), g(74, 1), g(75, 0),
                 g(76, 0), g(77, 0), g(78, 0),
                 g(0, "ENDTAB"),
                 g(0, "TABLE"), g(2, "LTYPE"), g(70, 2),
                 g(0, "LTYPE"), g(2, "CONTINUOUS"), g(70, 0), g(3, "Solid line"), g(72, 65), g(73, 0), g(40, 0.0),
                 g(0, "LTYPE"), g(2, "DASHED"), g(70, 0), g(3, "Dashed __ __ __"), g(72, 65), g(73, 2),
                 g(40, float(dim_text * 2.0)), g(49, float(dim_text * 1.25)), g(49, float(-dim_text * 0.75)),
                 g(0, "ENDTAB"),
                 g(0, "TABLE"), g(2, "LAYER"), g(70, len(LAYERS) + 1),
                 g(0, "LAYER"), g(2, "0"), g(70, 0), g(62, 7), g(6, "CONTINUOUS")]
        for name, colour, ltype in LAYERS:
            parts += [g(0, "LAYER"), g(2, name), g(70, 0), g(62, colour), g(6, ltype)]
        parts += [g(0, "ENDTAB"),
                  g(0, "TABLE"), g(2, "STYLE"), g(70, 1),
                  g(0, "STYLE"), g(2, "STANDARD"), g(70, 0), g(40, 0.0), g(41, 1.0), g(50, 0.0), g(71, 0),
                  g(42, float(dim_text)), g(3, "arial.ttf"), g(4, ""),
                  g(0, "ENDTAB"),
                  g(0, "TABLE"), g(2, "DIMSTYLE"), g(70, 1),
                  g(0, "DIMSTYLE"), g(2, "STANDARD"), g(70, 0), g(3, post), g(4, ""),
                  g(5, ""), g(6, ""), g(7, ""),
                  g(40, 1.0), g(41, float(dim_text)), g(42, float(dim_text * 0.5)), g(43, float(dim_text * 3)),
                  g(44, float(dim_text * 0.6)), g(45, 0.0), g(46, 0.0), g(47, 0.0), g(48, 0.0),
                  g(140, float(dim_text)), g(141, float(dim_text * 0.5)), g(142, float(tick)),
                  g(143, 25.4), g(144, 1.0), g(145, 0.0), g(146, 1.0), g(147, float(dim_text * 0.3)),
                  g(71, 0), g(72, 0), g(73, 0), g(74, 0), g(75, 0), g(76, 0), g(77, 1), g(78, 8),
                  g(170, 0), g(171, 2), g(172, 0), g(173, 0), g(174, 0), g(175, 0),
                  g(176, 0), g(177, 0), g(178, 0),
                  g(0, "ENDTAB"),
                  g(0, "ENDSEC"),
                  g(0, "SECTION"), g(2, "BLOCKS")]
        parts += self.blocks
        parts += [g(0, "ENDSEC"), g(0, "SECTION"), g(2, "ENTITIES")]
        parts += self.entities
        parts += [g(0, "ENDSEC"), g(0, "EOF")]
        with open(path, 'w', encoding='cp1252', errors='replace', newline='\r\n') as fh:
            fh.write(''.join(parts))


def write_dxf(path, sh):
    """Write one sheet at true size in the sheet's dimension unit."""
    fmt = sh.fmt
    f = sh.scale * fmt.factor / 1000.0          # drawing units per paper millimetre
    H = sh.height

    def T(p):
        return (p[0] * f, (H - p[1]) * f)

    wr = _Writer()
    dim_count = 0
    dim_text = sh.text_size * CAP * f
    tick = sh.text_size * 0.42 * f

    def emit(out, it, layer=None):
        layer = layer or it.layer
        if isinstance(it, S.Line):
            if len(it.points) < 2:
                return
            pts = [T(p) for p in it.points]
            if it.fill is not None:
                wr.solid(out, pts[:4], layer, _aci(it.fill))
            elif it.closed:
                wr.polyline(out, pts, layer, _colour(it), closed=True)
            else:
                wr.curve(out, pts, layer, _colour(it), fit_arcs=layer in (S.L_VISIBLE, S.L_LIGHTS))
        elif isinstance(it, S.Text):
            if it.text:
                x, y = T((it.x, it.y))
                wr.text(out, x, y, it.text, it.size * CAP * f, layer, _colour(it), it.anchor, it.rotation)
        elif isinstance(it, S.Shape):
            # DXF R12 has no curved fills: the logo is written as its outline.
            if max(it.fill[:3]) > 0.98:
                return
            for sub in it.subpaths:
                pts, cur = [], None
                for c in sub:
                    if c[0] in ('M', 'L'):
                        cur = (c[1], c[2])
                        pts.append(T(cur))
                    else:
                        x1, y1, x2, y2, x3, y3 = c[1:]
                        for i in range(1, 13):
                            t = i / 12.0
                            u = 1.0 - t
                            pts.append(T((u ** 3 * cur[0] + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
                                          u ** 3 * cur[1] + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3)))
                        cur = (x3, y3)
                if len(pts) > 2:
                    wr.polyline(out, pts, layer, 7, closed=True)
        elif isinstance(it, S.Fill):
            x0, y0 = T((it.x, it.y + it.h))
            x1, y1 = T((it.x + it.w, it.y))
            wr.polyline(out, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, _aci(it.color), closed=True)
        elif isinstance(it, S.Picture):
            x0, y0 = T((it.x, it.y + it.h))
            x1, y1 = T((it.x + it.w, it.y))
            wr.polyline(out, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, None, closed=True)
            wr.text(out, (x0 + x1) / 2, (y0 + y1) / 2, "RENDER PICTURE", 3.0 * CAP * f, layer, None, 'middle')

    def _colour(it):
        default = {S.L_VISIBLE: S.BLACK, S.L_TEXT: S.BLACK}.get(it.layer)
        if default is not None and tuple(it.color) == default:
            return None                       # BYLAYER
        if it.layer in (S.L_DIMS, S.L_NOTES, S.L_FRAME, S.L_HIDDEN) and _aci(it.color) in (7, 8):
            return None
        return _aci(it.color)

    for raw in sh.items:
        if isinstance(raw, S.Dim):
            ax, ay = T(raw.a)
            bx, by = T(raw.b)
            horizontal = abs(ay - by) <= abs(ax - bx)
            dim_count += 1
            name = "*D%d" % dim_count
            block = [wr._g(0, "BLOCK"), wr._g(8, "0"), wr._g(2, name), wr._g(70, 1),
                     wr._g(10, 0.0), wr._g(20, 0.0), wr._g(30, 0.0), wr._g(3, name)]
            body = []
            for prim in S.expand(raw):
                emit(body, prim, raw.layer)
            block += body + [wr._g(0, "ENDBLK"), wr._g(8, "0")]
            wr.blocks.append(''.join(block))
            p1, p2 = T(raw.p1), T(raw.p2)
            px, py, _rot = raw.text_position()
            tx, ty = T((px, py))
            moved = raw.text_level != 0 or raw.text_shift != 0.0
            wr.entities.append(
                wr._g(0, "DIMENSION") + wr._g(8, raw.layer) + wr._g(2, name)
                + wr._g(10, float(bx)) + wr._g(20, float(by)) + wr._g(30, 0.0)
                + wr._g(11, float(tx)) + wr._g(21, float(ty)) + wr._g(31, 0.0)
                + wr._g(70, 128 if moved else 0)
                + wr._g(13, float(p1[0])) + wr._g(23, float(p1[1])) + wr._g(33, 0.0)
                + wr._g(14, float(p2[0])) + wr._g(24, float(p2[1])) + wr._g(34, 0.0)
                + wr._g(50, 0.0 if horizontal else 90.0))
        elif isinstance(raw, S.Leader):
            for prim in S.expand(raw):
                emit(wr.entities, prim)
        else:
            emit(wr.entities, raw)

    wr.save(path, dim_text=dim_text, tick=tick, post=fmt.dxf_post, decimals=fmt.decimals)


def write_cnc(path, outlines, fmt):
    """Write flat cutting outlines side by side at true size.

    outlines: list of (name, polylines in metres, width, height, thickness)
    """
    wr = _Writer()
    k = fmt.factor
    sizes = [max(w, h) * k for _n, _p, w, h, _t in outlines] or [1.0]
    gap = max(sizes) * 0.08 + 1e-6
    text_h = max(max(sizes) * 0.02, 1e-6)
    x = 0.0
    for name, polylines, w, h, thickness in outlines:
        pts = np.vstack(polylines)
        ox, oy = pts[:, 0].min(), pts[:, 1].min()
        for pl in cleanup.chain(cleanup.clean_segments(polylines)):
            wr.curve(wr.entities, (pl - (ox, oy)) * k + (x, 0.0), "CUT")
        label = "%s  -  %s x %s %s, thickness %s" % (
            name, fmt.number(w), fmt.number(h), fmt.label, fmt.number(thickness))
        wr.text(wr.entities, x, -text_h * 2.5, label, text_h, "LABELS")
        x += w * k + gap
    wr.save(path, dim_text=text_h, tick=text_h * 0.5, post=fmt.dxf_post, decimals=fmt.decimals)
