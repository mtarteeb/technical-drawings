"""Loads render pictures and converts them to JPEG bytes for embedding."""

import os
import tempfile

import bpy

MAX_SIDE = 2400


def load_jpeg(path):
    """Return (jpeg_bytes, width, height) for an image file, or None if unreadable."""
    path = bpy.path.abspath(path)
    if not os.path.isfile(path):
        return None
    try:
        src = bpy.data.images.load(path, check_existing=False)
    except RuntimeError:
        return None
    tmp = None
    try:
        w, h = src.size
        if w == 0 or h == 0:
            return None
        longest = max(w, h)
        if longest > MAX_SIDE:
            f = MAX_SIDE / longest
            w, h = max(1, round(w * f)), max(1, round(h * f))
            src.scale(w, h)
        fd, tmp = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        # Image.save keeps the picture's own colours (no scene view transform).
        src.file_format = 'JPEG'
        src.save(filepath=tmp, quality=92)
        with open(tmp, 'rb') as fh:
            data = fh.read()
        return data, w, h
    finally:
        bpy.data.images.remove(src)
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
