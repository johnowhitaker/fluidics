from __future__ import annotations

import re

import pytest

from fluidics_gui.slicer import DesignError, generate_gcode, preview_payload, slice_design


def line(x1=5, y1=5, x2=20, y2=5, width=1):
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "width": width}


def test_intersecting_channels_are_unioned_into_one_outer_contour():
    design = {
        "shapes": [
            line(10, 12.5, 60, 12.5, 1),
            line(35, 4, 35, 21, 1),
        ]
    }
    result = preview_payload(design, {"offset": 0.2})

    assert result["stats"]["partPathCount"] == 1
    assert result["stats"]["pathLengthMm"] > 100
    assert all(path["kind"] == "part" for path in result["paths"])


def test_guides_are_ignored_and_disconnected_channels_create_separate_paths():
    design = {
        "shapes": [line(5, 5, 20, 5), line(50, 20, 65, 20)],
        "guides": [
            {"type": "guide", "x": 37.5, "y": 12.5, "width": 18, "height": 18, "rotation": 45}
        ],
    }
    paths, _, _ = slice_design(design, {})

    assert len(paths) == 2
    assert all(path.kind == "part" for path in paths)


def test_brims_are_independent_paths_and_counted():
    design = {"shapes": [line(20, 12.5, 55, 12.5)]}
    result = preview_payload(design, {"brim_count": 2})

    assert result["stats"]["brimPathCount"] == 2
    assert result["stats"]["pathCount"] == 3
    assert [path["kind"] for path in result["paths"][:2]] == ["brim", "brim"]


def test_prime_line_adds_visible_one_mm_lead_in_and_out_to_part_path():
    design = {"shapes": [line(20, 12.5, 55, 12.5)]}
    without_leads = preview_payload(design, {"prime_line": 0})
    with_leads = preview_payload(design, {"prime_line": 1})

    path = with_leads["paths"][0]
    assert path["leadIn"] is not None
    assert path["leadOut"] is not None
    assert path["points"][0] == path["leadIn"][0]
    assert path["points"][-1] == path["leadOut"][-1]
    assert pytest.approx(1, abs=0.001) == _segment_length(path["leadIn"])
    assert pytest.approx(1, abs=0.001) == _segment_length(path["leadOut"])
    assert pytest.approx(2, abs=0.02) == (
        with_leads["stats"]["pathLengthMm"] - without_leads["stats"]["pathLengthMm"]
    )
    assert with_leads["warnings"] == []


def test_prime_line_entry_prefers_clear_space_away_from_neighboring_paths():
    design = {
        "shapes": [
            line(20, 10, 55, 10),
            line(20, 14, 55, 14),
        ]
    }
    result = preview_payload(design, {"prime_line": 1})

    assert len(result["paths"]) == 2
    for path in result["paths"]:
        entry_y = path["leadIn"][0][1]
        seam_y = path["leadIn"][1][1]
        if seam_y < 12:
            assert entry_y < seam_y  # upper channel leads farther upward
        else:
            assert entry_y > seam_y  # lower channel leads farther downward


def _segment_length(segment):
    return ((segment[1][0] - segment[0][0]) ** 2 + (segment[1][1] - segment[0][1]) ** 2) ** 0.5


def test_gcode_uses_relative_extrusion_and_unretracts_between_paths():
    design = {"shapes": [line(5, 5, 20, 5), line(50, 20, 65, 20)]}
    gcode, stats, _ = generate_gcode(design, {"retract_mm": 0.8}, "two paths")

    assert "M83 ; relative extrusion" in gcode
    assert stats["pathCount"] == 2
    assert gcode.count("G1 E-0.80000 F1200") == 2
    assert gcode.count("G1 E0.80000 F1200") == 1
    extrusion_moves = re.findall(r"^G1 X.* E([0-9.]+) ", gcode, flags=re.MULTILINE)
    assert extrusion_moves
    assert all(float(value) > 0 for value in extrusion_moves)


def test_out_of_bounds_shape_is_clipped_with_warning():
    result = preview_payload({"shapes": [line(-2, 5, 10, 5)]}, {})
    assert result["warnings"]
    assert "clipped" in result["warnings"][0]


def test_empty_design_is_rejected():
    with pytest.raises(DesignError, match="at least one printable"):
        preview_payload({"shapes": []}, {})


def test_prime_line_outside_supported_range_is_rejected():
    with pytest.raises(DesignError, match="prime line"):
        preview_payload({"shapes": [line()]}, {"prime_line": -1})
