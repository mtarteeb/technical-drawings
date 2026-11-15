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

WARM_LIGHT = (1.0, 0.72, 0.0)
MAX_LIGHT_COLOURS = 6


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


def _linear_to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def light_colour(obj):
    """Colour to draw a light-emitting object in, or None if it does not emit.

    Reads the object's materials: a Principled BSDF with emission strength
    above zero, or an Emission shader. White and warm lights are drawn amber
    because white does not show on paper.
    """
    for slot in getattr(obj, 'material_slots', ()):
        mat = slot.material
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            colour = None
            if node.type == 'BSDF_PRINCIPLED':
                strength = node.inputs.get('Emission Strength')
                col = node.inputs.get('Emission Color') or node.inputs.get('Emission')
                if strength is None or col is None:
                    continue
                lit = strength.is_linked or strength.default_value > 0.0
                c = col.default_value
                if lit and (col.is_linked or max(c[0], c[1], c[2]) > 0.0):
                    colour = (c[0], c[1], c[2])
            elif node.type == 'EMISSION':
                strength = node.inputs.get('Strength')
                if strength is not None and (strength.is_linked or strength.default_value > 0.0):
                    c = node.inputs['Color'].default_value
                    colour = (c[0], c[1], c[2])
            if colour is None:
                continue
            r, g, b = (max(0.0, min(1.0, _linear_to_srgb(v))) for v in colour)
            hi, lo = max(r, g, b), min(r, g, b)
            if hi <= 0.0 or (hi - lo) / hi < 0.35:
                return WARM_LIGHT
            return (round(r / hi, 2), round(g / hi, 2), round(b / hi, 2))
    return None


class View:
    """One 2D view. Coordinates are in metres, x right, y up."""

    def __init__(self, name, polylines, hidden, lights, parts, bounds):
        self.name = name
        self.label = VIEW_LABELS.get(name, name)
        self.polylines = polylines      # list of (N,2) float arrays
        self.hidden = hidden            # list of (N,2) float arrays
        self.lights = lights            # list of (colour, [polylines])
        self.parts = parts              # {object name: (min_x, min_y, max_x, max_y)}
        self.min_x, self.min_y, self.max_x, self.max_y = bounds

    @property
    def width(self):
        return self.max_x - self.min_x

    @property
    def height(self):
        return self.max_y - self.min_y


def _instances(depsgraph):
    """Yield (selected object name, evaluated object, world matrix)."""
    for inst in depsgraph.object_instances:
        ob = inst.object
        if ob.type not in DRAWABLE_TYPES:
            continue
        owner = inst.parent if inst.is_instance and inst.parent is not None else ob
        yield owner.original.name, ob, inst.matrix_world.copy()


def _corners(depsgraph):
    """{object name: (K, 3) world-space bounding box corners}."""
    out = {}
    for name, ob, mw in _instances(depsgraph):
        pts = np.array([mw @ Vector(c) for c in ob.bound_box])
        out[name] = np.vstack((out[name], pts)) if name in out else pts
    return out


def _add_lineart(gp_obj, layer_name, material, level_start, level_end, crease_angle,
                 collection=None, contour_only=False):
    md = gp_obj.modifiers.new("TD_" + layer_name, 'LINEART')
    if collection is None:
        md.source_type = 'SCENE'
    else:
        md.source_type = 'COLLECTION'
        md.source_collection = collection
    md.target_layer = layer_name
    md.target_material = material
    md.use_contour = True
    md.use_crease = not contour_only
    md.use_intersection = not contour_only
    md.use_loose = True
    md.use_material = False
    md.use_edge_mark = not contour_only
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


class _TempScene:
    """Temporary scene with a camera and a Line Art object; always cleaned up."""

    def __init__(self, objects, frame):
        data = bpy.data
        self.scene = data.scenes.new("TD_TempScene")
        self.cam_data = data.cameras.new("TD_TempCamera")
        self.cam_data.type = 'ORTHO'
        self.cam = data.objects.new("TD_TempCamera", self.cam_data)
        self.gp_data = data.grease_pencils.new("TD_TempLines")
        self.gp_obj = data.objects.new("TD_TempLines", self.gp_data)
        self.mat = data.materials.new("TD_TempLineMat")
        data.materials.create_gpencil_data(self.mat)
        self.gp_data.materials.append(self.mat)
        self.collections = []
        self.frame = frame
        scene = self.scene
        scene.frame_set(frame)
        scene.render.resolution_x = 2048
        scene.render.resolution_y = 2048
        scene.render.resolution_percentage = 100
        for ob in objects:
            scene.collection.objects.link(ob)
        scene.collection.objects.link(self.cam)
        scene.collection.objects.link(self.gp_obj)
        scene.camera = self.cam
        self.view_layer = scene.view_layers[0]

    def layer(self, name):
        layer = self.gp_data.layers.new(name)
        layer.frames.new(self.frame)
        return layer

    def collection(self, name, objects):
        coll = bpy.data.collections.new(name)
        self.scene.collection.children.link(coll)
        for ob in objects:
            coll.objects.link(ob)
        self.collections.append(coll)
        return coll

    def aim(self, centre, radius, right, up, look):
        rot = Matrix((right, up, -look)).transposed()
        self.cam.matrix_world = Matrix.Translation(centre - look * (radius + 1.0)) @ rot.to_4x4()
        self.cam_data.ortho_scale = radius * 2.0 * 1.05
        self.cam_data.clip_start = 0.01
        self.cam_data.clip_end = radius * 2.0 + 2.0
        self.view_layer.update()

    def read(self, right, up, scale):
        evaluated = self.gp_obj.evaluated_get(self.view_layer.depsgraph)
        return {layer.name: [pl * scale for pl in _read_layer(layer, right, up)]
                for layer in evaluated.data.layers}

    def close(self):
        data = bpy.data
        data.scenes.remove(self.scene)
        data.objects.remove(self.gp_obj)
        data.objects.remove(self.cam)
        data.grease_pencils.remove(self.gp_data)
        data.cameras.remove(self.cam_data)
        data.materials.remove(self.mat)
        for coll in self.collections:
            data.collections.remove(coll)


def extract_views(objects, view_names, front_dir, frame=1, hidden_lines=False,
                  colour_lights=True, crease_angle=math.radians(140.0), unit_scale=1.0):
    """Compute 2D line views of `objects`.

    Returns {view_name: View}. Coordinates are metres (after `unit_scale`).
    Raises ValueError when there is nothing drawable.
    """
    objects = [o for o in objects if is_drawable(o)]
    if not objects:
        raise ValueError("Select at least one mesh, curve, text or collection instance.")

    light_groups = {}
    if colour_lights:
        for ob in objects:
            col = light_colour(ob)
            if col is not None and (col in light_groups or len(light_groups) < MAX_LIGHT_COLOURS):
                light_groups.setdefault(col, []).append(ob)

    tmp = _TempScene(objects, frame)
    views = {}
    try:
        tmp.layer('visible')
        _add_lineart(tmp.gp_obj, 'visible', tmp.mat, 0, 0, crease_angle)
        if hidden_lines:
            tmp.layer('hidden')
            _add_lineart(tmp.gp_obj, 'hidden', tmp.mat, 1, 16, crease_angle)
        light_layers = {}
        for i, (col, obs) in enumerate(light_groups.items()):
            name = 'light%d' % i
            tmp.layer(name)
            _add_lineart(tmp.gp_obj, name, tmp.mat, 0, 0, crease_angle,
                         collection=tmp.collection("TD_TempLights%d" % i, obs))
            light_layers[name] = col

        tmp.view_layer.update()
        corners = _corners(tmp.view_layer.depsgraph)
        if not corners:
            raise ValueError("The selected objects have no geometry to draw.")
        allc = np.vstack(list(corners.values()))
        mn, mx = Vector(allc.min(axis=0)), Vector(allc.max(axis=0))
        centre = (mn + mx) / 2.0
        radius = max((mx - mn).length / 2.0, 1e-4)

        for view in view_names:
            right, up, look = view_basis(view, front_dir)
            tmp.aim(centre, radius, right, up, look)
            lines = tmp.read(right, up, unit_scale)
            vis = lines.get('visible', [])
            hid = lines.get('hidden', [])
            if not vis and not hid:
                continue
            allpts = np.vstack(vis + hid)
            bounds = (allpts[:, 0].min(), allpts[:, 1].min(), allpts[:, 0].max(), allpts[:, 1].max())
            r, u = np.array(right), np.array(up)
            parts = {}
            for name, pts in corners.items():
                px, py = (pts @ r) * unit_scale, (pts @ u) * unit_scale
                parts[name] = (px.min(), py.min(), px.max(), py.max())
            lights = [(col, lines[name]) for name, col in light_layers.items() if lines.get(name)]
            views[view] = View(view, vis, hid, lights, parts, bounds)
    finally:
        tmp.close()

    if not views:
        raise ValueError("No lines could be generated from the selected objects.")
    return views


def extract_outline(obj, frame=1, unit_scale=1.0):
    """Flat cutting outline of one object, seen along its thinnest side.

    Returns (polylines, width, height, thickness) in metres, or None when the
    object has no outline.
    """
    if not is_drawable(obj):
        return None
    tmp = _TempScene([obj], frame)
    try:
        tmp.layer('visible')
        _add_lineart(tmp.gp_obj, 'visible', tmp.mat, 0, 0, math.radians(140.0), contour_only=True)
        tmp.view_layer.update()
        corners = _corners(tmp.view_layer.depsgraph)
        if not corners:
            return None
        allc = np.vstack(list(corners.values()))
        centre = Vector((allc.min(axis=0) + allc.max(axis=0)) / 2.0)
        radius = max(float(np.linalg.norm(allc.max(axis=0) - allc.min(axis=0))) / 2.0, 1e-4)

        # Object's own axes in world space, and its size along each.
        rot = obj.matrix_world.to_3x3()
        axes = [rot.col[i].normalized() for i in range(3)]
        sizes = [float(np.ptp(allc @ np.array(a))) for a in axes]
        thin = min(range(3), key=lambda i: sizes[i])
        others = [i for i in range(3) if i != thin]
        # Keep "up" as vertical as possible so parts are not drawn sideways.
        others.sort(key=lambda i: abs(axes[i].z))
        right, up = axes[others[0]], axes[others[1]]
        if up.z < 0:
            up = -up
        look = right.cross(up).normalized() * -1.0
        if abs(look.dot(axes[thin])) < 0.99:           # skewed object: fall back to exact cross product
            look = axes[thin]
            right = up.cross(look).normalized() * -1.0
        tmp.aim(centre, radius, right, up, look)
        lines = tmp.read(right, up, unit_scale).get('visible', [])
        if not lines:
            return None
        pts = np.vstack(lines)
        w = float(pts[:, 0].max() - pts[:, 0].min())
        h = float(pts[:, 1].max() - pts[:, 1].min())
        return lines, w, h, sizes[thin] * unit_scale
    finally:
        tmp.close()
