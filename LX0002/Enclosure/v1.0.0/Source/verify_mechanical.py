"""Audit the exported LX0002 enclosure against the original, unreflected PCB STEP.

Requires the final populated PCB STEP and matching mm STL in Assets. Tests the
seated assembly and its full upward capture clearance. No CAD is modified.
"""
from pathlib import Path
import datetime
import hashlib
import json
import re
import cadquery as cq
import numpy as np
import trimesh
from scipy.spatial import cKDTree

root = Path(__file__).resolve().parents[3]
source = Path(__file__).resolve().parent
out = root / 'Enclosure/v1.0.0/Export/Case'
assets = root / 'Enclosure/v1.0.0/Assets'
p = json.loads((source / 'parameters.json').read_text())
m = json.loads((root / 'PCB/v1.0.0/Source/mechanical.json').read_text())
length, width, thickness = m['size_mm']
p['outer_x_mm'] = [-p['pcb_end_overhang_mm'][0], length+p['pcb_end_overhang_mm'][1]]
p['button_xy_mm'] = m['button_center']
x0, x1 = p['outer_x_mm']
y0, y1 = p['outer_y_mm']
z0 = p['floor_outer_z_mm']
top = p['roof_outer_z_mm']
datum = 1.6012
provenance = json.loads((assets / 'assembled-export-verification.json').read_text())
assert provenance['pcb_sha256'] == hashlib.sha256((root / 'PCB/v1.0.0/Source/LX0002.kicad_pcb').read_bytes()).hexdigest(), 'Stale PCB STEP/STL provenance'
parts = json.loads((root / 'PCB/v1.0.0/Source/parts.json').read_text())
expected_fitted = {part['ref'] for part in parts if part['lcsc'] and not part.get('dnp', False)}
assert set(provenance['fitted_refs']) == expected_fitted, 'STEP must contain every populated component'
for filename in ['LX0002-assembled.step', 'LX0002-assembled-mm.stl']:
    assert hashlib.sha256((assets / filename).read_bytes()).hexdigest() == provenance['sha256'][filename], 'PCB asset does not match its export provenance'
files = [Path(__file__).resolve(), source / 'enclosure.py', source / 'parameters.json',
         assets / 'enclosure-geometry.json', assets / 'assembled-export-verification.json', assets / 'LX0002-assembled.step',
         assets / 'LX0002-assembled-mm.stl', root / 'PCB/v1.0.0/Source/LX0002.kicad_pcb',
         root / 'PCB/v1.0.0/Source/mechanical.json', root / 'PCB/v1.0.0/Source/parts.json', out / 'base.step', out / 'lid.step', out / 'LX0002-case-assembly.step',
         *sorted(out.glob('*.stl'))]
hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
base = cq.importers.importStep(str(out / 'base.step')).val().translate((x0, -y1, z0))
lid = cq.importers.importStep(str(out / 'lid.step')).val().translate((x0, y0, -top)).rotate((0, 0, 0), (1, 0, 0), 180)
original = cq.importers.importStep(str(assets / 'LX0002-assembled.step')).val()
pcb = original.translate((0, 0, -datum))
substrates = [solid for solid in pcb.Solids() if abs(solid.BoundingBox().xlen - length) < 1e-6 and abs(solid.BoundingBox().ylen - width) < 1e-6]
assert len(substrates) == 1, 'Expected one native KiCad PCB substrate'
substrate = substrates[0]
bounds = substrate.BoundingBox()
assert abs(bounds.xmin) < 1e-6 and abs(bounds.xmax - length) < 1e-6
assert abs(bounds.ymin + width) < 1e-6 and abs(bounds.ymax) < 1e-6, 'PCB reference has incorrect handedness/origin'
# KiCad exports the dielectric body separately from copper/mask. This two-layer
# stackup has a 1.51mm core inside the nominal 1.60mm finished board.
board_text = (root / 'PCB/v1.0.0/Source/LX0002.kicad_pcb').read_text()
core_thickness = float(re.search(r'\(layer "dielectric 1"\s*\(type "core"\)\s*\(thickness ([\d.]+)\)', board_text).group(1))
assert abs(bounds.zlen - core_thickness) < 1e-6 and abs(bounds.zmin + datum) < 1e-6, 'Check native PCB dielectric seating datum'
nominal_board = substrate.translate((0, 0, datum)).transformGeometry(cq.Matrix([
    [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, thickness/core_thickness, 0], [0, 0, 0, 1]
])).translate((0, 0, -thickness))
components = [solid for solid in pcb.Solids() if not solid.isSame(substrate)]
assert len(components) > 10, 'A bare board is insufficient for a component fit audit'
case_assembly = cq.importers.importStep(str(out / 'LX0002-case-assembly.step')).val()
assert len(case_assembly.Solids()) == 2, 'Case assembly STEP must contain the two original case solids'
expected_volume = base.Volume() + lid.Volume()
assert abs(sum(solid.Volume() for solid in case_assembly.Solids()) - expected_volume) < 1e-5
assembly_bounds = case_assembly.BoundingBox()
assert np.allclose([assembly_bounds.xmin, assembly_bounds.ymin, assembly_bounds.zmin, assembly_bounds.xmax, assembly_bounds.ymax, assembly_bounds.zmax], [x0, -y1, 0, x1, -y0, top-z0], atol=1e-6)

markers = {}
for name, shape, radius in [('pcb_holes', substrate, m['mounting_drill_mm'] / 2), ('base_pins', base, p['locating_pin_diameter_mm'] / 2)]:
    centers = set()
    for face in shape.Faces():
        if face.geomType() != 'CYLINDER':
            continue
        cylinder = face._geomAdaptor().Cylinder()
        axis = cylinder.Axis()
        if abs(cylinder.Radius() - radius) < 1e-6 and abs(abs(axis.Direction().Z()) - 1) < 1e-6:
            point = axis.Location()
            centers.add((round(point.X(), 6), round(point.Y(), 6)))
    markers[name] = sorted(centers)
expected_holes = sorted((round(x, 6), round(-y, 6)) for x, y in m['mounting_holes'].values())
assert markers['pcb_holes'] == markers['base_pins'] == expected_holes, markers

# The PCB mesh may translate in Z only. Reflection or a second axis conversion
# is forbidden even when a symmetric case would hide the error visually.
original_mesh = trimesh.load(assets / 'LX0002-assembled-mm.stl', force='mesh', process=False)
reference_mesh = trimesh.load(out / 'pcb-reference.stl', force='mesh', process=False)
transform = np.eye(4)
transform[2, 3] = -datum - z0
assert np.linalg.det(transform[:3, :3]) == 1
expected = trimesh.transform_points(original_mesh.vertices, transform)
assert expected.shape == reference_mesh.vertices.shape
reference_error = float(np.max(np.abs(expected - reference_mesh.vertices)))
assert reference_error < 1e-5, reference_error
print_transforms = {}
mesh_checks = {}
for name in ['base', 'lid']:
    assembly_mesh = trimesh.load(out / (name + '-assembly.stl'), force='mesh', process=False)
    print_mesh = trimesh.load(out / (name + '.stl'), force='mesh', process=False)
    conversion = np.eye(4)
    if name == 'base':
        conversion[:3, 3] = [-x0, y1, 0]
    else:
        conversion[:3, :3] = np.diag([1, -1, -1])
        conversion[:3, 3] = [-x0, -y0, top - z0]
    assert np.linalg.det(conversion[:3, :3]) == 1
    expected = trimesh.transform_points(assembly_mesh.vertices, conversion)
    error = float(max(cKDTree(print_mesh.vertices).query(expected)[0].max(), cKDTree(expected).query(print_mesh.vertices)[0].max()))
    assert error < 1e-5, (name, error)
    print_transforms[name] = {'determinant': 1, 'matrix': conversion.tolist(), 'maximum_vertex_error_mm': error}
    checked = trimesh.load(out / (name + '.stl'), force='mesh')
    assert checked.is_watertight and checked.is_winding_consistent and checked.volume > 0 and checked.body_count == 1
    mesh_checks[name] = {'watertight': True, 'winding_consistent': True, 'positive_volume': True, 'connected_bodies': 1, 'bounds_mm': checked.bounds.tolist(), 'triangles': len(checked.faces)}

case_overlap = sum(solid.Volume() for solid in base.intersect(lid).Solids())
assert case_overlap < 1e-7
assert len(base.Solids()) == len(lid.Solids()) == 1 and base.isValid() and lid.isValid()
collisions = []
seat_contacts = []
for case_name, case in [('base', base), ('lid', lid)]:
    for index, solid in enumerate(pcb.Solids()):
        overlap = case.intersect(solid)
        volume = sum(piece.Volume() for piece in overlap.Solids())
        if volume <= 1e-7:
            continue
        body = solid.BoundingBox()
        overlap_bounds = overlap.BoundingBox()
        entry = {'case': case_name, 'pcb_solid_index': index, 'volume_mm3': volume, 'body_bounds_mm': [body.xmin, body.ymin, body.zmin, body.xmax, body.ymax, body.zmax], 'overlap_depth_mm': overlap_bounds.zlen}
        if solid.isSame(substrate) and case_name == 'base' and overlap_bounds.zlen <= 0.001201:
            seat_contacts.append(entry)
        else:
            collisions.append(entry)
    for index, solid in enumerate(components):
        overlap = case.intersect(solid.translate((0, 0, p['pcb_capture_top_z_mm'])))
        volume = sum(piece.Volume() for piece in overlap.Solids())
        if volume > 1e-7:
            collisions.append({'case': case_name, 'raised_component_index': index, 'lift_mm': p['pcb_capture_top_z_mm'], 'volume_mm3': volume})
assert not collisions, json.dumps(collisions, indent=2)
for case_name, case in [('base', base), ('lid', lid)]:
    for lift in [0, p['pcb_capture_top_z_mm']]:
        nominal_overlap = sum(piece.Volume() for piece in case.intersect(nominal_board.translate((0, 0, lift))).Solids())
        assert nominal_overlap < 1e-7, ('Finished board envelope', case_name, lift, nominal_overlap)

# The generic 0201 visual model is not the manufacturer's height tolerance.
# Check the actual L102 maximum height separately, with 0.10mm XY allowance.
l102 = next(part for part in parts if part['ref'] == 'L102')
assert l102['mpn'] == 'LQP03HQ2N7B02D', 'Review the L102 height envelope after any component change'
lx, ly, rotation = l102['place']
l102_envelope = cq.Workplane('XY').box(.80, .50, .42, centered=(True, True, False)).val().rotate((0, 0, 0), (0, 0, 1), rotation).translate((lx, -ly, 0))
for case_name, case in [('base', base), ('lid', lid)]:
    for lift in [0, p['pcb_capture_top_z_mm']]:
        overlap = sum(piece.Volume() for piece in case.intersect(l102_envelope.translate((0, 0, lift))).Solids())
        assert overlap < 1e-7, ('L102 manufacturer maximum-height envelope', case_name, lift, overlap)
manufacturer_envelopes = [{'reference': 'L102', 'mpn': l102['mpn'], 'maximum_height_mm': .42, 'checked_xy_envelope_mm': [.80, .50], 'nominal_body_xy_mm': [.60, .30], 'per_side_xy_allowance_mm': .10, 'source': l102['datasheet'], 'collision_free_at_maximum_board_lift': True}]

port_probes = []
for name, point in [('USB', (-0.75, -10, 1.5)), ('OUT_GND', (length + 0.75, -3.75, 2.5)), ('OUT_D16', (length + 0.75, -7.75, 2.5)), ('OUT_D17', (length + 0.75, -12.25, 2.5)), ('OUT_5V', (length + 0.75, -16.25, 2.5))]:
    probe = cq.Solid.makeSphere(.05, cq.Vector(*point))
    volume = sum(piece.Volume() for case in [base, lid] for piece in case.intersect(probe).Solids())
    assert volume < 1e-9, (name, volume)
    port_probes.append({'port': name, 'point_mm': point, 'overlap_mm3': volume})
# Full top access over every release button; the output opening runs to the end.
for y in [-3.75, -7.75, -12.25, -16.25]:
    probe = cq.Solid.makeCylinder(.5, 5, cq.Vector(m['output_centers'][0][0]-3.5, y, 3.7))
    assert sum(piece.Volume() for piece in lid.intersect(probe).Solids()) < 1e-7

long_sides = []
for face in lid.Faces():
    box = face.BoundingBox()
    if face.geomType() == 'PLANE' and box.ylen < 1e-6 and (abs(box.ymin + y0) < 1e-6 or abs(box.ymin + y1) < 1e-6):
        long_sides.append({'y_mm': box.ymin, 'x_span_mm': [box.xmin, box.xmax], 'z_span_mm': [box.zmin, box.zmax]})
assert len(long_sides) == 2
assert all(abs(side['z_span_mm'][0] - p['floor_inner_z_mm']) < 1e-6 and abs(side['z_span_mm'][1] - top) < 1e-6 for side in long_sides)
terminal_walls = []
for wall_y in [-1.3, -18.7]:
    points = [(length + delta, wall_y, (p['roof_inner_z_mm'] + top) / 2) for delta in [-.25, 0, .25]]
    matches = []
    for face in lid.Faces():
        box = face.BoundingBox()
        if face.geomType() == 'PLANE' and box.ylen < 1e-6 and abs(box.ymin - wall_y) < 1e-6:
            distances = [face.distance(cq.Vertex.makeVertex(*point)) for point in points]
            if max(distances) < 1e-6:
                matches.append({'y_mm': wall_y, 'x_span_mm': [box.xmin, box.xmax]})
    assert len(matches) == 1, 'Terminal window has a stepped/protruding end wall'
    terminal_walls.extend(matches)
for path in files:
    assert hashes[str(path.relative_to(root))] == hashlib.sha256(path.read_bytes()).hexdigest(), 'Inputs changed during audit'
report = {
    'reviewed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scope': 'Exact exported-solid assembly, full upward capture movement, original PCB handedness, and printable mesh audit. No physical fit, force, fatigue or thermal test.',
    'source_hashes_sha256': hashes,
    'physical_handedness': {'pass': True, 'pcb_holes_native_xy_mm': markers['pcb_holes'], 'base_pins_native_xy_mm': markers['base_pins'], 'pcb_transform': transform.tolist(), 'pcb_transform_determinant': 1, 'pcb_reference_vertex_error_mm': reference_error, 'assembly_to_print': print_transforms},
    'results': {'nominal_collision_check_pass': True, 'full_upward_pcb_float_mm': p['pcb_capture_top_z_mm'], 'base_lid_overlap_mm3': case_overlap, 'component_case_intersections': collisions, 'support_seat_datum_overlap': seat_contacts, 'step_core_thickness_mm': core_thickness, 'finished_board_envelope_thickness_mm': thickness, 'finished_board_envelope_collision_free': True, 'datum_note': 'KiCad STEP contains the dielectric core. Its bottom differs from the nominal support datum by up to1.2µm; only this substrate-seat contact is accepted. The complete nominal1.60mm finished-board envelope is checked independently.', 'print_meshes': mesh_checks, 'pcb_component_solids': len(components), 'manufacturer_height_envelopes': manufacturer_envelopes},
    'assembled_envelope_mm': [x1-x0, y1-y0, top-z0],
    'retention': {'locating_holes': expected_holes, 'pin_diameter_mm': p['locating_pin_diameter_mm'], 'edge_capture_x_mm': p['pcb_edge_capture_centers_x_mm'], 'edge_overlap_mm': p['pcb_edge_capture_overlap_mm'], 'capture_gap_mm': thickness+p['pcb_capture_top_z_mm'], 'screws': 0},
    'button': {'center_drawing_xy_mm': p['button_xy_mm'], 'membrane_size_mm': p['button_membrane_size_mm'], 'membrane_thickness_mm': p['button_membrane_thickness_mm'], 'nominal_switch_gap_mm': p['button_tip_z_mm']-2, 'gap_at_max_lift_mm': p['button_tip_z_mm']-2-p['pcb_capture_top_z_mm'], 'force_and_travel_physically_tested': False},
    'ports': {'probes': port_probes, 'usb_opening_mm': [p['usb_nominal_width_mm']+2*p['usb_clearance_per_side_mm'], p['usb_nominal_height_mm']+2*p['usb_clearance_per_side_mm']], 'usb_corner_radius_note': 'Nominal1.0mm connector corner radius is inferred from supplier model, not dimensioned by DEALON.', 'terminal_top_access': True, 'terminal_end_wall_planes': terminal_walls},
    'flat_long_sides': long_sides,
    'physical_fit_tested': False,
}
(out / 'Validation').mkdir(exist_ok=True)
(out / 'Validation/mechanical-review.json').write_text(json.dumps(report, indent=2)+'\n')
build = json.loads((out / 'verification.json').read_text())
build['final_pcb_overlay_verified'] = True
build['stage'] = 'CAD FIT AND HANDEDNESS CHECKED; physical fit and force testing remain required'
(out / 'verification.json').write_text(json.dumps(build, indent=2)+'\n')
print(json.dumps({'component_collisions':0,'base_lid_overlap_mm3':case_overlap,'pcb_component_solids':len(components),'envelope_mm':report['assembled_envelope_mm']},indent=2))
