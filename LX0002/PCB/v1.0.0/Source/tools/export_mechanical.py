"""Export the populated native PCB without mirroring, then verify every fitted ref.

Run using the CadQuery environment after final routing and silkscreen are frozen.
The populated STL is an assembly reference for collision checks, not a print job.
"""
from pathlib import Path
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import cadquery as cq
import numpy as np
import trimesh

root = Path(__file__).resolve().parents[2]
source = root / 'Source'
output = root / 'Export'
output.mkdir(parents=True, exist_ok=True)
board = source / 'LX0002.kicad_pcb'
board_hash = hashlib.sha256(board.read_bytes()).hexdigest()
parts = json.loads((source / 'parts.json').read_text())
mechanical = json.loads((source / 'mechanical.json').read_text())
board_length, board_width, board_thickness = mechanical['size_mm']
fitted = sorted(part['ref'] for part in parts if part.get('lcsc') and not part.get('dnp'))
cli = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
step = output / 'LX0002-assembled.step'
glb = output / 'LX0002-assembled.glb'
stl = output / 'LX0002-assembled-mm.stl'
for kind, target, extra in [
    ('step', step, []),
    ('glb', glb, ['--include-pads', '--include-silkscreen', '--include-soldermask']),
]:
    command = [cli, 'pcb', 'export', kind, '--force', '--no-dnp', '--subst-models',
               '--output', str(target), *extra, str(board)]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    (output / ('mechanical-export-' + kind + '.log')).write_text(result.stdout + result.stderr)
    assert target.is_file() and target.stat().st_size > 1000

assembly_refs = re.findall(r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\('[^']*','([^']*)'", step.read_text())
missing = sorted(set(fitted) - set(assembly_refs))
assert not missing, 'Missing fitted component models: ' + ', '.join(missing)
assert 'L104' not in assembly_refs, 'DNP antenna tuning component must not be rendered'
shape = cq.importers.importStep(str(step)).val()
solids = shape.Solids()
assert solids and all(solid.isValid() for solid in solids), 'Invalid STEP solids'
bounds = shape.BoundingBox()
step_bounds = np.array([[bounds.xmin, bounds.ymin, bounds.zmin],
                        [bounds.xmax, bounds.ymax, bounds.zmax]])
assert bounds.xmin < 0 and bounds.xmax >= board_length-.01 and bounds.ymin <= -board_width+.01 and bounds.ymax < .01
assert bounds.zmin > -.1 and bounds.zmax > 6, 'Unexpected KiCad STEP assembly datum'
cq.exporters.export(shape, str(stl), tolerance=.015, angularTolerance=.1)
mesh = trimesh.load(str(stl), force='mesh', process=False)
assert np.max(np.abs(mesh.bounds - step_bounds)) < .03, 'STL scale or coordinates changed'
scene = trimesh.load(str(glb), force='scene', process=False)
world_bounds = []
for node in scene.graph.nodes_geometry:
    matrix, name = scene.graph[node]
    component = scene.geometry[name].copy()
    component.apply_transform(matrix)
    component.vertices = np.asarray(component.vertices)[:, [0, 2, 1]] * [1000, -1000, 1000]
    world_bounds.append(component.bounds)
glb_bounds = np.array([np.min([bound[0] for bound in world_bounds], axis=0),
                       np.max([bound[1] for bound in world_bounds], axis=0)])
assert np.max(np.abs(glb_bounds - step_bounds)) < .12, 'GLB handedness, scale or origin differs'
assert hashlib.sha256(board.read_bytes()).hexdigest() == board_hash, 'Board changed during export'
verification = {
    'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'pcb_sha256': board_hash,
    'fitted_component_count': len(fitted), 'fitted_refs': fitted,
    'missing_models': missing, 'solid_count': len(solids), 'all_solids_valid': True,
    'units': 'mm', 'step_bounds_mm': step_bounds.tolist(), 'glb_bounds_mm': glb_bounds.tolist(),
    'coordinates': 'Native KiCad STEP: X right, Y negative, dielectric core Z=0..1.51mm; nominal finished PCB 1.6mm; no reflection',
    'preview_models': ['ANT1 and SW1 STEP geometry converted exactly from existing approximate VRML models',
                       'U1 FH4R2 nominal package model from Espressif datasheet v2.2 Figure7-2; not a supplier STEP'],
    'supplier_models': 'J1 USB and J3/J4 terminals are supplier visualization models; drawings govern fit',
    'sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in [step, stl, glb]},
}
record = output / 'assembled-export-verification.json'
record.write_text(json.dumps(verification, indent=2) + '\n')
enclosure_assets = root.parents[1] / 'Enclosure/v1.0.0/Assets'
assert enclosure_assets.parent.is_dir(), enclosure_assets
enclosure_assets.mkdir(exist_ok=True)
for path in [step, stl, record]:
    shutil.copyfile(path, enclosure_assets / path.name)
print(json.dumps(verification, indent=2))
