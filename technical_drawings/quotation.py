"""Quotation technicals: dimensions and notes drawn from the render camera,
laid over a finished render as editable vector lines and text.

Every dimension is measured from the model and projected through the same
camera as the render, so it sits exactly on the object in the picture.
"""

import math

import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from . import sheet as S

L_PICTURE = S.L_PICTURES
BOX_EDGES = [             # pairs of bound_box corner indices, grouped by local axis
    [(0, 4), (1, 5), (2, 6), (3, 7)],      # X
    [(0, 3), (1, 2), (4, 7), (5, 6)],      # Y
    [(0, 1), (3, 2), (4, 5), (7, 6)],      # Z
]


def _hull(points):
    """Convex hull indices of 2D points (monotone chain)."""
    idx = sorted(range(len(points)), key=lambda i: (points[i][0], points[i][1]))

    def cross(o, a, b):
        return ((points[a][0] - points[o][0]) * (points[b][1] - points[o][1])
                - (points[a][1] - points[o][1]) * (points[b][0] - points[o][0]))

    lower, upper = [], []
    for i in idx:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], i) <= 1e-12:
            lower.pop()
        lower.append(i)
    for i in reversed(idx):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], i) <= 1e-12:
            upper.pop()
        upper.append(i)
    return lower[:-1] + upper[:-1]


class _Projector:
    def __init__(self, scene, camera, x, y, w, h):
        self.scene, self.camera = scene, camera
        self.x, self.y, self.w, self.h = x, y, w, h

    def __call__(self, world):
        co = world_to_camera_view(self.scene, self.camera, Vector(world))
        return (self.x + co.x * self.w, self.y + (1.0 - co.y) * self.h), co.z


def _avoid_overlap(dim, placed):
    """Slide a dimension's text along its line until it is clear of the others."""
    from .export_pdf import text_width
    radius = max(text_width(dim.text, dim.size, True) / 2.0, dim.size)
    best = None
    for shift in (0.0, 0.22, -0.22, 0.38, -0.38):
        dim.text_shift = shift
        x, y, _ = dim.text_position()
        clash = sum(max(0.0, (radius + r) * 0.8 - math.hypot(x - px, y - py)) for px, py, r in placed)
        if best is None or clash < best[0] - 1e-9:
            best = (clash, shift)
        if clash == 0.0:
            break
    dim.text_shift = best[1]
    x, y, _ = dim.text_position()
    placed.append((x, y, radius))


def _box_dims(items, corners, project, fmt, size, colour, offset, unit_scale, placed, skip_small=True):
    """Dimension a box (8 world corners in bound_box order) on its outline."""
    pts, depth = [], []
    for c in corners:
        p, z = project(c)
        pts.append(p)
        depth.append(z)
    if min(depth) <= 0.0:
        return
    hull = _hull(pts)
    hull_edges = {frozenset((hull[i], hull[(i + 1) % len(hull)])) for i in range(len(hull))}
    cx = sum(pts[i][0] for i in hull) / len(hull)
    cy = sum(pts[i][1] for i in hull) / len(hull)
    lengths = [(Vector(corners[a]) - Vector(corners[b])).length for (a, b) in (e[0] for e in BOX_EDGES)]
    longest = max(lengths) or 1.0
    for axis, edges in enumerate(BOX_EDGES):
        if lengths[axis] <= 1e-6 or (skip_small and lengths[axis] < 0.05 * longest):
            continue
        best = None
        for a, b in edges:
            if frozenset((a, b)) not in hull_edges:
                continue
            on_page = math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])
            if on_page < size * 2.0:
                continue
            near = (depth[a] + depth[b]) / 2.0
            if best is None or near < best[0]:
                best = (near, a, b)
        if best is None:
            continue
        _, a, b = best
        (x0, y0), (x1, y1) = pts[a], pts[b]
        length = math.hypot(x1 - x0, y1 - y0)
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if (mx - cx) * nx + (my - cy) * ny < 0:          # push away from the object
            nx, ny = -nx, -ny
        pa = (x0 + nx * offset, y0 + ny * offset)
        pb = (x1 + nx * offset, y1 + ny * offset)
        dim = S.Dim((x0, y0), (x1, y1), pa, pb, fmt.text(lengths[axis] * unit_scale),
                    size, S.L_DIMS, colour, width=size * 0.035, bold=True)
        _avoid_overlap(dim, placed)
        items.append(dim)


def build(scene, camera, objects, picture, fmt, colour=(1.0, 1.0, 1.0), text_size=12.0 * 25.4 / 72.0,
          own_dims=(), notes=(), overall=True, paper='A3'):
    """Build the overlay sheet.

    picture: (path, pixel_w, pixel_h) of the finished render
    own_dims: objects that get their own width/depth/height
    notes: list of (object, text)
    overall: dimension the whole selection when no object has own dimensions
    """
    path, iw, ih = picture
    # The picture fills a standard sheet as far as its proportions allow.
    PAGE_W, page_h = S.PAPER_SIZES[paper]
    img_w, img_h = PAGE_W, PAGE_W * ih / iw
    if img_h > page_h:
        img_w, img_h = page_h * iw / ih, page_h
    img_x, img_y = (PAGE_W - img_w) / 2.0, (page_h - img_h) / 2.0
    project = _Projector(scene, camera, img_x, img_y, img_w, img_h)
    unit_scale = scene.unit_settings.scale_length
    items = [S.Picture(path, img_x, img_y, img_w, img_h)]
    offset = text_size * 1.3
    dim_texts = []

    for ob in own_dims:
        corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        _box_dims(items, corners, project, fmt, text_size, colour, offset, unit_scale, dim_texts)

    if overall and not own_dims and objects:
        allc = np.array([ob.matrix_world @ Vector(c) for ob in objects for c in ob.bound_box])
        mn, mx = allc.min(axis=0), allc.max(axis=0)
        corners = [(mn[0], mn[1], mn[2]), (mn[0], mn[1], mx[2]), (mn[0], mx[1], mx[2]), (mn[0], mx[1], mn[2]),
                   (mx[0], mn[1], mn[2]), (mx[0], mn[1], mx[2]), (mx[0], mx[1], mx[2]), (mx[0], mx[1], mn[2])]
        _box_dims(items, corners, project, fmt, text_size, colour, offset, unit_scale, dim_texts, skip_small=False)

    # Notes: leader from the object's centre towards the nearer side of the picture.
    from .export_pdf import text_width
    note_size = text_size * 0.8
    placed = []
    entries = []
    for ob, text in notes:
        centre = sum((ob.matrix_world @ Vector(c) for c in ob.bound_box), Vector()) / 8.0
        p, z = project(centre)
        if z > 0.0 and img_x <= p[0] <= img_x + img_w and img_y <= p[1] <= img_y + img_h:
            entries.append((p, text))
    entries.sort(key=lambda e: e[0][1])
    for (x, y), text in entries:
        tw = text_width(text, note_size, True)
        side = 1.0 if x >= PAGE_W / 2.0 else -1.0
        reach = PAGE_W * 0.07
        ex = x + side * reach
        ex = min(max(ex, tw + 6.0), PAGE_W - tw - 6.0) if tw + 12.0 < PAGE_W else x
        ey = y - PAGE_W * 0.03
        for px, py in placed:
            if abs(px - ex) < tw + 20.0 and abs(py - ey) < note_size * 1.8:
                ey = py + note_size * 1.8
        ey = min(max(ey, note_size * 1.5), page_h - note_size)
        placed.append((ex, ey))
        items.append(S.Leader([(x, y), (ex, ey)], text, note_size, S.L_NOTES, colour,
                              width=text_size * 0.035, anchor='start' if side > 0 else 'end',
                              bold=True, arrow=0.0))

    return S.Sheet(PAGE_W, page_h, items, {}, 0, "Quotation", fmt, paper, text_size)
