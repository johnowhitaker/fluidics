# Fluidics Studio

Fluidics Studio is a self-contained local web app for designing channel voids on a
microscope slide, previewing the exact one-layer nozzle contours, generating G-code,
and sending a verified job to OctoPrint.

It lives entirely in this directory and does not import the older project scripts.
The contouring and OctoPrint behavior were brought across and adapted for vector
designs, so this folder can be moved into its own repository later.

## Start it

From the parent `fluidics` repository:

```sh
python3 -m venv fluidics_gui/.venv
source fluidics_gui/.venv/bin/activate
pip install -r fluidics_gui/requirements.txt
python -m fluidics_gui.app
```

Then open <http://127.0.0.1:5000>. The design and printer settings autosave in the
browser. The built-in flow-focusing example makes the preview immediately useful.

If the existing Python environment already has the requirements, only the last
command is needed.

## Editor controls

- Select or move geometry with **V**. Use the inspector for exact millimetre values.
- Draw a straight channel with **L**. Hold **Ctrl** or **Command** to snap its angle
  to 45-degree increments.
- Draw freehand channels with **F**, fixed-radius arcs with **A**, circular chambers
  or ring channels with **C**, and non-printing coverslip guides with **G**.
- Toggle grid snapping and choose the grid pitch in the Design panel.
- Undo/redo with the normal platform shortcuts; duplicate with **Ctrl/Command-D**;
  delete a selected feature with **Delete**.
- Exported `.fluidics.json` files include the design, guides, and fabrication
  settings. OctoPrint credentials are deliberately excluded.

The teal geometry is the intended *fluid void*. The orange overlay is the computed
nozzle centerline around the union of that geometry. Intersections are merged before
contouring, so T-junctions and flow-focusing crosses do not acquire walls through the
middle of the junction.

## Fabrication settings

The Fabrication tab exposes the values that materially affect the generated file:

- channel-wall offset, perimeter count and spacing;
- print Z, modeled bead width, layer height, filament diameter, flow, extruder
  prime, optional tangent lead-in/lead-out length, and retraction;
- print/travel/Z feed rates, nozzle and bed temperatures, and fan percentage;
- slide origin and dimensions, homing, center probing, and probe Z offset;
- separate priming brims, heat-park position, and end-park position.

The preview and material estimate are rebuilt whenever these change. G-code uses
absolute XY positioning and relative extrusion (`M83`). Disconnected contours are
retracted and unretracted independently; brim loops are also independent paths.

## OctoPrint

Open the OctoPrint tab and enter the Pi address and an API key. **Test connection**
checks `/api/printer`. You can then upload, upload and select, or start immediately.
Starting a print requires a second confirmation that the physical setup was checked.
That confirmation can be disabled from the OctoPrint panel or permanently skipped
from the dialog; the choice is stored only in the current browser.

The address and key are stored only in this browser's local storage. They are sent to
the local Flask process when testing or uploading and are not written into design
files or server-side configuration.

## Tests

```sh
python -m pytest fluidics_gui/tests
node --check fluidics_gui/static/app.js
```

The tests cover contour unioning, disconnected paths, brims, retraction behavior,
clipping warnings, G-code downloads, and API error responses.

## Before the first hardware print

This remains experimental machine-control software. Review the orange path, download
and inspect the G-code, confirm the slide's physical X/Y origin, and validate Z height
and nozzle clearance at low risk before allowing unattended movement or heating.
