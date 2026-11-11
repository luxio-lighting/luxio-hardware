"""Produce a fresh routed-board copper report and archive superseded estimates.

Run with a Python installation containing NumPy and SciPy:
  python3 Source/tools/review_current_paths.py --board Source/LX0001.kicad_pcb
KiCad DRC, raster extraction, hash validation and the resistor-network solve
must succeed before the report is replaced. --allow-unrouted labels a private
engineering run provisional; use the default for the final routed PCB.
"""
import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
folder = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board', type=Path, required=True)
parser.add_argument('--report', type=Path, default=root / 'Source/current_path_review.txt')
parser.add_argument('--evidence-dir', type=Path, default=root / 'Export/current-path-model')
parser.add_argument('--resolution', type=float, default=0.1)
parser.add_argument('--copper-um', type=float, nargs='+', default=[35])
parser.add_argument('--allow-unrouted', action='store_true')
parser.add_argument('--include-usb', action='store_true', help='Also model the USB load loop at the worst-case 1.384 A current clamp')
parser.add_argument('--kicad-python', default='/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9')
parser.add_argument('--kicad-cli', default='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args = parser.parse_args()
assert args.resolution > 0
args.evidence_dir.mkdir(parents=True, exist_ok=True)
board_hash = hashlib.sha256(args.board.read_bytes()).hexdigest()
drc_path = args.evidence_dir / 'current-board-drc.json'
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(drc_path), str(args.board)], check=True)
drc = json.loads(drc_path.read_text())
unconnected = len(drc.get('unconnected_items', []))
electrical = {'clearance', 'shorting_items', 'hole_to_hole', 'hole_clearance', 'edge_clearance', 'track_width', 'via_annulus', 'via_diameter', 'drill_out_of_range', 'copper_edge_clearance', 'track_crossing', 'tracks_crossing', 'items_not_allowed'}
violations = [v for v in drc.get('violations', []) if v['type'] in electrical]
assert not violations, 'Electrical DRC violations remain; previous current-path report was preserved'
assert args.allow_unrouted or not unconnected, f'{unconnected} unrouted connections remain; previous current-path report was preserved'
mesh_path = args.evidence_dir / 'current-copper-mesh.json'
result_path = args.evidence_dir / 'current-copper-results.json'
raw_report = args.evidence_dir / 'current-copper-solver.txt'
subprocess.run([args.kicad_python, str(folder / 'current_path_mesh.py'), str(args.board), '--output', str(mesh_path), '--resolution', str(args.resolution), '--full-stack'], check=True)
subprocess.run([sys.executable, str(folder / 'current_stack_solve.py'), str(mesh_path), '--report', str(raw_report), '--json-output', str(result_path), '--current-a', '5', '--copper-um'] + [str(v) for v in args.copper_um], check=True)
results = json.loads(result_path.read_text())
mesh = json.loads(mesh_path.read_text())
assert results['successful'] and results['board_sha256'] == board_hash
assert hashlib.sha256(args.board.read_bytes()).hexdigest() == board_hash, 'PCB changed while modelling; previous report preserved'
status = 'PROVISIONAL: routing remains incomplete' if unconnected else 'Routed PCB: zero unconnected items in a fresh KiCad DRC'
lines = ['LX0001 current-path review — actual saved copper', f'PCB SHA256: {board_hash}', f'Board: {args.board.resolve()}', f'Status: {status}', f'Generated UTC: {datetime.datetime.now(datetime.timezone.utc).isoformat()}', '']
for total in results['totals']:
    lines.append(f"At 5 A (35 um outer / 15.2 um inner copper): modeled loop {total['resistance_mohm']:.4f} mOhm, {total['drop_mv']:.3f} mV drop, {total['loss_w']:.4f} W copper loss.")
lines += ['This is an electrical copper estimate, not a thermal rating or 5 A qualification.', 'Connectors, solder joints, fuse element and MOSFET package/channel losses are excluded.', '', 'Per-net copper results (5 A, 20 C copper resistivity):', 'Net        Terminals       Outer um R mOhm   Drop mV   Loss W']
for name, segment in results['segments'].items():
    for row in segment['results']:
        lines.append(f"{name:10} {segment['source_ref']:>3}->{segment['sink_ref']:<3}       {row['copper_um']:5g}  {row['resistance_mohm']:8.4f}  {row['drop_mv']:8.3f}  {row['loss_w']:7.4f}")
if args.include_usb:
    usb_mesh_path = args.evidence_dir / 'usb-copper-mesh.json'
    usb_result_path = args.evidence_dir / 'usb-copper-results.json'
    subprocess.run([args.kicad_python, str(folder / 'current_path_mesh.py'), str(args.board), '--output', str(usb_mesh_path), '--resolution', str(args.resolution), '--power-source', 'usb', '--full-stack'], check=True)
    subprocess.run([sys.executable, str(folder / 'current_stack_solve.py'), str(usb_mesh_path), '--report', str(args.evidence_dir / 'usb-copper-solver.txt'), '--json-output', str(usb_result_path), '--current-a', '1.384', '--copper-um'] + [str(v) for v in args.copper_um], check=True)
    usb_results = json.loads(usb_result_path.read_text())
    assert usb_results['successful'] and usb_results['board_sha256'] == board_hash
    assert hashlib.sha256(args.board.read_bytes()).hexdigest() == board_hash, 'PCB changed during USB model'
    lines += ['', 'USB load-path copper results (1.384 A worst-case clamp, 20 C):']
    for total in usb_results['totals']:
        lines.append(f"At 35 um outer / 15.2 um inner copper: USB loop {total['resistance_mohm']:.4f} mOhm, {total['drop_mv']:.3f} mV drop, {total['loss_w']:.4f} W copper loss.")
    for name, segment in usb_results['segments'].items():
        for row in segment['results']:
            lines.append(f"{name:12} {segment['source_ref']:>3}->{segment['sink_ref']:<3} {row['copper_um']:g} um: {row['resistance_mohm']:.4f} mOhm; {row['drop_mv']:.3f} mV; {row['loss_w']:.5f} W.")
    lines.append('TPS2553 switch resistance, USB connector/cable and Q3 channel resistance are excluded from this copper-only USB loop.')
lines += ['', 'Interlayer current distribution:']
for name in ['VSYS', 'GND']:
    for row in results['segments'][name]['results']:
        vias = [v for v in row['via_currents'] if v.get('kind') == 'routing_via']
        if vias:
            maximum = max(vias, key=lambda v: v['current_a'])
            lines.append(f"{name}, {row['copper_um']:g} um: largest modeled routing-via current {maximum['current_a']:.3f} A at ({maximum['x_mm']:.3f}, {maximum['y_mm']:.3f}) mm, drill {maximum['drill_mm']:.2f} mm.")
        component_holes = [v for v in row['via_currents'] if v.get('kind') == 'plated_component_hole']
        if component_holes:
            lines.append(f"{name}: {len(component_holes)} plated component slots also included using their actual plated perimeter.")
lines += ['', 'Model and practical limits:', f"Grid {mesh['resolution_mm']:g} mm; copper rho 1.724e-8 ohm-m at 20 C.", f"Nominal board 1.6 mm; actual saved copper layer spacing; assumed via/slot wall {results['via_plating_um']:g} um.", 'Saved filled zones, tracks and pads were extracted without changing the PCB.', 'Terminal pads on each named component are ideal equipotential nodes.', 'Rasterization approximates narrow copper and current crowding; it is not a temperature simulation.', 'The model includes all four copper layers (35/15.2/15.2/35 um), adjacent-layer barrel lengths and plated connector slots. Internal ground paths are included.', 'Copper resistance rises with temperature; actual copper/plating tolerances are not measured.', '', 'Approximate additional device loss at 5 A / 25 C:', 'Q1: up to 0.248 W from 9.9 mOhm; F1: about 0.168 W from its typical 6.7 mOhm.', 'Q6: up to 0.375 W at 10 V gate drive, or 0.575 W at 4.5 V, before hot-RDS(on) increase.', 'These figures omit connector/contact resistance and do not bound enclosure temperature.', 'The final PCB/case needs 5/12/24 V load-temperature and fault-clearing measurements.', '', f"Fresh DRC: {unconnected} unconnected items; electrical error types checked: {len(violations)}.", f"Other DRC categories: {dict(collections.Counter(v['type'] for v in drc.get('violations', []) if v['type'] not in electrical))}", 'This copper report does not waive mechanical, RF, assembly or other manufacturing checks.', '', f'Evidence: {args.evidence_dir.resolve()}', f"Mesh SHA256: {results['mesh_sha256']}", f"Solver SHA256: {results['solver_sha256']}", 'Re-run after any routing, via, footprint or copper-fill change.', '']
if args.report.exists():
    history = root / 'Assets/review-history'
    history.mkdir(parents=True, exist_ok=True)
    old_hash = hashlib.sha256(args.report.read_bytes()).hexdigest()[:12]
    archived = history / f'current_path_review-{old_hash}.txt'
    if not archived.exists():
        shutil.copy2(args.report, archived)
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text('\n'.join(lines))
print(f'Saved current report {args.report}; superseded report archived if present')
