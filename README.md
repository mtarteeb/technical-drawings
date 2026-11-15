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
3. Set the views, sheet information, render pictures, Pantone colours and file formats.
4. Press **Export Technicals**.

## Releasing an update (maintainers)

1. Raise `version` in `technical_drawings/blender_manifest.toml`.
2. Commit.
3. Run `tools/release.sh`.

## Status

| Feature | State |
| --- | --- |
| Front / top / side / back line views from the selection | Working |
| A-size sheet with information strip, pictures, Pantone swatches | Working |
| PDF and SVG export | Working |
| Automatic dimensions and notes | Not built yet |
| DXF export and CNC outlines | Not built yet |
| Quotation overlay on a render | Not built yet |

## License

GPL-3.0-or-later, as required for Blender add-ons.
