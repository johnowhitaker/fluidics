"""Vector design rasterization, contour extraction, and one-layer G-code output.

The editor works in microscope-slide millimetres with an origin at the top-left.
Printer paths use the conventional bottom-left origin and are translated onto the
printer bed only while G-code is written.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure


class DesignError(ValueError):
    """A design or fabrication setting cannot be sliced safely."""


@dataclass
class Path2D:
    points: list[tuple[float, float]]
    kind: str = "part"
    lead_in: tuple[tuple[float, float], tuple[float, float]] | None = None
    lead_out: tuple[tuple[float, float], tuple[float, float]] | None = None

    @property
    def length(self) -> float:
        return sum(distance(a, b) for a, b in zip(self.points, self.points[1:]))


@dataclass
class SliceSettings:
    slide_width: float = 75.0
    slide_height: float = 25.0
    resolution_px_per_mm: float = 24.0
    offset: float = 0.25
    perimeters: int = 1
    perimeter_spacing: float = 0.45
    min_contour_mm: float = 0.8
    simplify_tolerance_mm: float = 0.035

    x0: float = 72.5
    y0: float = 97.5
    z_height: float = 0.18
    print_feedrate: float = 900.0
    travel_feedrate: float = 3000.0
    z_feedrate: float = 600.0

    nozzle_temp: int = 205
    bed_temp: int = 0
    filament_diameter: float = 1.75
    extrusion_line_width: float = 0.45
    layer_height: float = 0.18
    flow: float = 0.75
    fan_percent: int = 0

    prime_mm: float = 0.0
    prime_line: float = 0.0
    retract_mm: float = 0.7
    retract_feedrate: float = 1200.0
    safe_z: float = 8.0
    home_axes: bool = True
    probe_at_center: bool = False
    probe_z_offset: float = 0.0

    heat_park_enabled: bool = False
    heat_park_x: float = 158.0
    heat_park_y: float = 135.0
    heat_park_z: float = 25.0
    end_park_enabled: bool = False
    end_park_x: float = 158.0
    end_park_y: float = 135.0

    brim_count: int = 0
    brim_margin: float = 1.0
    brim_spacing: float = 1.0


def settings_from_dict(raw: dict[str, Any] | None) -> SliceSettings:
    raw = raw or {}
    allowed = {field.name for field in fields(SliceSettings)}
    values = {key: value for key, value in raw.items() if key in allowed}
    settings = SliceSettings(**values)
    validate_settings(settings)
    return settings


def validate_settings(s: SliceSettings) -> None:
    positive = {
        "slide width": s.slide_width,
        "slide height": s.slide_height,
        "raster resolution": s.resolution_px_per_mm,
        "perimeter spacing": s.perimeter_spacing,
        "print feedrate": s.print_feedrate,
        "travel feedrate": s.travel_feedrate,
        "Z feedrate": s.z_feedrate,
        "filament diameter": s.filament_diameter,
        "extrusion line width": s.extrusion_line_width,
        "layer height": s.layer_height,
        "flow": s.flow,
        "safe Z": s.safe_z,
    }
    for label, value in positive.items():
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise DesignError(f"{label} must be greater than zero")
    if not 1 <= int(s.perimeters) <= 12:
        raise DesignError("perimeters must be between 1 and 12")
    if not 0 <= int(s.brim_count) <= 12:
        raise DesignError("brim count must be between 0 and 12")
    if not -10 <= float(s.offset) <= 10:
        raise DesignError("offset must be between -10 and 10 mm")
    if not 0 < float(s.z_height) <= 5:
        raise DesignError("print Z height must be between 0 and 5 mm")
    if not 0 <= int(s.nozzle_temp) <= 320 or not 0 <= int(s.bed_temp) <= 150:
        raise DesignError("temperature is outside the supported range")
    if not 0 <= int(s.fan_percent) <= 100:
        raise DesignError("fan percentage must be between 0 and 100")
    if not math.isfinite(float(s.prime_line)) or not 0 <= float(s.prime_line) <= 10:
        raise DesignError("prime line must be between 0 and 10 mm")
    pixel_count = s.slide_width * s.slide_height * s.resolution_px_per_mm**2
    if pixel_count > 8_000_000:
        raise DesignError("slide size and raster resolution produce an oversized job")


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DesignError(f"{label} must be a number") from exc
    if not math.isfinite(number):
        raise DesignError(f"{label} must be finite")
    return number


def _point(raw: Any, label: str) -> tuple[float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise DesignError(f"{label} must contain x and y")
    return (_finite_number(raw[0], f"{label} x"), _finite_number(raw[1], f"{label} y"))


def _scaled_point(point: tuple[float, float], scale: float) -> tuple[int, int]:
    return (round(point[0] * scale), round(point[1] * scale))


def _round_stroke(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    width_mm: float,
    scale: float,
) -> None:
    if len(points) < 2:
        return
    width_px = max(1, round(width_mm * scale))
    pixel_points = [_scaled_point(point, scale) for point in points]
    draw.line(pixel_points, fill=255, width=width_px, joint="curve")
    radius = width_px / 2
    for x, y in (pixel_points[0], pixel_points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)


def _arc_points(
    cx: float,
    cy: float,
    radius: float,
    start_angle: float,
    sweep_angle: float,
) -> list[tuple[float, float]]:
    segments = max(12, math.ceil(abs(sweep_angle) * max(radius, 1) / 3.0))
    return [
        (
            cx + radius * math.cos(math.radians(start_angle + sweep_angle * i / segments)),
            cy + radius * math.sin(math.radians(start_angle + sweep_angle * i / segments)),
        )
        for i in range(segments + 1)
    ]


def render_design_mask(
    design: dict[str, Any], settings: SliceSettings
) -> tuple[np.ndarray, list[str]]:
    """Render printable channel volumes into a high-resolution binary mask."""

    scale = settings.resolution_px_per_mm
    size = (round(settings.slide_width * scale), round(settings.slide_height * scale))
    image = Image.new("L", size, 0)
    draw = ImageDraw.Draw(image)
    warnings: list[str] = []
    shapes = design.get("shapes", []) if isinstance(design, dict) else []
    if not isinstance(shapes, list):
        raise DesignError("design shapes must be a list")

    printable_count = 0
    for index, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            raise DesignError(f"shape {index + 1} is invalid")
        shape_type = shape.get("type")
        if shape_type == "guide":
            continue
        label = f"shape {index + 1}"
        width = _finite_number(shape.get("width", 0.6), f"{label} width")
        if width <= 0 or width > max(settings.slide_width, settings.slide_height):
            raise DesignError(f"{label} width is outside the supported range")

        if shape_type == "line":
            points = [
                (_finite_number(shape.get("x1"), f"{label} x1"), _finite_number(shape.get("y1"), f"{label} y1")),
                (_finite_number(shape.get("x2"), f"{label} x2"), _finite_number(shape.get("y2"), f"{label} y2")),
            ]
            _round_stroke(draw, points, width, scale)
        elif shape_type == "freehand":
            points = [_point(point, f"{label} point") for point in shape.get("points", [])]
            if len(points) < 2:
                continue
            _round_stroke(draw, points, width, scale)
        elif shape_type == "arc":
            cx = _finite_number(shape.get("cx"), f"{label} center x")
            cy = _finite_number(shape.get("cy"), f"{label} center y")
            radius = _finite_number(shape.get("radius"), f"{label} radius")
            start = _finite_number(shape.get("startAngle", 0), f"{label} start angle")
            sweep = _finite_number(shape.get("sweepAngle", 90), f"{label} sweep angle")
            if radius <= 0 or abs(sweep) < 0.1 or abs(sweep) > 360:
                raise DesignError(f"{label} arc radius or sweep is invalid")
            _round_stroke(draw, _arc_points(cx, cy, radius, start, sweep), width, scale)
        elif shape_type == "circle":
            cx = _finite_number(shape.get("cx"), f"{label} center x")
            cy = _finite_number(shape.get("cy"), f"{label} center y")
            radius = _finite_number(shape.get("radius"), f"{label} radius")
            if radius <= 0:
                raise DesignError(f"{label} radius must be greater than zero")
            box = tuple(round(value * scale) for value in (cx - radius, cy - radius, cx + radius, cy + radius))
            if shape.get("mode", "chamber") == "ring":
                draw.ellipse(box, outline=255, width=max(1, round(width * scale)))
            else:
                draw.ellipse(box, fill=255)
        else:
            raise DesignError(f"{label} has unsupported type {shape_type!r}")

        printable_count += 1
        bounds = shape_bounds(shape)
        if bounds and (
            bounds[0] < 0
            or bounds[1] < 0
            or bounds[2] > settings.slide_width
            or bounds[3] > settings.slide_height
        ):
            warnings.append(f"{shape.get('name') or label} extends beyond the slide and will be clipped")

    if printable_count == 0:
        raise DesignError("Add at least one printable channel or chamber")
    return np.asarray(image, dtype=np.uint8) > 0, warnings


def shape_bounds(shape: dict[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        width = float(shape.get("width", 0.6)) / 2
        if shape.get("type") == "line":
            xs = [float(shape["x1"]), float(shape["x2"])]
            ys = [float(shape["y1"]), float(shape["y2"])]
            return min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width
        if shape.get("type") == "freehand":
            points = shape.get("points", [])
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            return min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width
        if shape.get("type") == "circle":
            cx, cy, radius = float(shape["cx"]), float(shape["cy"]), float(shape["radius"])
            pad = width if shape.get("mode") == "ring" else 0
            return cx - radius - pad, cy - radius - pad, cx + radius + pad, cy + radius + pad
        if shape.get("type") == "arc":
            points = _arc_points(
                float(shape["cx"]),
                float(shape["cy"]),
                float(shape["radius"]),
                float(shape.get("startAngle", 0)),
                float(shape.get("sweepAngle", 90)),
            )
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width
    except (KeyError, TypeError, ValueError):
        return None
    return None


def offset_binary_mask(mask: np.ndarray, offset_px: float) -> np.ndarray:
    if abs(offset_px) < 0.5:
        return mask
    if offset_px > 0:
        return ndimage.distance_transform_edt(~mask) <= offset_px
    return ndimage.distance_transform_edt(mask) > abs(offset_px)


def _contour_to_path(
    contour: np.ndarray, settings: SliceSettings, kind: str = "part"
) -> Path2D:
    scale = settings.resolution_px_per_mm
    simplified = measure.approximate_polygon(
        contour, tolerance=max(0.5, settings.simplify_tolerance_mm * scale)
    )
    points = [
        ((float(col) + 0.5) / scale, settings.slide_height - (float(row) + 0.5) / scale)
        for row, col in simplified
    ]
    if points and distance(points[0], points[-1]) > 1.5 / scale:
        points.append(points[0])
    return Path2D(points, kind=kind)


def _unit_vector(
    start: tuple[float, float], end: tuple[float, float]
) -> tuple[float, float] | None:
    length = distance(start, end)
    if length <= 1e-9:
        return None
    return ((end[0] - start[0]) / length, (end[1] - start[1]) / length)


def _mask_sample(
    mask: np.ndarray, point: tuple[float, float], settings: SliceSettings
) -> tuple[bool, bool]:
    """Return whether a slide-coordinate point is in bounds and in channel space."""

    x, y = point
    in_bounds = 0 <= x <= settings.slide_width and 0 <= y <= settings.slide_height
    if not in_bounds:
        return False, False
    scale = settings.resolution_px_per_mm
    col = min(mask.shape[1] - 1, max(0, round(x * scale)))
    row = min(mask.shape[0] - 1, max(0, round((settings.slide_height - y) * scale)))
    return True, bool(mask[row, col])


def _map_sample(
    values: np.ndarray, point: tuple[float, float], settings: SliceSettings
) -> float:
    x, y = point
    if not (0 <= x <= settings.slide_width and 0 <= y <= settings.slide_height):
        return 0.0
    scale = settings.resolution_px_per_mm
    col = min(values.shape[1] - 1, max(0, round(x * scale)))
    row = min(values.shape[0] - 1, max(0, round((settings.slide_height - y) * scale)))
    return float(values[row, col])


def _lead_segment_score(
    start: tuple[float, float],
    end: tuple[float, float],
    mask: np.ndarray,
    channel_clearance: np.ndarray,
    path_clearance: np.ndarray,
    settings: SliceSettings,
) -> tuple[float, bool]:
    """Rank leads by clearance from channels, print paths, and the slide edge."""

    score = 0.0
    clear = True
    for index in range(1, 9):
        t = index / 8
        point = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
        in_bounds, in_channel = _mask_sample(mask, point, settings)
        if not in_bounds:
            score -= 30
            clear = False
        elif in_channel:
            score -= 8
            clear = False
        else:
            open_space = _map_sample(channel_clearance, point, settings)
            other_path_space = min(
                _map_sample(path_clearance, point, settings),
                max(settings.slide_width, settings.slide_height),
            )
            score += open_space * (1 + t * 2) + other_path_space * (0.5 + t)
    end_x, end_y = end
    edge_space = min(end_x, settings.slide_width - end_x, end_y, settings.slide_height - end_y)
    endpoint_open_space = _map_sample(channel_clearance, end, settings)
    endpoint_other_path_space = min(
        _map_sample(path_clearance, end, settings),
        max(settings.slide_width, settings.slide_height),
    )
    # The endpoint is the purple dot and the place most likely to collect ooze,
    # so its clearance deliberately dominates the seam ranking.
    score += (
        endpoint_open_space * 25
        + endpoint_other_path_space * 12
        + max(0.0, edge_space) * 0.5
    )
    return score, clear


def _orient_closed_path(
    path: Path2D,
    mask: np.ndarray,
    channel_clearance: np.ndarray,
    path_clearance: np.ndarray,
    settings: SliceSettings,
) -> tuple[Path2D, bool]:
    if len(path.points) < 3 or distance(path.points[0], path.points[-1]) > 1e-6:
        return path, False
    points = path.points[:-1]
    if settings.prime_line <= 0:
        start_index = max(range(len(points)), key=lambda i: (points[i][1], points[i][0]))
        rotated = points[start_index:] + points[:start_index]
        return Path2D(rotated + [rotated[0]], path.kind), False

    candidates: list[tuple[Any, ...]] = []
    lead_length = settings.prime_line
    for index, seam in enumerate(points):
        incoming = _unit_vector(points[index - 1], seam)
        outgoing = _unit_vector(seam, points[(index + 1) % len(points)])
        if incoming is None or outgoing is None:
            continue
        entry = (seam[0] - incoming[0] * lead_length, seam[1] - incoming[1] * lead_length)
        exit_point = (seam[0] + outgoing[0] * lead_length, seam[1] + outgoing[1] * lead_length)
        entry_score, entry_clear = _lead_segment_score(
            seam, entry, mask, channel_clearance, path_clearance, settings
        )
        exit_score, exit_clear = _lead_segment_score(
            seam, exit_point, mask, channel_clearance, path_clearance, settings
        )
        reverse = exit_score > entry_score
        preferred_entry = exit_point if reverse else entry
        preferred_exit = entry if reverse else exit_point
        candidates.append(
            (
                int(entry_clear and exit_clear),
                max(entry_score, exit_score),
                min(entry_score, exit_score),
                seam[1],
                seam[0],
                index,
                preferred_entry,
                preferred_exit,
                reverse,
            )
        )
    if not candidates:
        start_index = max(range(len(points)), key=lambda i: (points[i][1], points[i][0]))
        rotated = points[start_index:] + points[:start_index]
        return Path2D(rotated + [rotated[0]], path.kind), True

    clear_rank, _, _, _, _, start_index, entry, exit_point, reverse = max(candidates)
    if reverse:
        rotated = [points[(start_index - offset) % len(points)] for offset in range(len(points))]
    else:
        rotated = points[start_index:] + points[:start_index]
    seam = rotated[0]
    contour = rotated + [seam]
    return (
        Path2D(
            [entry] + contour + [exit_point],
            path.kind,
            lead_in=(entry, seam),
            lead_out=(seam, exit_point),
        ),
        not bool(clear_rank),
    )


def _path_clearance_map(
    paths: list[Path2D], settings: SliceSettings, exclude_index: int
) -> np.ndarray:
    scale = settings.resolution_px_per_mm
    size = (round(settings.slide_width * scale), round(settings.slide_height * scale))
    image = Image.new("L", size, 0)
    draw = ImageDraw.Draw(image)
    width = max(1, round(settings.extrusion_line_width * scale))

    def to_pixel(point: tuple[float, float]) -> tuple[int, int]:
        return (round(point[0] * scale), round((settings.slide_height - point[1]) * scale))

    drawn = False
    for index, path in enumerate(paths):
        if index == exclude_index:
            continue
        if len(path.points) >= 2:
            draw.line([to_pixel(point) for point in path.points], fill=255, width=width, joint="curve")
            drawn = True
    if not drawn:
        return np.full((size[1], size[0]), max(settings.slide_width, settings.slide_height))
    line_mask = np.asarray(image, dtype=np.uint8) > 0
    return ndimage.distance_transform_edt(~line_mask) / scale


def contour_paths(mask: np.ndarray, settings: SliceSettings) -> tuple[list[Path2D], list[str]]:
    raw_paths: list[tuple[Path2D, np.ndarray, np.ndarray]] = []
    lead_warning_count = 0
    for perimeter_index in range(settings.perimeters):
        effective_offset = settings.offset + perimeter_index * settings.perimeter_spacing
        offset_mask = offset_binary_mask(mask, effective_offset * settings.resolution_px_per_mm)
        channel_clearance = ndimage.distance_transform_edt(~offset_mask) / settings.resolution_px_per_mm
        for contour in measure.find_contours(offset_mask.astype(float), 0.5):
            raw_path = _contour_to_path(contour, settings)
            if len(raw_path.points) >= 3 and raw_path.length >= settings.min_contour_mm:
                raw_paths.append((raw_path, offset_mask, channel_clearance))
    raw_path_list = [entry[0] for entry in raw_paths]
    paths: list[Path2D] = []
    for path_index, (raw_path, offset_mask, channel_clearance) in enumerate(raw_paths):
        path_clearance = _path_clearance_map(raw_path_list, settings, path_index)
        path, lead_warning = _orient_closed_path(
            raw_path, offset_mask, channel_clearance, path_clearance, settings
        )
        paths.append(path)
        lead_warning_count += int(lead_warning)
    paths.sort(key=lambda path: -path.length)
    warnings = []
    if lead_warning_count:
        warnings.append(
            f"{lead_warning_count} lead-in/out pair(s) could not stay entirely on-slide and outside channels; inspect the preview"
        )
    return paths, warnings


def _brim_paths(paths: list[Path2D], settings: SliceSettings) -> list[Path2D]:
    if not paths or settings.brim_count <= 0:
        return []
    xs = [x for path in paths for x, _ in path.points]
    ys = [y for path in paths for _, y in path.points]
    brims: list[Path2D] = []
    for index in reversed(range(settings.brim_count)):
        margin = settings.brim_margin + index * settings.brim_spacing
        left = max(0.0, min(xs) - margin)
        bottom = max(0.0, min(ys) - margin)
        right = min(settings.slide_width, max(xs) + margin)
        top = min(settings.slide_height, max(ys) + margin)
        brims.append(
            Path2D(
                [(right, top), (right, bottom), (left, bottom), (left, top), (right, top)],
                kind="brim",
            )
        )
    return brims


def slice_design(
    design: dict[str, Any], raw_settings: dict[str, Any] | None = None
) -> tuple[list[Path2D], SliceSettings, list[str]]:
    settings = settings_from_dict(raw_settings)
    mask, warnings = render_design_mask(design, settings)
    part_paths, lead_warnings = contour_paths(mask, settings)
    warnings.extend(lead_warnings)
    if not part_paths:
        raise DesignError("No printable contours were found; try a wider channel or smaller negative offset")
    paths = _brim_paths(part_paths, settings) + part_paths
    return paths, settings, warnings


def extrusion_per_mm(settings: SliceSettings) -> float:
    filament_area = math.pi * (settings.filament_diameter / 2) ** 2
    bead_area = settings.extrusion_line_width * settings.layer_height
    return bead_area / filament_area * settings.flow


def _line(value: str) -> str:
    return value + "\n"


def generate_gcode(
    design: dict[str, Any],
    raw_settings: dict[str, Any] | None = None,
    job_name: str = "fluidics-slide",
) -> tuple[str, dict[str, Any], list[str]]:
    paths, settings, warnings = slice_design(design, raw_settings)
    e_per_mm = extrusion_per_mm(settings)
    total_length = sum(path.length for path in paths)
    chunks = [
        _line("; generated by Fluidics Studio"),
        _line(f"; job: {job_name}"),
        _line("; WARNING: verify coordinates, Z height, temperatures, and path preview before printing"),
        _line(f"; slide: {settings.slide_width:.3f} x {settings.slide_height:.3f} mm"),
        _line(f"; paths: {len(paths)}, path length: {total_length:.2f} mm"),
        _line(f"; lead-in/out length: {settings.prime_line:.3f} mm per end"),
        _line(f"M140 S{settings.bed_temp}"),
        _line("G90 ; absolute XYZ"),
        _line("M83 ; relative extrusion"),
    ]
    if settings.home_axes:
        chunks.append(_line("G28"))
    if settings.probe_at_center:
        center_x = settings.x0 + settings.slide_width / 2
        center_y = settings.y0 + settings.slide_height / 2
        chunks.extend(
            [
                _line(f"G0 Z{settings.safe_z:.3f} F{settings.z_feedrate:.0f}"),
                _line(f"G0 X{center_x:.3f} Y{center_y:.3f} F{settings.travel_feedrate:.0f}"),
                _line("G30"),
            ]
        )
        if settings.probe_z_offset:
            chunks.append(_line(f"G92 Z{settings.probe_z_offset:.3f}"))
    chunks.append(_line(f"G0 Z{settings.safe_z:.3f} F{settings.z_feedrate:.0f}"))
    if settings.heat_park_enabled:
        chunks.extend(
            [
                _line(
                    f"G0 X{settings.heat_park_x:.3f} Y{settings.heat_park_y:.3f} "
                    f"F{settings.travel_feedrate:.0f}"
                ),
                _line(f"G0 Z{settings.heat_park_z:.3f} F{settings.z_feedrate:.0f}"),
            ]
        )
    chunks.append(_line(f"M104 S{settings.nozzle_temp}"))
    if settings.bed_temp > 0:
        chunks.append(_line(f"M190 S{settings.bed_temp}"))
    chunks.extend(
        [
            _line(f"M109 S{settings.nozzle_temp}"),
            _line(f"M106 S{round(settings.fan_percent / 100 * 255)}"),
            _line("G92 E0"),
        ]
    )
    if settings.prime_mm > 0:
        chunks.extend(
            [
                _line(f"G1 E{settings.prime_mm:.5f} F180"),
                _line("G92 E0"),
            ]
        )

    for path_index, path in enumerate(paths):
        start_x, start_y = path.points[0]
        chunks.extend(
            [
                _line(f"; {path.kind} path {path_index + 1}"),
                _line(f"G0 Z{settings.safe_z:.3f} F{settings.z_feedrate:.0f}"),
                _line(
                    f"G0 X{settings.x0 + start_x:.3f} Y{settings.y0 + start_y:.3f} "
                    f"F{settings.travel_feedrate:.0f}"
                ),
                _line(f"G0 Z{settings.z_height:.3f} F{settings.z_feedrate:.0f}"),
            ]
        )
        if path_index > 0 and settings.retract_mm > 0:
            chunks.append(_line(f"G1 E{settings.retract_mm:.5f} F{settings.retract_feedrate:.0f}"))
        last = path.points[0]
        for point in path.points[1:]:
            segment_length = distance(last, point)
            if segment_length > 0:
                chunks.append(
                    _line(
                        f"G1 X{settings.x0 + point[0]:.3f} Y{settings.y0 + point[1]:.3f} "
                        f"E{segment_length * e_per_mm:.5f} F{settings.print_feedrate:.0f}"
                    )
                )
            last = point
        if settings.retract_mm > 0:
            chunks.append(_line(f"G1 E{-settings.retract_mm:.5f} F{settings.retract_feedrate:.0f}"))

    chunks.extend(
        [
            _line(f"G0 Z{settings.safe_z:.3f} F{settings.z_feedrate:.0f}"),
            _line("M106 S0"),
            _line("M104 S0"),
            _line("M140 S0"),
        ]
    )
    if settings.end_park_enabled:
        chunks.append(
            _line(
                f"G0 X{settings.end_park_x:.3f} Y{settings.end_park_y:.3f} "
                f"F{settings.travel_feedrate:.0f}"
            )
        )
    chunks.append(_line("M84"))
    stats = path_stats(paths, settings)
    return "".join(chunks), stats, warnings


def path_stats(paths: Iterable[Path2D], settings: SliceSettings) -> dict[str, Any]:
    path_list = list(paths)
    total_length = sum(path.length for path in path_list)
    print_minutes = total_length / settings.print_feedrate if settings.print_feedrate else 0
    return {
        "pathCount": len(path_list),
        "partPathCount": sum(path.kind == "part" for path in path_list),
        "brimPathCount": sum(path.kind == "brim" for path in path_list),
        "pathLengthMm": round(total_length, 2),
        "filamentMm": round(total_length * extrusion_per_mm(settings), 2),
        "estimatedMinutes": round(print_minutes, 2),
    }


def preview_payload(
    design: dict[str, Any], raw_settings: dict[str, Any] | None = None
) -> dict[str, Any]:
    paths, settings, warnings = slice_design(design, raw_settings)
    return {
        "paths": [
            {
                "kind": path.kind,
                "points": [[round(x, 4), round(settings.slide_height - y, 4)] for x, y in path.points],
                "leadIn": (
                    [[round(x, 4), round(settings.slide_height - y, 4)] for x, y in path.lead_in]
                    if path.lead_in
                    else None
                ),
                "leadOut": (
                    [[round(x, 4), round(settings.slide_height - y, 4)] for x, y in path.lead_out]
                    if path.lead_out
                    else None
                ),
            }
            for path in paths
        ],
        "stats": path_stats(paths, settings),
        "warnings": warnings,
        "settings": asdict(settings),
    }
