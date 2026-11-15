"""Technical Drawings: production technical sheets from selected objects.

Workflow: select the objects to draw, set the options in the sidebar panel
(View3D > Sidebar > Technicals), press Export.
"""

import os

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import engine, export_pdf, export_svg, images, sheet


class TD_Swatch(PropertyGroup):
    name: StringProperty(name="Name", default="Pantone 000 C")
    color: FloatVectorProperty(name="Colour", subtype='COLOR', size=3, min=0.0, max=1.0,
                               default=(0.12, 0.27, 0.49))


class TD_Picture(PropertyGroup):
    path: StringProperty(name="Picture", subtype='FILE_PATH',
                         description="A finished render to place on the sheet")


class TD_Settings(PropertyGroup):
    project_name: StringProperty(name="Project Name")
    client: StringProperty(name="Client")
    drawing_title: StringProperty(name="Drawing Title",
                                  description="Name of the element on this sheet, e.g. Entrance Arch")
    drawn_by: StringProperty(name="Drawing By")
    notes: StringProperty(
        name="General Notes",
        description="One note per line; separate notes with a semicolon ( ; )",
        default="ALL DIMENSIONS ARE IN CENTIMETERS UNLESS OTHERWISE SPECIFIED.")

    paper: EnumProperty(name="Paper", default='A3',
                        items=[(k, k + " landscape", "") for k in sheet.PAPER_SIZES])
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

    swatches: CollectionProperty(type=TD_Swatch)
    swatch_index: IntProperty()
    pictures: CollectionProperty(type=TD_Picture)
    picture_index: IntProperty()

    export_pdf: BoolProperty(name="PDF", default=True)
    export_svg: BoolProperty(name="SVG (Illustrator)", default=False)
    output_dir: StringProperty(name="Folder", subtype='DIR_PATH', default="//Technicals/",
                               description="Where the drawings are saved")
    file_name: StringProperty(name="File Name", default="",
                              description="Leave empty to use the drawing title or project name")
    open_after: BoolProperty(name="Open When Done", default=True)


LIST_INDEX = {"swatches": "swatch_index", "pictures": "picture_index"}


def _selected_views(st):
    order = (('FRONT', st.view_front), ('RIGHT', st.view_right), ('LEFT', st.view_left),
             ('BACK', st.view_back), ('TOP', st.view_top))
    return [name for name, on in order if on]


def _safe_name(text):
    keep = "".join(c if c.isalnum() or c in " -_()." else "_" for c in text).strip(" .")
    return keep or "Technical Drawing"


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
        views_wanted = _selected_views(st)
        if not views_wanted:
            self.report({'ERROR'}, "Turn on at least one view.")
            return {'CANCELLED'}
        if not (st.export_pdf or st.export_svg):
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

        try:
            views = engine.extract_views(
                objects, views_wanted, engine.FRONT_DIRECTIONS[st.front_direction],
                frame=context.scene.frame_current, hidden_lines=st.hidden_lines,
                unit_scale=context.scene.unit_settings.scale_length)
        except ValueError as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}

        image_data, pictures, missing = {}, [], []
        for pic in st.pictures:
            if not pic.path:
                continue
            loaded = images.load_jpeg(pic.path)
            if loaded is None:
                missing.append(os.path.basename(pic.path))
                continue
            image_data[pic.path] = loaded
            pictures.append((pic.path, loaded[1], loaded[2]))

        settings = sheet.SheetSettings(
            paper=st.paper, project_name=st.project_name, client=st.client,
            drawing_title=st.drawing_title, drawn_by=st.drawn_by,
            notes=[n.strip() for n in st.notes.replace("\n", ";").split(";")],
            swatches=[(s.name, tuple(s.color)) for s in st.swatches],
            pictures=pictures, hidden_lines=st.hidden_lines)
        sh = sheet.build_sheet(views, settings)

        base = _safe_name(st.file_name or st.drawing_title or st.project_name)
        written = []
        try:
            if st.export_pdf:
                path = os.path.join(out_dir, base + ".pdf")
                export_pdf.write_pdf(path, [sh], image_data)
                written.append(path)
            if st.export_svg:
                path = os.path.join(out_dir, base + ".svg")
                export_svg.write_svg(path, sh, image_data)
                written.append(path)
        except OSError as err:
            self.report({'ERROR'}, "Could not save: %s" % err)
            return {'CANCELLED'}

        if missing:
            self.report({'WARNING'}, "Picture not found: " + ", ".join(missing))
        self.report({'INFO'}, "Saved %d file(s) at scale 1:%d to %s" % (len(written), sh.scale, out_dir))
        if st.open_after and written and not bpy.app.background:
            bpy.ops.wm.path_open(filepath=written[0])
        return {'FINISHED'}


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


class TD_UL_swatches(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "color", text="")
        row.prop(item, "name", text="", emboss=False)


class TD_UL_pictures(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.prop(item, "path", text="")


class TD_PT_base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Technicals"


class TD_PT_main(TD_PT_base, Panel):
    bl_idname = "TD_PT_main"
    bl_label = "Technical Drawings"

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self.layout
        count = sum(1 for o in context.selected_objects if engine.is_drawable(o))
        box = layout.box()
        box.label(text="%d object(s) selected to draw" % count,
                  icon='CHECKMARK' if count else 'ERROR')
        col = layout.column()
        col.scale_y = 1.5
        col.operator(TD_OT_export.bl_idname, icon='EXPORT')


class TD_PT_views(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Views"

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(st, "front_direction")
        col = layout.column(heading="Show", align=True)
        col.prop(st, "view_front")
        col.prop(st, "view_top")
        col.prop(st, "view_right")
        col.prop(st, "view_left")
        col.prop(st, "view_back")
        layout.prop(st, "hidden_lines")


class TD_PT_sheet(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Sheet Information"

    def draw(self, context):
        st = context.scene.technical_drawings
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(st, "project_name")
        layout.prop(st, "client")
        layout.prop(st, "drawing_title")
        layout.prop(st, "drawn_by")
        layout.prop(st, "notes")
        layout.prop(st, "paper")


class TD_PT_pictures(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Render Pictures"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        st = context.scene.technical_drawings
        row = self.layout.row()
        row.template_list("TD_UL_pictures", "", st, "pictures", st, "picture_index", rows=2)
        col = row.column(align=True)
        col.operator(TD_OT_list_add.bl_idname, icon='ADD', text="").target = "pictures"
        col.operator(TD_OT_list_remove.bl_idname, icon='REMOVE', text="").target = "pictures"


class TD_PT_swatches(TD_PT_base, Panel):
    bl_parent_id = "TD_PT_main"
    bl_label = "Pantone Colours"
    bl_options = {'DEFAULT_CLOSED'}

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
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column(heading="Formats", align=True)
        col.prop(st, "export_pdf")
        col.prop(st, "export_svg")
        layout.prop(st, "output_dir")
        layout.prop(st, "file_name")
        layout.prop(st, "open_after")


classes = (
    TD_Swatch, TD_Picture, TD_Settings,
    TD_OT_export, TD_OT_list_add, TD_OT_list_remove,
    TD_UL_swatches, TD_UL_pictures,
    TD_PT_main, TD_PT_views, TD_PT_sheet, TD_PT_pictures, TD_PT_swatches, TD_PT_output,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.technical_drawings = PointerProperty(type=TD_Settings)


def unregister():
    del bpy.types.Scene.technical_drawings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
