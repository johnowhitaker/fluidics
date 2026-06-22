# Fluidics slide-printing tools

Experimental tools for locating a microscope slide on an Ender 3 V3 SE bed and
generating one-layer G-code from black PNG masks.

## Files

- `cad/slide_holder.scad` - parametric OpenSCAD slide holder.
- `scripts/png_microfluidic_slicer.py` - PNG-to-preview/G-code generator.
- `examples/square.png` - simple test mask.
- `examples/t2.png` - hand-drawn test mask with multiple features.

Generated STL, preview, and G-code files go in `output/`, which is ignored by
git.

## Generate a slide trace

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
