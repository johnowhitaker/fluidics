# Fluidics slide-printing tools

> **Work in progress:** this is experimental hardware and machine-control
> software. Verify generated paths, printer coordinates, temperatures, nozzle
> clearance, and Z height before running a job.

This project explores fabricating microfluidic chips by printing precise,
single-layer plastic channel walls onto glass microscope slides and thermally
bonding a coverslip on top. Background on the earlier fabrication experiments is
available in [Microfluidics, attempt 1](https://johnowhitaker.dev/mini-hw-projects/microfluidics_1.html).

## Recommended workflow: Fluidics Studio

<img width="1254" height="792" alt="Screenshot 2026-07-22 at 8 35 03 AM" src="https://github.com/user-attachments/assets/159a1591-1f28-4283-918b-a57feb207e09" />


The recommended way to design and print chips is the standalone browser-based
[Fluidics Studio](fluidics_gui/README.md) app in `fluidics_gui/`. It provides a
millimetre-accurate 75 × 25 mm editor, straight/freehand/arc/circle tools,
coverslip guides, snapping, live nozzle-path previews, full fabrication settings,
G-code generation, and direct OctoPrint upload/printing.

```sh
python3 -m venv fluidics_gui/.venv
source fluidics_gui/.venv/bin/activate
pip install -r fluidics_gui/requirements.txt
python -m fluidics_gui.app
```

Then open <http://127.0.0.1:5000>. See the
[Fluidics Studio README](fluidics_gui/README.md) for editor controls, fabrication
parameters, OctoPrint setup, and the pre-print safety checklist.

## Earlier command-line tools

The original PNG-based scripts remain available for reproducing and extending
the earlier workflow. They locate a microscope slide on an Ender 3 V3 SE bed and
generate one-layer G-code from black PNG masks.

## Files

- `cad/slide_holder.scad` - parametric OpenSCAD slide holder.
- `scripts/png_microfluidic_slicer.py` - PNG-to-preview/G-code generator.
- `examples/square.png` - simple test mask.
- `examples/t2.png` - hand-drawn test mask with multiple features.

Generated STL, preview, and G-code files go in `output/`, which is ignored by
git.

### Generate a slide trace

```sh
python3 scripts/png_microfluidic_slicer.py examples/square.png \
  --preview output/square_preview.png \
  --out-gcode output/square_slide_trace.gcode \
  --probe \
  --port-length 10 \
  --heat-park-x 158 --heat-park-y 135 --heat-park-z 25 \
  --z-height 0.2 \
  --flow 0.75 \
  --brim 2 \
  --nozzle-temp 195 \
  --offset 0.1
```

The PNG is fit to the 75 mm slide width. Black pixels are treated as the target
internal volume; red preview lines show where filament will be deposited around
that volume. The generated G-code defaults to a cold bed and can optionally probe
the slide center with `--probe`.

`--brim N` draws N concentric priming rectangles around the design before the
actual perimeter. The printer is put in relative extrusion mode (`M83`), and
generated `E` values are per-segment extrusion deltas.

Upload a generated file with:

```sh
python3 scripts/octoprint_upload.py output/square_slide_trace.gcode --select --print
```

### Drive loose Duet steppers

With the Duet connected over USB and VIN/motor power on:

```sh
python3 scripts/duet_stepper.py status
python3 scripts/duet_stepper.py move --axis X --dir forward --rotations 1 --rpm 20
python3 scripts/duet_stepper.py move --axis Y --dir reverse --rotations 0.5 --rpm 5
python3 scripts/duet_stepper.py pulse --axis X --unit microstep --count 100 --interval-ms 250
python3 scripts/duet_stepper.py pulse --axis Y --unit fullstep --count 20 --interval 1
```

The script auto-detects `/dev/cu.usbmodem*`, queries `M92` for the selected
axis, and sends relative `G1` moves with `M564 S0` so the bench motors can move
without homing. Rotation math assumes a 200 full-step motor and 16 microsteps;
override those with `--steps-per-rev` and `--microsteps` if the hardware differs.
