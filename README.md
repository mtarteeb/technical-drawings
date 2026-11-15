# Technical Drawings (Blender add-on)

Creates technical drawing sheets from the objects you select in Blender.
Geometry only: no AI, works offline, same result every time.

## Install (once per computer)

1. In Blender open **Edit > Preferences > Get Extensions**.
2. Open the **Repositories** drop-down (top right), press **+** and choose **Add Remote Repository**.
3. Paste this URL and tick **Check for Updates on Startup**:

   `https://mtarteeb.github.io/technical-drawings/index.json`

4. Search for **Technical Drawings** in Get Extensions and press **Install**.

Updates then appear inside Blender under Get Extensions; press **Update**.

Requires Blender 4.3 or newer (developed and tested on Blender 5.1).

## Use

1. Select the objects you want to draw. Anything not selected (people, props, the venue) is left out.
2. Open the sidebar in the 3D viewport (press **N**) and choose the **Technicals** tab.
3. Choose **Production** or **Quotation** at the top.
4. Set the options, then press **Export Technicals**.

### Production

A sheet with front, top and side views, automatic dimensions, notes, render pictures,
Pantone swatches and the information strip.

- **Dimensions** are measured from the model: overall sizes, a chain at every long straight edge, radii of arcs.
- **Notes**: click an object, type its note (for example `STICKER`) in *Dimensions and Notes*. It appears with an arrow.
- **Own Dimensions**: tick this on an object whose edges must always be dimensioned.
- **Text objects** are drawn as letter outlines automatically. They stay editable text in the model; nothing is converted.
- **Light strips**: objects with a light-emitting material are drawn in colour.
- **Render pictures**: add a camera under *Render Pictures*; it is rendered with the scene's render settings when you export. A finished render file can be used instead.
- **Files**: PDF, SVG (Illustrator), DXF (AutoCAD, true size, editable dimensions) and CNC outlines (DXF).

### Quotation

Dimensions and notes laid over a finished render, as editable lines and text.

1. Choose the camera. Add the finished render made from it, or leave the file empty to render on export.
2. Tick **Own Dimensions** on the objects that should show their width, depth and height.
   With none ticked, the overall size of the selection is shown.
3. Export as PDF or SVG.

## Releasing an update (maintainers)

1. Raise `version` in `technical_drawings/blender_manifest.toml`.
2. Commit.
3. Run `tools/release.sh`.

## Known limits

- Text on the sheet uses Latin characters only (no Arabic yet).
- Curves become true arcs only where the model's curve is a regular arc; other curves stay as short straight segments.
- Quotation dimensions are not hidden when another object stands in front of them.
- DXF files do not contain the render pictures or filled Pantone swatches.

## License

GPL-3.0-or-later, as required for Blender add-ons.
