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


def render_camera(scene, camera, max_width=1800):
    """Render the scene from `camera` with the scene's own render settings and
    return (jpeg_bytes, width, height). The scene's settings are restored."""
    render = scene.render
    settings = render.image_settings
    saved = {
        'camera': scene.camera,
        'filepath': render.filepath,
        'percentage': render.resolution_percentage,
        'file_format': settings.file_format,
        'color_mode': settings.color_mode,
        'quality': settings.quality,
        'use_file_extension': render.use_file_extension,
    }
    media = getattr(settings, 'media_type', None)
    fd, tmp = tempfile.mkstemp(suffix='.jpg')
    os.close(fd)
    try:
        scene.camera = camera
        full_w = render.resolution_x
        render.resolution_percentage = max(1, min(100, round(100.0 * max_width / max(full_w, 1))))
        if media is not None:
            settings.media_type = 'IMAGE'
        settings.file_format = 'JPEG'
        settings.color_mode = 'RGB'
        settings.quality = 92
        render.use_file_extension = False
        render.filepath = tmp
        bpy.ops.render.render(write_still=True, scene=scene.name)
        with open(tmp, 'rb') as fh:
            data = fh.read()
        if not data:
            return None
        check = bpy.data.images.load(tmp, check_existing=False)
        try:
            w, h = check.size
        finally:
            bpy.data.images.remove(check)
        return data, w, h
    finally:
        scene.camera = saved['camera']
        render.filepath = saved['filepath']
        render.resolution_percentage = saved['percentage']
        if media is not None:
            settings.media_type = media
        settings.file_format = saved['file_format']
        settings.color_mode = saved['color_mode']
        settings.quality = saved['quality']
        render.use_file_extension = saved['use_file_extension']
        if os.path.exists(tmp):
            os.remove(tmp)
