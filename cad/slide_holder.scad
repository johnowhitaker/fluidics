// Loose microscope slide locator for printing directly on an Ender 3 bed.
// Units are millimeters. The slide datum is the inside lower-left corner.

$fn = 48;

slide_x = 75.0;
slide_y = 25.0;
slide_clearance = 0.9;

wall = 4.0;
base_thickness = 1.6;
clip_height = 2.2;
clip_lip = 1.0;
corner_radius = 2.0;

finger_gap = 12.0;
front_gap = 18.0;

bed_anchor_hole_d = 4.2;
bed_anchor_margin = 6.0;

inner_x = slide_x + 2 * slide_clearance;
inner_y = slide_y + 2 * slide_clearance;
outer_x = inner_x + 2 * wall;
outer_y = inner_y + 2 * wall;

module rounded_rect(size, r) {
    hull() {
        translate([r, r]) circle(r = r);
        translate([size[0] - r, r]) circle(r = r);
        translate([size[0] - r, size[1] - r]) circle(r = r);
        translate([r, size[1] - r]) circle(r = r);
    }
}

module frame_2d() {
    difference() {
        rounded_rect([outer_x, outer_y], corner_radius);
        translate([wall, wall])
            square([inner_x, inner_y], center = false);

        // Front access gap for sliding the glass in and pushing it out.
        translate([outer_x / 2 - front_gap / 2, -0.1])
            square([front_gap, wall + 0.2], center = false);

        // Side finger reliefs.
        translate([-0.1, outer_y / 2 - finger_gap / 2])
            square([wall + 0.2, finger_gap], center = false);
        translate([outer_x - wall - 0.1, outer_y / 2 - finger_gap / 2])
            square([wall + 0.2, finger_gap], center = false);
    }
}

module low_clip(x, y, rot) {
    translate([x, y, base_thickness - 0.05])
        rotate([0, 0, rot])
            linear_extrude(clip_height + 0.05)
                polygon(points = [
                    [0, 0],
                    [8, 0],
                    [8, wall],
                    [clip_lip, wall],
                    [clip_lip, wall + clip_lip],
                    [0, wall + clip_lip]
                ]);
}

module slide_holder() {
    difference() {
        union() {
            linear_extrude(base_thickness) frame_2d();

            // Four low overhangs. They should locate without pinching; shim later.
            low_clip(wall + 8, wall - clip_lip, 0);
            low_clip(outer_x - wall - 16, wall - clip_lip, 0);
            low_clip(wall + 8, outer_y - wall + clip_lip, 180);
            low_clip(outer_x - wall - 16, outer_y - wall + clip_lip, 180);

            // Raised datum nubs against the left and rear edges.
            translate([wall - 0.6, wall + 4, base_thickness])
                cube([0.8, 7, clip_height]);
            translate([wall - 0.6, outer_y - wall - 11, base_thickness])
                cube([0.8, 7, clip_height]);
            translate([wall + 4, outer_y - wall - 0.2, base_thickness])
                cube([10, 0.8, clip_height]);
            translate([outer_x - wall - 14, outer_y - wall - 0.2, base_thickness])
                cube([10, 0.8, clip_height]);
        }

        // Optional screw/tape registration holes outside the slide area.
        translate([bed_anchor_margin, bed_anchor_margin, -0.1])
            cylinder(h = base_thickness + clip_height + 0.3, d = bed_anchor_hole_d);
        translate([outer_x - bed_anchor_margin, bed_anchor_margin, -0.1])
            cylinder(h = base_thickness + clip_height + 0.3, d = bed_anchor_hole_d);
    }
}

slide_holder();
