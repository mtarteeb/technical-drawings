"""Line engine: turns objects into exact 2D line views.

Uses Blender's Line Art inside a temporary scene that holds only the objects
being drawn, so nothing else in the user's scene can hide lines and the
user's scene is never modified. Geometry only, no AI.
"""

import math

import bpy
import numpy as np
from mathutils import Matrix, Vector

DRAWABLE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}

# Front direction = the direction the viewer looks along for the FRONT view.
FRONT_DIRECTIONS = {
    'NEG_Y': Vector((0.0, 1.0, 0.0)),   # viewer stands at -Y (Blender's Front)
    'POS_Y': Vector((0.0, -1.0, 0.0)),
    'NEG_X': Vector((1.0, 0.0, 0.0)),
    'POS_X': Vector((-1.0, 0.0, 0.0)),
}

VIEW_LABELS = {
    'FRONT': "FRONT VIEW",
    'BACK': "BACK VIEW",
    'RIGHT': "SIDE VIEW",
    'LEFT': "LEFT SIDE VIEW",
    'TOP': "TOP VIEW",
}


def view_basis(view, front_dir):
    """Return (right, up, look) unit vectors for a named view."""
    z = Vector((0.0, 0.0, 1.0))
    f = front_dir.normalized()
    r = f.cross(z).normalized()          # viewer's right when looking along f
    if view == 'FRONT':
        return r, z, f
    if view == 'BACK':
        return -r, z, -f
    if view == 'RIGHT':                  # seen from the right-hand side
        return f, z, -r
    if view == 'LEFT':
        return -f, z, r
    if view == 'TOP':                    # front edge at the bottom of the view
        return r, f, -z
    raise ValueError(view)


def is_drawable(obj):
    if obj.type in DRAWABLE_TYPES:
        return True
    return obj.type == 'EMPTY' and obj.instance_collection is not None


class View:
    """One 2D view. Coordinates are in metres, x right, y up."""

    def __init__(self, name, polylines, hidden, bounds):
        self.name = name
        self.label = VIEW_LABELS[name]
        self.polylines = polylines      # list of (N,2) float arrays
        self.hidden = hidden            # list of (N,2) float arrays
        self.min_x, self.min_y, self.max_x, self.max_y = bounds

    @property
    def width(self):
        return self.max_x - self.min_x

    @property
    def height(self):
        return self.max_y - self.min_y


def _world_bounds(depsgraph):
    mn = np.full(3, np.inf)
    mx = np.full(3, -np.inf)
    found = False
    for inst in depsgraph.object_instances:
        ob = inst.object
        if ob.type not in DRAWABLE_TYPES:
            continue
        mw = inst.matrix_world
        for corner in ob.bound_box:
            w = mw @ Vector(corner)
            mn = np.minimum(mn, w)
            mx = np.maximum(mx, w)
            found = True
    if not found:
        return None
    return Vector(mn), Vector(mx)


def _add_lineart(gp_obj, layer_name, material, level_start, level_end, crease_angle):
    md = gp_obj.modifiers.new("TD_" + layer_name, 'LINEART')
    md.source_type = 'SCENE'
    md.target_layer = layer_name
    md.target_material = material
    md.use_contour = True
    md.use_crease = True
    md.use_intersection = True
    md.use_loose = True
    md.use_material = False
    md.use_edge_mark = True
    md.crease_threshold = crease_angle
    md.use_multiple_levels = level_start != level_end
    md.level_start = level_start
    md.level_end = level_end
    for prop, value in (
        ('smooth_tolerance', 0.0),
        ('chaining_image_threshold', 0.0),
        ('use_fuzzy_intersections', False),
        ('use_object_instances', True),
        ('use_image_boundary_trimming', False),
    ):
        if hasattr(md, prop):
            setattr(md, prop, value)
    return md


def _read_layer(layer, right, up):
    frame = layer.current_frame()
    if frame is None or frame.drawing is None:
        return []
    drawing = frame.drawing
    pos_attr = drawing.attributes.get('position')
    if pos_attr is None or len(pos_attr.data) == 0:
        return []
    n = len(pos_attr.data)
    pos = np.empty(n * 3, dtype=np.float32)
    pos_attr.data.foreach_get('vector', pos)
    pos = pos.reshape(n, 3).astype(np.float64)
    offsets = np.empty(len(drawing.curve_offsets), dtype=np.int32)
    drawing.curve_offsets.foreach_get('value', offsets)
    xy = np.column_stack((pos @ np.array(right), pos @ np.array(up)))
    return [xy[offsets[i]:offsets[i + 1]] for i in range(len(offsets) - 1)
            if offsets[i + 1] - offsets[i] >= 2]


def extract_views(objects, view_names, front_dir, frame=1, hidden_lines=False,
                  crease_angle=math.radians(140.0), unit_scale=1.0):
    """Compute 2D line views of `objects`.

    Returns {view_name: View}. Coordinates are metres (after `unit_scale`).
    Raises ValueError when there is nothing drawable.
    """
    objects = [o for o in objects if is_drawable(o)]
    if not objects:
        raise ValueError("Select at least one mesh, curve, text or collection instance.")

    data = bpy.data
    scene = data.scenes.new("TD_TempScene")
    cam_data = data.cameras.new("TD_TempCamera")
    cam_data.type = 'ORTHO'
    cam = data.objects.new("TD_TempCamera", cam_data)
    gp_data = data.grease_pencils.new("TD_TempLines")
    gp_obj = data.objects.new("TD_TempLines", gp_data)
    mat = data.materials.new("TD_TempLineMat")
    data.materials.create_gpencil_data(mat)
    gp_data.materials.append(mat)

    views = {}
    try:
        scene.frame_set(frame)
        scene.render.resolution_x = 2048
        scene.render.resolution_y = 2048
        scene.render.resolution_percentage = 100
        for ob in objects:
            scene.collection.objects.link(ob)
        scene.collection.objects.link(cam)
        scene.collection.objects.link(gp_obj)
        scene.camera = cam

        for name in ('visible', 'hidden'):
            layer = gp_data.layers.new(name)
            layer.frames.new(frame)
        _add_lineart(gp_obj, 'visible', mat, 0, 0, crease_angle)
        if hidden_lines:
            _add_lineart(gp_obj, 'hidden', mat, 1, 16, crease_angle)

        view_layer = scene.view_layers[0]
        view_layer.update()
        bounds = _world_bounds(view_layer.depsgraph)
        if bounds is None:
            raise ValueError("The selected objects have no geometry to draw.")
        mn, mx = bounds
        centre = (mn + mx) / 2.0
        radius = max((mx - mn).length / 2.0, 1e-4)

        for view in view_names:
            right, up, look = view_basis(view, front_dir)
            rot = Matrix((right, up, -look)).transposed()   # columns: X, Y, Z of the camera
            cam.matrix_world = Matrix.Translation(centre - look * (radius + 1.0)) @ rot.to_4x4()
            cam_data.ortho_scale = radius * 2.0 * 1.05
            cam_data.clip_start = 0.01
            cam_data.clip_end = radius * 2.0 + 2.0
            view_layer.update()
            evaluated = gp_obj.evaluated_get(view_layer.depsgraph)
            lines = {}
            for layer in evaluated.data.layers:
                lines[layer.name] = [pl * unit_scale for pl in _read_layer(layer, right, up)]
            vis = lines.get('visible', [])
            hid = lines.get('hidden', [])
            if not vis and not hid:
                continue
            allpts = np.vstack(vis + hid)
            b = (allpts[:, 0].min(), allpts[:, 1].min(), allpts[:, 0].max(), allpts[:, 1].max())
            views[view] = View(view, vis, hid, b)
    finally:
        data.scenes.remove(scene)
        data.objects.remove(gp_obj)
        data.objects.remove(cam)
        data.grease_pencils.remove(gp_data)
        data.cameras.remove(cam_data)
        data.materials.remove(mat)

    if not views:
        raise ValueError("No lines could be generated from the selected objects.")
    return views
