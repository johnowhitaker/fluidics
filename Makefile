PYTHON ?= python3
OPENSCAD ?= openscad

.PHONY: all holder sample check

all: holder sample

holder: output/slide_holder.stl

sample: output/square_slide_trace.gcode output/square_preview.png

output/slide_holder.stl: cad/slide_holder.scad
	mkdir -p output
	$(OPENSCAD) -o $@ $<

output/square_slide_trace.gcode output/square_preview.png: scripts/png_microfluidic_slicer.py examples/square.png
	mkdir -p output
	$(PYTHON) scripts/png_microfluidic_slicer.py examples/square.png \
		--preview output/square_preview.png \
		--out-gcode output/square_slide_trace.gcode

check:
	$(PYTHON) -m py_compile scripts/png_microfluidic_slicer.py scripts/octoprint_upload.py scripts/duet_stepper.py
