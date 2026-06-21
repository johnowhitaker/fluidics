# Fluidics slide-printing tools

Experimental tools for locating a microscope slide on an Ender 3 V3 SE bed and
generating one-layer G-code from black PNG masks.

## Files

- `cad/slide_holder.scad` - parametric OpenSCAD slide holder.
- `output/slide_holder.stl` - generated printable STL.
- `scripts/png_microfluidic_slicer.py` - PNG-to-preview/G-code generator.
- `examples/square.png` - simple test mask.

## Generate a slide trace

```sh
python3 scripts/png_microfluidic_slicer.py examples/square.png \
  --preview output/square_preview.png \
  --out-gcode output/square_slide_trace.gcode \
  --x0 72.5 --y0 97.5 \
  --z-height 0.18 \
  --offset 0.25 \
  --flow 0.75 \
  --bed-temp 0
```

The PNG is fit to the 75 mm slide width. Black pixels are treated as the target
internal volume; red preview lines show where filament will be deposited around
that volume. The generated G-code defaults to a cold bed and can optionally probe
the slide center with `--probe`.
