"""SVG writer. Layers become named groups, text stays live text, so the file
is editable in Illustrator, Inkscape and Affinity."""

import base64
from xml.sax.saxutils import escape

from . import sheet as S


def _rgb(c):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(v * 255))) for v in c[:3])


def _n(v):
    return ('%.3f' % v).rstrip('0').rstrip('.') if v else '0'


def write_svg(path, sh, images):
    """Write one sheet. `images` maps picture path -> (jpeg_bytes, w, h)."""
    layers = {}
    order = []
    for raw in sh.items:
        if raw.layer not in layers:
            layers[raw.layer] = []
            order.append(raw.layer)
        if isinstance(raw, (S.Dim, S.Leader)):
            # Keep each dimension or note together as one group for easy editing.
            layers[raw.layer].append('<g>')
            for prim in S.expand(raw):
                _emit(layers[raw.layer], prim, images)
            layers[raw.layer].append('</g>')
        else:
            _emit(layers[raw.layer], raw, images)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
             'width="%smm" height="%smm" viewBox="0 0 %s %s">' % (
                 _n(sh.width), _n(sh.height), _n(sh.width), _n(sh.height))]
    for name in order:
        parts.append('<g id="%s" inkscape:groupmode="layer" inkscape:label="%s">' % (name, name))
        parts.extend(layers[name])
        parts.append('</g>')
    parts.append('</svg>')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(parts))


def _emit(out, it, images):
    if isinstance(it, S.Fill):
        out.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (
            _n(it.x), _n(it.y), _n(it.w), _n(it.h), _rgb(it.color)))
    elif isinstance(it, S.Picture):
        img = images.get(it.path)
        if img:
            out.append('<image x="%s" y="%s" width="%s" height="%s" preserveAspectRatio="none" '
                       'href="data:image/jpeg;base64,%s"/>' % (
                           _n(it.x), _n(it.y), _n(it.w), _n(it.h),
                           base64.b64encode(img[0]).decode('ascii')))
    elif isinstance(it, S.Line):
        if len(it.points) < 2:
            return
        pts = ' '.join('%s,%s' % (_n(x), _n(y)) for x, y in it.points)
        dash = ' stroke-dasharray="%s"' % ' '.join(_n(d) for d in it.dash) if it.dash else ''
        fill = _rgb(it.fill) if it.fill is not None else 'none'
        stroke = _rgb(it.color) if it.width > 0 else 'none'
        out.append('<%s points="%s" fill="%s" stroke="%s" stroke-width="%s" '
                   'stroke-linecap="round" stroke-linejoin="round"%s/>' % (
                       'polygon' if it.closed else 'polyline', pts, fill, stroke, _n(it.width), dash))
    elif isinstance(it, S.Text):
        if not it.text:
            return
        rot = ' transform="rotate(%s %s %s)"' % (_n(-it.rotation), _n(it.x), _n(it.y)) if it.rotation else ''
        out.append('<text x="%s" y="%s" font-family="Helvetica, Arial, sans-serif" font-size="%s" '
                   'fill="%s"%s text-anchor="%s"%s>%s</text>' % (
                       _n(it.x), _n(it.y), _n(it.size), _rgb(it.color),
                       ' font-weight="bold"' if it.bold else '', it.anchor, rot, escape(it.text)))
