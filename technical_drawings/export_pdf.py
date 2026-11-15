"""Vector PDF writer (pure Python, no dependencies).

Lines stay vector and text stays real, selectable text (Helvetica), so the
PDF opens editable in Illustrator.
"""

import math
import zlib

from . import sheet as S

MM = 72.0 / 25.4

_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HELV_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
              556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
              975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
              667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
              333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
              611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]


def text_width(text, size, bold=False):
    """Width of `text` in the same units as `size`."""
    table = _HELV_BOLD if bold else _HELV
    total = 0
    for ch in text:
        code = ord(ch)
        total += table[code - 32] if 32 <= code <= 126 else 556
    return total * size / 1000.0


def _pdf_string(text):
    raw = text.encode('cp1252', 'replace')
    raw = raw.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
    return b'(' + raw + b')'


def _f(v):
    return ('%.3f' % v).rstrip('0').rstrip('.') if v else '0'


def _page_stream(sh, image_names):
    out = []
    w = out.append
    # Work in millimetres with the origin at the top-left corner.
    w('%s 0 0 %s 0 %s cm' % (_f(MM), _f(-MM), _f(sh.height * MM)))
    w('1 J 1 j')
    state = None
    for it in (prim for raw in sh.items for prim in S.expand(raw)):
        if isinstance(it, S.Fill):
            w('%s %s %s rg %s %s %s %s re f' % (*map(_f, it.color), _f(it.x), _f(it.y), _f(it.w), _f(it.h)))
        elif isinstance(it, S.Picture):
            name = image_names.get(it.path)
            if name:
                w('q %s 0 0 %s %s %s cm /%s Do Q' % (_f(it.w), _f(-it.h), _f(it.x), _f(it.y + it.h), name))
        elif isinstance(it, S.Line):
            if len(it.points) < 2:
                continue
            new_state = (it.color, it.width, it.dash)
            if new_state != state:
                w('%s %s %s RG %s w [%s] 0 d' % (*map(_f, it.color), _f(it.width),
                                                 ' '.join(_f(d) for d in it.dash)))
                state = new_state
            p = it.points
            seg = ['%s %s m' % (_f(p[0][0]), _f(p[0][1]))]
            seg += ['%s %s l' % (_f(x), _f(y)) for x, y in p[1:]]
            if it.fill is not None:
                w('%s %s %s rg' % tuple(map(_f, it.fill)))
                seg.append('h B' if it.width > 0 else 'h f')
            else:
                seg.append('h S' if it.closed else 'S')
            w(' '.join(seg))
        elif isinstance(it, S.Text):
            if not it.text:
                continue
            tw = text_width(it.text, it.size, it.bold)
            shift = {'start': 0.0, 'middle': -tw / 2.0, 'end': -tw}[it.anchor]
            a = math.radians(it.rotation)
            ca, sa = math.cos(a), math.sin(a)
            x = it.x + shift * ca
            y = it.y - shift * sa
            w('BT /%s %s Tf %s %s %s rg %s %s %s %s %s %s Tm ' % (
                'F2' if it.bold else 'F1', _f(it.size), *map(_f, it.color),
                _f(ca), _f(-sa), _f(-sa), _f(-ca), _f(x), _f(y)))
            out[-1] = out[-1].encode('latin-1') + _pdf_string(it.text) + b' Tj ET'
    return b'\n'.join(o if isinstance(o, bytes) else o.encode('latin-1') for o in out)


def write_pdf(path, sheets, images):
    """Write `sheets` (list of sheet.Sheet) as a multi-page PDF.

    `images` maps picture path -> (jpeg_bytes, pixel_w, pixel_h).
    """
    objects = []          # index 0 == object number 1

    def add(body):
        objects.append(body)
        return len(objects)

    catalog = add(None)
    pages = add(None)
    f1 = add(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    f2 = add(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')

    image_names, image_refs = {}, []
    for i, (ipath, (jpeg, iw, ih)) in enumerate(images.items()):
        num = add(b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB '
                  b'/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n' % (iw, ih, len(jpeg))
                  + jpeg + b'\nendstream')
        image_names[ipath] = 'Im%d' % i
        image_refs.append('/Im%d %d 0 R' % (i, num))

    page_nums = []
    for sh in sheets:
        data = zlib.compress(_page_stream(sh, image_names), 9)
        content = add(b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(data) + data + b'\nendstream')
        page = add(('<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %s %s] /Contents %d 0 R '
                    '/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> /XObject << %s >> >> >>'
                    % (pages, _f(sh.width * MM), _f(sh.height * MM), content, f1, f2,
                       ' '.join(image_refs))).encode('latin-1'))
        page_nums.append(page)

    objects[catalog - 1] = ('<< /Type /Catalog /Pages %d 0 R >>' % pages).encode('latin-1')
    objects[pages - 1] = ('<< /Type /Pages /Count %d /Kids [%s] >>' % (
        len(page_nums), ' '.join('%d 0 R' % n for n in page_nums))).encode('latin-1')

    buf = bytearray(b'%PDF-1.5\n%\xe2\xe3\xcf\xd3\n')
    offsets = []
    for i, body in enumerate(objects):
        offsets.append(len(buf))
        buf += b'%d 0 obj\n' % (i + 1) + body + b'\nendobj\n'
    xref = len(buf)
    buf += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    for off in offsets:
        buf += b'%010d 00000 n \n' % off
    buf += b'trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, catalog, xref)
    with open(path, 'wb') as fh:
        fh.write(buf)
