"""Technical Drawings: production and quotation technicals from selected objects.

Workflow: select the objects to draw, set the options in the sidebar panel
(3D Viewport > Sidebar > Technicals), press Export.
"""

import os

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, PointerProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import dims, engine, export_dxf, export_pdf, export_svg, images, quotation, sheet


class TD_Swatch(PropertyGroup):
    name: StringProperty(name="Name", default="Pantone 000 C")
    color: FloatVectorProperty(name="Colour", subtype='COLOR', size=3, min=0.0, max=1.0,
                               default=(0.12, 0.27, 0.49))


def _camera_poll(self, obj):
    return obj.type == 'CAMERA'


class TD_Picture(PropertyGroup):
    camera: PointerProperty(
        name="Camera", type=bpy.types.Object, poll=_camera_poll,
        description="Camera to render from. The picture is rendered with the scene's render settings "
                    "when you export, which can take a while")
    path: StringProperty(
        name="Finished Render", subtype='FILE_PATH',
        description="Optional: use this finished render instead of rendering the camera again")


class TD_Settings(PropertyGroup):
    mode: EnumProperty(
        name="Drawing Type",
        items=[('PRODUCTION', "Production", "Sheet with front, top and side views for the workshop"),
               ('QUOTATION', "Quotation", "Dimensions and notes laid over a finished render")],
        default='PRODUCTION')

    project_name: StringProperty(name="Project Name")
    client: StringProperty(name="Client")
    drawing_title: StringProperty(name="Drawing Title",
                                  description="Name of the element on this sheet, e.g. Entrance Arch")
    drawn_by: StringProperty(name="Drawing By")
    logo: BoolProperty(name="Company Logo", default=True,
                       description="Show the TARTEEB logo in the information strip")
    notes: StringProperty(
        name="General Notes",
        description="Separate notes with a semicolon ( ; ). The unit and scale notes are added automatically",
        default="")

    paper: EnumProperty(name="Paper", default='A3',
                        description="Sheet size. With 'Bigger Paper' this is the smallest size used",
                        items=[(k, k + " landscape", "") for k in sheet.PAPER_SIZES])
    fit: EnumProperty(
        name="If It Does Not Fit", default='SHEETS',
        description="What to do when the views cannot be drawn large enough on one sheet "
                    "for the dimensions to stay readable",
        items=[('SHEETS', "More Sheets", "Keep the paper size and spread the views over more sheets"),
               ('PAPER', "Bigger Paper", "Keep one sheet and step up to the next standard size (up to A0)")])
    text_pt: FloatProperty(
        name="Text Size", default=12.0, min=6.0, max=36.0, subtype='NONE',
        description="Size of dimension and note text on the printed sheet, in points. "
                    "It stays this size whatever the scale of the drawing")
    front_direction: EnumProperty(
        name="Front Faces",
        description="Which way the front of the selected objects faces",
        default='NEG_Y',
        items=[('NEG_Y', "-Y (Blender Front)", "The front is seen in Blender's Front view (Numpad 1)"),
               ('POS_Y', "+Y (Blender Back)", "The front is seen in Blender's Back view"),
               ('NEG_X', "-X (Blender Left)", "The front is seen in Blender's Left view"),
               ('POS_X', "+X (Blender Right)", "The front is seen in Blender's Right view")])

    view_front: BoolProperty(name="Front", default=True)
    view_top: BoolProperty(name="Top", default=True)
    view_right: BoolProperty(name="Side", default=True, description="Right-hand side view")
    view_left: BoolProperty(name="Left Side", default=False)
    view_back: BoolProperty(name="Back", default=False)
    hidden_lines: BoolProperty(name="Hidden Lines", default=False,
                               description="Draw edges that are hidden behind other parts as dashed lines")
    ignore_bevels: BoolProperty(
        name="Ignore Bevels", default=True,
        description="Draw and measure parts as if their Bevel modifiers were off, so sizes are the "
                    "true corner-to-corner sizes. The model is not changed")
    colour_lights: BoolProperty(
        name="Colour Light Strips", default=True,
        description="Draw objects whose material emits light in the colour of the light")

    dimensions: BoolProperty(name="Dimensions", default=True,
                             description="Measure the model and add dimensions automatically")
    unit: EnumProperty(name="Unit", default='CM',
                       items=[('CM', "Centimetres", ""), ('MM', "Millimetres", ""),
                              ('M', "Metres", ""), ('IN', "Inches", "")])
    decimals: IntProperty(name="Decimals", default=1, min=0, max=3,
                          description="Most decimal places shown; trailing zeros are dropped")
    suffix: EnumProperty(name="Unit Text", default='SPACED',
                         items=[('SPACED', "500 cm", "Number, space, unit"),
                                ('UPPER', "500CM", "Number and unit in capitals"),
                                ('NONE', "500", "Number only")])
    detail: EnumProperty(
        name="Detail", default='MEDIUM',
        description="How many intermediate dimensions are added between the overall sizes",
        items=[('LOW', "Few", "Only the most prominent edges"),
               ('MEDIUM', "Normal", ""),
               ('HIGH', "Many", "Also shorter edges")])
    radii: BoolProperty(name="Radii", default=True, description="Add the radius of arcs and the diameter of circles")
    object_notes: BoolProperty(name="Object Notes", default=True,
                               description="Show the notes typed on objects as arrows with text")

    swatches: CollectionProperty(type=TD_Swatch)
    swatch_index: IntProperty()
    pictures: CollectionProperty(type=TD_Picture)
    picture_index: IntProperty()

    quote_camera: PointerProperty(name="Camera", type=bpy.types.Object, poll=_camera_poll,
                                  description="Camera of the render. Empty = the scene camera")
    quote_picture: StringProperty(
        name="Finished Render", subtype='FILE_PATH',
        description="Optional: the finished render made from this camera. "
                    "Leave empty to render the camera when you export")
    quote_colour: FloatVectorProperty(name="Colour", subtype='COLOR', size=3, min=0.0, max=1.0,
                                      default=(1.0, 1.0, 1.0),
                                      description="Colour of the dimensions and notes on the picture")

    export_pdf: BoolProperty(name="PDF", default=True)
    export_svg: BoolProperty(name="SVG (Illustrator)", default=False)
    export_dxf: BoolProperty(name="DXF (AutoCAD)", default=False,
                             description="True-size drawing with editable dimensions. Production only")
    export_cnc: BoolProperty(
        name="CNC Outlines (DXF)", default=False,
        description="Separate DXF with the flat cutting outline of every selected object at true size")
    output_dir: StringProperty(name="Folder", subtype='DIR_PATH', default="//Technicals/",
                               description="Where the drawings are saved")
    file_name: StringProperty(name="File Name", default="",
                              description="Leave empty to use the drawing title or project name")
    open_after: BoolProperty(
        name="Open When Done", default=True,
        description="Open the PDF after exporting, or the folder when no PDF was made. "
                    "DXF and SVG files are never opened automatically")


LIST_INDEX = {"swatches": "swatch_index", "pictures": "picture_index"}


def _selected_views(st):
    order = (('FRONT', st.view_front), ('RIGHT', st.view_right), ('LEFT', st.view_left),
             ('BACK', st.view_back), ('TOP', st.view_top))
    return [name for name, on in order if on]


def _safe_name(text):
    keep = "".join(c if c.isalnum() or c in " -_()." else "_" for c in text).strip(" .")
    return keep or "Technical Drawing"


def _format(st):
    return dims.Format(st.unit, st.decimals, st.suffix)


class TD_OT_export(Operator):
    bl_idname = "technical_drawings.export"
    bl_label = "Export Technicals"
    bl_description = "Create the technical drawing of the selected objects"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        st = context.scene.technical_drawings
        objects = [o for o in context.selected_objects if engine.is_drawable(o)]
        if not objects:
            self.report({'ERROR'}, "Select the objects you want to draw first.")
            return {'CANCELLED'}
        quotation_mode = st.mode == 'QUOTATION'
        formats = [st.export_pdf, st.export_svg] + ([] if quotation_mode else [st.export_dxf, st.export_cnc])
        if not any(formats):
            self.report({'ERROR'}, "Turn on at least one file format.")
            return {'CANCELLED'}

        out_dir = bpy.path.abspath(st.output_dir or "//")
        if out_dir.startswith("//") or not os.path.isabs(out_dir):
            self.report({'ERROR'}, "Save the .blend file first, or choose a folder for the drawings.")
            return {'CANCELLED'}
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as err:
            self.report({'ERROR'}, "Cannot create the folder: %s" % err)
            return {'CANCELLED'}

        base = _safe_name(st.file_name or st.drawing_title or st.project_name)
        try:
            if quotation_mode:
                written, info = self._quotation(context, st, objects, out_dir, base)
            else:
                written, info = self._production(context, st, objects, out_dir, base)
        except ValueError as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        except OSError as err:
            self.report({'ERROR'}, "Could not save: %s" % err)
            return {'CANCELLED'}

        self.report({'INFO'}, "Saved %d file(s)%s to %s" % (len(written), info, out_dir))
        if st.open_after and written and not bpy.app.background:
            # Only the PDF is opened for viewing. CAD and vector files are left
            # closed: a file that is already open in one program opens
            # read-only (locked) in AutoCAD.
            pdfs = [p for p in written if p.lower().endswith(".pdf")]
            bpy.ops.wm.path_open(filepath=pdfs[0] if pdfs else out_dir)
        return {'FINISHED'}

    def _production(self, context, st, objects, out_dir, base):
        views_wanted = _selected_views(st)
        if not views_wanted:
            raise ValueError("Turn on at least one view.")
        scene = context.scene
        unit_scale = scene.unit_settings.scale_length
        fmt = _format(st)
        written = []

        if st.export_pdf or st.export_svg or st.export_dxf:
            views = engine.extract_views(
                objects, views_wanted, engine.FRONT_DIRECTIONS[st.front_direction],
                frame=scene.frame_current, hidden_lines=st.hidden_lines,
                colour_lights=st.colour_lights, unit_scale=unit_scale,
                ignore_bevels=st.ignore_bevels)

            image_data, pictures, missing = {}, [], []
            for i, pic in enumerate(st.pictures):
                if pic.path:
                    key = pic.path
                    loaded = images.load_jpeg(pic.path)
                    if loaded is None:
                        missing.append(os.path.basename(pic.path))
                        continue
                elif pic.camera is not None:
                    key = "camera:%d:%s" % (i, pic.camera.name)
                    loaded = images.render_camera(scene, pic.camera)
                    if loaded is None:
                        missing.append(pic.camera.name)
                        continue
                else:
                    continue
                image_data[key] = loaded
                pictures.append((key, loaded[1], loaded[2]))
            if missing:
                self.report({'WARNING'}, "Picture could not be made: " + ", ".join(missing))

            notes = ["ALL DIMENSIONS ARE IN %s UNLESS OTHERWISE SPECIFIED." % {
                'CM': "CENTIMETERS", 'MM': "MILLIMETERS", 'M': "METERS", 'IN': "INCHES"}[st.unit]]
            notes += [n.strip() for n in st.notes.replace("\n", ";").split(";")]
            settings = sheet.SheetSettings(
                paper=st.paper, project_name=st.project_name, client=st.client,
                drawing_title=st.drawing_title, drawn_by=st.drawn_by, notes=notes,
                swatches=[(s.name, tuple(s.color)) for s in st.swatches],
                pictures=pictures, hidden_lines=st.hidden_lines,
                dimensions=st.dimensions, fmt=fmt, detail=st.detail, radii=st.radii,
                object_notes=[(o.name, o.td_note.strip()) for o in objects
                              if st.object_notes and o.td_note.strip()],
                forced_parts=[o.name for o in objects if o.td_own_dims],
                dim_text_size=st.text_pt * 25.4 / 72.0, fit=st.fit, logo=st.logo)
            sheets = sheet.build_sheets(views, settings)

            def numbered(ext, sh):
                tail = " - sheet %d" % sh.number if len(sheets) > 1 else ""
                return os.path.join(out_dir, base + tail + ext)

            if st.export_pdf:
                path = os.path.join(out_dir, base + ".pdf")
                export_pdf.write_pdf(path, sheets, image_data)
                written.append(path)
            for sh in sheets:
                if st.export_svg:
                    export_svg.write_svg(numbered(".svg", sh), sh, image_data)
                    written.append(numbered(".svg", sh))
                if st.export_dxf:
                    export_dxf.write_dxf(numbered(".dxf", sh), sh)
                    written.append(numbered(".dxf", sh))
            info = " (%d sheet%s, %s, scale 1:%d)" % (
                len(sheets), "" if len(sheets) == 1 else "s", sheets[0].paper, sheets[0].scale)
        else:
            info = ""

        if st.export_cnc:
            outlines = []
            for ob in objects:
                result = engine.extract_outline(ob, frame=scene.frame_current, unit_scale=unit_scale,
                                                ignore_bevels=st.ignore_bevels)
                if result:
                    outlines.append((ob.name,) + result)
            if outlines:
                path = os.path.join(out_dir, base + " - CNC.dxf")
                export_dxf.write_cnc(path, outlines, fmt)
                written.append(path)
        return written, info

    def _quotation(self, context, st, objects, out_dir, base):
        scene = context.scene
        camera = st.quote_camera or scene.camera
        if camera is None:
            raise ValueError("Choose the camera the render was made from.")
        if st.quote_picture:
            picture_key = st.quote_picture
            loaded = images.load_jpeg(st.quote_picture)
            if loaded is None:
                raise ValueError("The render picture could not be read.")
        else:
            picture_key = "camera:" + camera.name
            loaded = images.render_camera(scene, camera, max_width=2400)
            if loaded is None:
                raise ValueError("The camera could not be rendered.")
        render = scene.render
        cam_aspect = (render.resolution_x * render.pixel_aspect_x) / (render.resolution_y * render.pixel_aspect_y)
        if abs(loaded[1] / loaded[2] - cam_aspect) > 0.01 * cam_aspect:
            self.report({'WARNING'}, "The picture's proportions differ from the scene's render size; "
                                     "dimensions may not line up.")
        meshes = [o for o in objects if o.type in engine.DRAWABLE_TYPES]
        sh = quotation.build(
            scene, camera, meshes, (picture_key, loaded[1], loaded[2]), _format(st),
            colour=tuple(st.quote_colour), text_size=st.text_pt * 25.4 / 72.0, paper=st.paper,
            own_dims=[o for o in meshes if o.td_own_dims],
            notes=[(o, o.td_note.strip()) for o in meshes if st.object_notes and o.td_note.strip()],
            overall=st.dimensions)
        image_data = {picture_key: loaded}
        base += " - Quotation"
        written = []
        if st.export_pdf:
            path = os.path.join(out_dir, base + ".pdf")
            export_pdf.write_pdf(path, [sh], image_data)
            written.append(path)
        if st.export_svg:
            path = os.path.join(out_dir, base + ".svg")
            export_svg.write_svg(path, sh, image_data)
            written.append(path)
        return written, ""


class TD_OT_list_add(Operator):
    bl_idname = "technical_drawings.list_add"
    bl_label = "Add"
    bl_options = {'REGISTER', 'UNDO'}
    target: StringProperty()

    def execute(self, context):
        st = context.scene.technical_drawings
        coll = getattr(st, self.target)
        coll.add()
        setattr(st, LIST_INDEX[self.target], len(coll) - 1)
        return {'FINISHED'}


class TD_OT_list_remove(Operator):
    bl_idname = "technical_drawings.list_remove"
    bl_label = "Remove"
    bl_options = {'REGISTER', 'UNDO'}
    target: StringProperty()

    def execute(self, context):
        st = context.scene.technical_drawings
        coll = getattr(st, self.target)
        idx_name = LIST_INDEX[self.target]
        idx = getattr(st, idx_name)
        if 0 <= idx < len(coll):
            coll.remove(idx)
            setattr(st, idx_name, max(0, idx - 1))
        return {'FINISHED'}


class TD_OT_note_to_selected(Operator):
    bl_idname = "technical_drawings.note_to_selected"
    bl_label = "Copy to Selected"
    bl_description = "Give every selected object the same note and dimension setting as the active object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        src = context.active_object
        for ob in context.selected_objects:
            ob.td_note = src.td_note
            ob.td_own_dims = src.td_own_dims
            ob.td_no_dims = src.td_no_dims
        return {'FINISHED'}


class TD_UL_swatches(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "color", text="")
        row.prop(item, "name", text="", emboss=False)


class TD_UL_pictures(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.prop(item, "camera", text="")


class TD_PT_base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Technicals"

    @staticmethod
    def _split(layout):
        layout.use_property_split = True
        layout.use_property_decorate = False
        return layout


class TD_PT_main(TD_PT_base, Panel):
    bl_idname = "TD_PT_main"
    bl_label = "Technical Drawings"

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self.layout
        layout.prop(st, "mode", expand=True)
        count = sum(1 for o in context.selected_objects if engine.is_drawable(o))
        box = layout.box()
        box.label(text="%d object(s) selected to draw" % count,
                  icon='CHECKMARK' if count else 'ERROR')
        col = layout.column()
        col.scale_y = 1.5
        col.operator(TD_OT_export.bl_idname, icon='EXPORT')


class TD_PT_quotation(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Render"

    @classmethod
    def poll(cls, context):
        return context.scene.technical_drawings.mode == 'QUOTATION'

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self._split(self.layout)
        layout.prop(st, "quote_camera")
        layout.prop(st, "quote_picture")
        if not st.quote_picture:
            layout.label(text="No file: the camera is rendered on export.", icon='INFO')
        layout.prop(st, "quote_colour")
        layout.prop(st, "paper")


class TD_PT_views(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Views"

    @classmethod
    def poll(cls, context):
        return context.scene.technical_drawings.mode == 'PRODUCTION'

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self._split(self.layout)
        layout.prop(st, "front_direction")
        col = layout.column(heading="Show", align=True)
        col.prop(st, "view_front")
        col.prop(st, "view_top")
        col.prop(st, "view_right")
        col.prop(st, "view_left")
        col.prop(st, "view_back")
        col = layout.column(heading="Lines", align=True)
        col.prop(st, "hidden_lines")
        col.prop(st, "colour_lights")
        col.prop(st, "ignore_bevels")


class TD_PT_dimensions(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Dimensions and Notes"

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self._split(self.layout)
        layout.prop(st, "dimensions")
        col = layout.column()
        col.active = st.dimensions
        col.prop(st, "unit")
        col.prop(st, "suffix")
        col.prop(st, "decimals")
        layout.prop(st, "text_pt")
        if st.mode == 'PRODUCTION':
            col.prop(st, "detail")
            col.prop(st, "radii")
        layout.prop(st, "object_notes")

        ob = context.active_object
        box = self.layout.box()
        if ob is None:
            box.label(text="Click an object to give it a note", icon='INFO')
            return
        box.label(text=ob.name, icon='OBJECT_DATA')
        box.prop(ob, "td_note", text="Note")
        box.prop(ob, "td_own_dims")
        box.prop(ob, "td_no_dims")
        box.operator(TD_OT_note_to_selected.bl_idname, icon='COPYDOWN')


class TD_PT_sheet(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Sheet Information"

    @classmethod
    def poll(cls, context):
        return context.scene.technical_drawings.mode == 'PRODUCTION'

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self._split(self.layout)
        layout.prop(st, "project_name")
        layout.prop(st, "client")
        layout.prop(st, "drawing_title")
        layout.prop(st, "drawn_by")
        layout.prop(st, "logo")
        layout.prop(st, "notes")
        layout.prop(st, "paper")
        layout.prop(st, "fit")


class TD_PT_pictures(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Render Pictures"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.technical_drawings.mode == 'PRODUCTION'

    def draw(self, context):
        st = context.scene.technical_drawings
        row = self.layout.row()
        row.template_list("TD_UL_pictures", "", st, "pictures", st, "picture_index", rows=2)
        col = row.column(align=True)
        col.operator(TD_OT_list_add.bl_idname, icon='ADD', text="").target = "pictures"
        col.operator(TD_OT_list_remove.bl_idname, icon='REMOVE', text="").target = "pictures"
        if 0 <= st.picture_index < len(st.pictures):
            pic = st.pictures[st.picture_index]
            col = self.layout.column()
            col.label(text="Rendered from the camera on export.", icon='INFO')
            col.prop(pic, "path", text="Or Use File")


class TD_PT_swatches(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Pantone Colours"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.technical_drawings.mode == 'PRODUCTION'

    def draw(self, context):
        st = context.scene.technical_drawings
        row = self.layout.row()
        row.template_list("TD_UL_swatches", "", st, "swatches", st, "swatch_index", rows=2)
        col = row.column(align=True)
        col.operator(TD_OT_list_add.bl_idname, icon='ADD', text="").target = "swatches"
        col.operator(TD_OT_list_remove.bl_idname, icon='REMOVE', text="").target = "swatches"


class TD_PT_output(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Files"

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self._split(self.layout)
        col = layout.column(heading="Formats", align=True)
        col.prop(st, "export_pdf")
        col.prop(st, "export_svg")
        if st.mode == 'PRODUCTION':
            col.prop(st, "export_dxf")
            col.prop(st, "export_cnc")
        layout.prop(st, "output_dir")
        layout.prop(st, "file_name")
        layout.prop(st, "open_after")


classes = (
    TD_Swatch, TD_Picture, TD_Settings,
    TD_OT_export, TD_OT_list_add, TD_OT_list_remove, TD_OT_note_to_selected,
    TD_UL_swatches, TD_UL_pictures,
    TD_PT_main, TD_PT_quotation, TD_PT_views, TD_PT_dimensions, TD_PT_sheet,
    TD_PT_pictures, TD_PT_swatches, TD_PT_output,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.technical_drawings = PointerProperty(type=TD_Settings)
    bpy.types.Object.td_note = StringProperty(
        name="Technical Note",
        description="Text shown with an arrow pointing at this object, e.g. STICKER or WARM COB LIGHT")
    bpy.types.Object.td_own_dims = BoolProperty(
        name="Own Dimensions",
        description="Always dimension this object: its edges are kept in the production chains, "
                    "and it gets its own width, depth and height on quotation pictures")


    bpy.types.Object.td_no_dims = BoolProperty(
        name="Decoration (No Dimensions)",
        description="Draw this object but never dimension it. Use for logos and graphics. "
                    "Text objects are treated this way automatically")


def unregister():
    del bpy.types.Object.td_no_dims
    del bpy.types.Object.td_own_dims
    del bpy.types.Object.td_note
    del bpy.types.Scene.technical_drawings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
