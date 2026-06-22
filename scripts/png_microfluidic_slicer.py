#!/usr/bin/env python3
"""Trace black regions in a PNG and emit one-layer G-code for slide printing."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure


SLIDE_WIDTH_MM = 75.0
SLIDE_HEIGHT_MM = 25.0


@dataclass
class Path2D:
    points: list[tuple[float, float]]

    @property
    def length(self) -> float:
        return sum(dist(a, b) for a, b in zip(self.points, self.points[1:]))


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate preview and G-code paths around black PNG regions."
    )
    p.add_argument("input_png", type=Path)
    p.add_argument("--out-gcode", type=Path, default=Path("output/slide_trace.gcode"))
    p.add_argument("--preview", type=Path, default=Path("output/slide_trace_preview.png"))
    p.add_argument("--slide-width", type=float, default=SLIDE_WIDTH_MM)
    p.add_argument("--slide-height", type=float, default=SLIDE_HEIGHT_MM)
    p.add_argument("--x0", type=float, default=72.5, help="slide left edge in printer coordinates")
    p.add_argument("--y0", type=float, default=97.5, help="slide bottom edge in printer coordinates")
    p.add_argument("--threshold", type=int, default=128)
    p.add_argument("--offset", type=float, default=0.25, help="positive expands away from black area")
    p.add_argument("--perimeters", type=int, default=1)
    p.add_argument("--perimeter-spacing", type=float, default=0.45)
    p.add_argument("--z-height", type=float, default=0.18)
    p.add_argument("--feedrate", type=float, default=900.0)
    p.add_argument("--travel-feedrate", type=float, default=3000.0)
    p.add_argument("--nozzle-temp", type=int, default=205)
    p.add_argument("--bed-temp", type=int, default=0)
    p.add_argument("--filament-diameter", type=float, default=1.75)
    p.add_argument("--line-width", type=float, default=0.45)
    p.add_argument("--layer-height", type=float, default=0.18)
    p.add_argument("--flow", type=float, default=0.75, help="extrusion multiplier")
    p.add_argument("--prime-mm", type=float, default=0.0)
    p.add_argument("--retract-mm", type=float, default=0.7)
    p.add_argument("--min-contour-mm", type=float, default=1.0)
    p.add_argument("--probe", action="store_true", help="probe slide center before printing")
    p.add_argument(
        "--probe-with-g30",
        action="store_true",
        help="after homing, run an extra G30 probe at the slide center",
    )
    p.add_argument("--probe-z-offset", type=float, default=0.0)
    p.add_argument("--safe-z", type=float, default=8.0)
    p.add_argument("--heat-park-x", type=float, default=None)
    p.add_argument("--heat-park-y", type=float, default=None)
    p.add_argument("--heat-park-z", type=float, default=20.0)
    p.add_argument("--port", choices=["top-right", "none"], default="top-right")
    p.add_argument("--port-length", type=float, default=8.0)
    p.add_argument(
        "--brim",
        type=int,
        default=0,
        help="draw this many concentric priming rectangles around all traced paths",
    )
    p.add_argument("--brim-margin", type=float, default=1.0)
    p.add_argument("--brim-spacing", type=float, default=1.0)
    return p.parse_args()


def load_mask(path: Path, threshold: int) -> tuple[np.ndarray, Image.Image]:
    img = Image.open(path).convert("L")
    mask = np.array(img) < threshold
    return mask, img.convert("RGB")


def contour_paths(
    mask: np.ndarray,
    slide_width: float,
    slide_height: float,
    offset_mm: float,
    perimeters: int,
    spacing: float,
    min_len: float,
) -> list[Path2D]:
    h, w = mask.shape
    px_mm = slide_width / w
    fit_height = h * px_mm
    if fit_height > slide_height:
        raise SystemExit(
            f"Image fits to {slide_width:.1f} mm wide but becomes {fit_height:.1f} mm tall; "
            f"slide height is {slide_height:.1f} mm."
        )
    y_margin = (slide_height - fit_height) / 2.0

    paths: list[Path2D] = []
    for perimeter_i in range(perimeters):
        effective_offset = offset_mm + perimeter_i * spacing
        offset_mask = offset_binary_mask(mask, effective_offset / px_mm)
        for contour in measure.find_contours(offset_mask.astype(float), 0.5):
            pts: list[tuple[float, float]] = []
            for row, col in contour:
                x = (col + 0.5) * px_mm
                y = slide_height - (y_margin + (row + 0.5) * px_mm)
                pts.append((x, y))
            if pts and dist(pts[0], pts[-1]) > px_mm * 2:
                pts.append(pts[0])
            path = simplify_path(Path2D(pts), tolerance=px_mm * 0.75)
            if path.length >= min_len:
                paths.append(orient_start(path))
    paths.sort(key=lambda path: (-path.length, path.points[0][1], -path.points[0][0]))
    return paths


def offset_binary_mask(mask: np.ndarray, offset_px: float) -> np.ndarray:
    """Offset a binary image by Euclidean distance in pixel units."""
    if abs(offset_px) < 0.5:
        return mask
    if offset_px > 0:
        return ndimage.distance_transform_edt(~mask) <= offset_px
    return ndimage.distance_transform_edt(mask) > abs(offset_px)


def simplify_path(path: Path2D, tolerance: float) -> Path2D:
    pts = path.points
    if len(pts) < 3:
        return path
    closed = pts[0] == pts[-1]
    work = pts[:-1] if closed else pts
    out = rdp(work, tolerance)
    if closed and out[0] != out[-1]:
        out.append(out[0])
    return Path2D(out)


def rdp(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points[:]
    start = points[0]
    end = points[-1]
    max_dist = -1.0
    max_idx = 0
    for idx, pt in enumerate(points[1:-1], start=1):
        d = point_line_distance(pt, start, end)
        if d > max_dist:
            max_dist = d
            max_idx = idx
    if max_dist > tolerance:
        left = rdp(points[: max_idx + 1], tolerance)
        right = rdp(points[max_idx:], tolerance)
        return left[:-1] + right
    return [start, end]


def point_line_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    if start == end:
        return dist(point, start)
    px, py = point
    sx, sy = start
    ex, ey = end
    numerator = abs((ey - sy) * px - (ex - sx) * py + ex * sy - ey * sx)
    denominator = math.hypot(ey - sy, ex - sx)
    return numerator / denominator


def orient_start(path: Path2D) -> Path2D:
    pts = path.points[:-1] if path.points[0] == path.points[-1] else path.points[:]
    idx = max(range(len(pts)), key=lambda i: (pts[i][1], pts[i][0]))
    rotated = pts[idx:] + pts[:idx] + [pts[idx]]
    return Path2D(rotated)


def extrusion_per_mm(args: argparse.Namespace) -> float:
    filament_area = math.pi * (args.filament_diameter / 2.0) ** 2
    bead_area = args.line_width * args.layer_height
    return bead_area / filament_area * args.flow


def add_port(path: Path2D, args: argparse.Namespace) -> Path2D:
    if args.port == "none" or not path.points:
        return path
    start = path.points[0]
    return Path2D([(start[0] + args.port_length, start[1] + args.port_length)] + path.points)


def brimmed_paths(paths: list[Path2D], args: argparse.Namespace) -> list[Path2D]:
    if args.brim <= 0:
        return paths
    min_x, min_y, max_x, max_y = path_bounds(paths)
    rectangles: list[tuple[float, float, float, float]] = []
    for i in range(args.brim):
        margin = args.brim_margin + (args.brim - 1 - i) * args.brim_spacing
        rectangles.append(
            (
                max(0.0, min_x - margin),
                max(0.0, min_y - margin),
                min(args.slide_width, max_x + margin),
                min(args.slide_height, max_y + margin),
            )
        )

    first = paths[0]
    points: list[tuple[float, float]] = []
    for min_rx, min_ry, max_rx, max_ry in rectangles:
        rect = [
            (max_rx, max_ry),
            (max_rx, min_ry),
            (min_rx, min_ry),
            (min_rx, max_ry),
            (max_rx, max_ry),
        ]
        if points:
            points.append(rect[0])
        points.extend(rect)
    points.extend(first.points)
    return [Path2D(points)] + paths[1:]


def path_bounds(paths: list[Path2D]) -> tuple[float, float, float, float]:
    xs = [x for path in paths for x, _ in path.points]
    ys = [y for path in paths for _, y in path.points]
    return min(xs), min(ys), max(xs), max(ys)


def write_gcode(paths: list[Path2D], args: argparse.Namespace) -> None:
    args.out_gcode.parent.mkdir(parents=True, exist_ok=True)
    e_per_mm = extrusion_per_mm(args)

    def line(s: str) -> str:
        return s + "\n"

    with args.out_gcode.open("w") as f:
        f.write(line("; generated by png_microfluidic_slicer.py"))
        f.write(line("; WARNING: experimental glass-slide printing G-code"))
        f.write(line("M140 S%d" % args.bed_temp))
        f.write(line("G90"))
        f.write(line("M83"))
        f.write(line("G28"))
        if args.probe and args.probe_with_g30:
            cx = args.x0 + args.slide_width / 2.0
            cy = args.y0 + args.slide_height / 2.0
            f.write(line(f"G0 Z{args.safe_z:.3f} F{args.travel_feedrate:.0f}"))
            f.write(line(f"G0 X{cx:.3f} Y{cy:.3f} F{args.travel_feedrate:.0f}"))
            f.write(line("G30"))
            if args.probe_z_offset:
                f.write(line(f"G92 Z{args.probe_z_offset:.3f}"))
        f.write(line(f"G0 Z{args.safe_z:.3f} F{args.travel_feedrate:.0f}"))
        if args.heat_park_x is not None and args.heat_park_y is not None:
            f.write(line(f"G0 X{args.heat_park_x:.3f} Y{args.heat_park_y:.3f} F{args.travel_feedrate:.0f}"))
            f.write(line(f"G0 Z{args.heat_park_z:.3f} F{args.travel_feedrate:.0f}"))
        f.write(line("M104 S%d" % args.nozzle_temp))
        if args.bed_temp > 0:
            f.write(line("M190 S%d" % args.bed_temp))
        f.write(line("M109 S%d" % args.nozzle_temp))
        f.write(line("G92 E0"))
        if args.prime_mm > 0:
            f.write(line(f"G1 E{args.prime_mm:.4f} F180"))
            f.write(line("G92 E0"))

        for path_i, path in enumerate(brimmed_paths(paths, args)):
            p = add_port(path, args) if path_i == 0 else path
            start = p.points[0]
            f.write(line(f"G0 Z{args.safe_z:.3f} F{args.travel_feedrate:.0f}"))
            f.write(line(f"G0 X{args.x0 + start[0]:.3f} Y{args.y0 + start[1]:.3f} F{args.travel_feedrate:.0f}"))
            f.write(line(f"G0 Z{args.z_height:.3f} F600"))
            f.write(line("G92 E0"))
            last = start
            for pt in p.points[1:]:
                seg = dist(last, pt)
                e_delta = seg * e_per_mm
                if e_delta <= 0:
                    last = pt
                    continue
                f.write(
                    line(
                        f"G1 X{args.x0 + pt[0]:.3f} Y{args.y0 + pt[1]:.3f} "
                        f"E{e_delta:.5f} F{args.feedrate:.0f}"
                    )
                )
                last = pt
            f.write(line(f"G1 E{-args.retract_mm:.4f} F1200"))
        f.write(line(f"G0 Z{args.safe_z:.3f} F{args.travel_feedrate:.0f}"))
        f.write(line("M104 S0"))
        f.write(line("M140 S0"))
        f.write(line("M84"))


def draw_preview(img: Image.Image, paths: list[Path2D], args: argparse.Namespace) -> None:
    args.preview.parent.mkdir(parents=True, exist_ok=True)
    w, h = img.size
    px_per_mm = w / args.slide_width
    fit_height_px = args.slide_height * px_per_mm
    canvas_h = int(round(fit_height_px))
    y_pad = max(0, (canvas_h - h) // 2)
    canvas = Image.new("RGB", (w, canvas_h), "white")
    canvas.paste(img, (0, y_pad))
    draw = ImageDraw.Draw(canvas)

    def to_px(pt: tuple[float, float]) -> tuple[int, int]:
        return (round(pt[0] * px_per_mm), round((args.slide_height - pt[1]) * px_per_mm))

    for path_i, path in enumerate(brimmed_paths(paths, args)):
        p = add_port(path, args) if path_i == 0 else path
        draw.line([to_px(pt) for pt in p.points], fill=(230, 0, 0), width=max(2, round(px_per_mm * 0.25)))
    canvas.save(args.preview)


def main() -> None:
    args = parse_args()
    mask, img = load_mask(args.input_png, args.threshold)
    paths = contour_paths(
        mask,
        args.slide_width,
        args.slide_height,
        args.offset,
        args.perimeters,
        args.perimeter_spacing,
        args.min_contour_mm,
    )
    if not paths:
        raise SystemExit("No black-region contours found.")
    draw_preview(img, paths, args)
    write_gcode(paths, args)
    print(f"wrote {args.out_gcode}")
    print(f"wrote {args.preview}")
    print(f"paths: {len(paths)}, longest: {paths[0].length:.1f} mm")


if __name__ == "__main__":
    main()
