"""Review the frozen, fully routed LX0002 USB copper loop without changing CAD.

Run using a Python with NumPy after final zone fill/save:
  python3 Source/tools/review_current_paths.py --board Source/LX0002.kicad_pcb
Default cases compare0.10/0.05mm grids with25/20um barrel walls at3A.
No resulting report is a thermal qualification or an independently rated ampacity.
"""
import argparse
import collections
import datetime
import hashlib
import json
import math
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
parser.add_argument('--resolutions', type=float, nargs='+', default=[0.10, 0.05])
parser.add_argument('--via-plating-um', type=float, nargs='+', default=[25, 20])
parser.add_argument('--usb-contact-group', choices=['all', 'upper', 'lower'], default='all')
parser.add_argument('--max-grid-change-percent', type=float, default=5)
parser.add_argument('--allow-unrouted', action='store_true')
parser.add_argument('--reuse-current-results', action='store_true', help='Reuse successful results only when PCB, mesh, solver and all physical parameters match exactly')
parser.add_argument('--kicad-python', default='/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3')
parser.add_argument('--kicad-cli', default='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args = parser.parse_args()
assert all(0.02 <= value <= 0.5 for value in args.resolutions)
assert all(value > 0 for value in args.via_plating_um)
args.evidence_dir.mkdir(parents=True, exist_ok=True)
board_hash = hashlib.sha256(args.board.read_bytes()).hexdigest()
drc_path = args.evidence_dir / 'current-board-drc.json'
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(drc_path), str(args.board)], check=True)
drc = json.loads(drc_path.read_text())
unconnected = len(drc.get('unconnected_items', []))
electrical = {'clearance', 'shorting_items', 'hole_to_hole', 'hole_clearance', 'edge_clearance', 'track_width', 'via_annulus', 'via_diameter', 'drill_out_of_range', 'copper_edge_clearance', 'track_crossing', 'tracks_crossing', 'items_not_allowed'}
violations = [item for item in drc.get('violations', []) if item['type'] in electrical]
assert not violations, 'Electrical DRC violations remain; previous report is preserved'
assert args.allow_unrouted or not unconnected, f'{unconnected} unrouted connections remain; previous report is preserved'
cases = []
for resolution in sorted(set(args.resolutions), reverse=True):
    prefix = 'usb-' + args.usb_contact_group + '-' + str(resolution).replace('.', 'p')
    mesh_path = args.evidence_dir / (prefix + '-mesh.json')
    subprocess.run([args.kicad_python, str(folder / 'current_path_mesh.py'), str(args.board), '--output', str(mesh_path), '--resolution', str(resolution), '--usb-contact-group', args.usb_contact_group], check=True)
    for wall in args.via_plating_um:
        result_path = args.evidence_dir / (prefix + '-' + str(wall) + 'um-results.json')
        previous = json.loads(result_path.read_text()) if args.reuse_current_results and result_path.exists() else {}
        reusable = previous.get('successful') and previous.get('board_sha256') == board_hash and previous.get('mesh_sha256') == hashlib.sha256(mesh_path.read_bytes()).hexdigest() and previous.get('solver_sha256') == hashlib.sha256((folder / 'current_path_solve.py').read_bytes()).hexdigest() and previous.get('current_a') == 3 and previous.get('copper_um') == [35] and previous.get('board_thickness_mm') == 1.6 and previous.get('via_plating_um') == wall
        if reusable:
            print('Reused exact current PCB/mesh/solver result:', result_path, flush=True)
        else:
            subprocess.run([sys.executable, str(folder / 'current_path_solve.py'), str(mesh_path), '--report', str(result_path.with_suffix('.txt')), '--json-output', str(result_path), '--board', str(args.board), '--current-a', '3', '--copper-um', '35', '--board-thickness-mm', '1.6', '--via-plating-um', str(wall)], check=True)
        result = json.loads(result_path.read_text())
        assert result['successful'] and result['board_sha256'] == board_hash
        assert hashlib.sha256(args.board.read_bytes()).hexdigest() == board_hash, 'PCB changed during analysis; report is preserved'
        cases.append(result)
convergence = []
for wall in args.via_plating_um:
    rows = sorted([case for case in cases if case['via_plating_um'] == wall], key=lambda item: item['resolution_mm'], reverse=True)
    for coarse, fine in zip(rows, rows[1:]):
        delta = abs(coarse['totals'][0]['resistance_mohm'] - fine['totals'][0]['resistance_mohm']) / fine['totals'][0]['resistance_mohm'] * 100
        per_net = {net: abs(coarse['segments'][net]['results'][0]['resistance_mohm'] - fine['segments'][net]['results'][0]['resistance_mohm']) / fine['segments'][net]['results'][0]['resistance_mohm'] * 100 for net in fine['segments']}
        assert all(change <= args.max_grid_change_percent for change in per_net.values()), f'Per-net grid sensitivity too high: {per_net}; refine mesh'
        convergence.append({'wall_um': wall, 'coarse_mm': coarse['resolution_mm'], 'fine_mm': fine['resolution_mm'], 'loop_change_percent': delta, 'per_net_change_percent': per_net})
        assert delta <= args.max_grid_change_percent, f'Grid change{delta:.2f}% exceeds{args.max_grid_change_percent:g}%; refine grid before accepting report'
finals = [case for case in cases if case['resolution_mm'] == min(args.resolutions)]
lines = ['LX0002 USB copper-path review', f'PCB SHA256: {board_hash}', f'Board: {args.board.resolve()}', f'Generated UTC: {datetime.datetime.now(datetime.timezone.utc).isoformat()}', 'Status: PROVISIONAL; routing incomplete' if unconnected else 'Status: routed snapshot, zero unconnected items in fresh DRC', '', '3A total USB connector ceiling; both actual 35um copper layers, 1.6mm full through-barrel model.', 'USB_5V: J1 VBUS contacts to J4 VCC. GND: J3 ground to J1 ground contacts.', 'USB cable shield is not assumed to carry return current; shell stakes still provide PCB interlayer copper.', 'The entire 3A is assigned to the strip loop; actual controller current reduces allowable strip current.', 'Copper/barrel dissipation only: no cable, connector/contact, solder, controller or regulator losses.', 'No temperature, continuous-current qualification or fault-clearing claim is made.', '']
for case in finals:
    total = case['totals'][0]
    lines.append(f"{case['via_plating_um']:g}um wall: loop {total['resistance_mohm']:.4f}mOhm, {total['drop_mv']:.3f}mV, {total['loss_w']:.5f}W at 3A and 20C.")
    lines.append(f"Uniform 60C copper sensitivity only: {total['resistance_mohm']*1.1572:.4f}mOhm, {total['drop_mv']*1.1572:.3f}mV, {total['loss_w']*1.1572:.5f}W. This is not a predicted temperature.")
    for net, segment in case['segments'].items():
        row = segment['results'][0]
        lines.append(f"  {net}: {row['resistance_mohm']:.4f}mOhm; planar{row['planar_copper_loss_w']:.5f}W, barrels{row['barrel_loss_w']:.5f}W.")
        if row['via_currents']:
            maximum = max(row['via_currents'], key=lambda via: via['current_a'])
            lines.append(f"  Largest barrel current{maximum['current_a']:.3f}A at({maximum['x_mm']:.3f},{maximum['y_mm']:.3f})mm; drill{maximum['drill_mm']:.2f}mm; barrel loss{maximum['loss_w']:.6f}W.")
layout = json.loads((root / 'Source/power_distribution_layout.json').read_text())
fanout = []
lines += ['', 'USB VBUS fanout / narrow-branch review:']
for label, pad, via_coordinates in [('upper', [6.175,7.6], [[4.7,7.95],[5.2,8.2]]), ('lower', [6.175,12.4], [[4.1,12.1],[4.7,12.1]])]:
    expected_points = [pad, [5.7,7.6], [5.35,7.95], [4.7,7.95]] if label == 'upper' else [pad, [5.7,12.4], [5.45,12.15], [4.1,12.1]]
    width = 0.33
    length = 0
    for start,end in zip(expected_points,expected_points[1:]):
        matches = [route for route in layout['routes'] if route['net']=='USB_5V' and route['layer']=='F.Cu' and len(route['points'])==2 and ((math.dist(route['points'][0],start)<.000002 and math.dist(route['points'][1],end)<.000002) or (math.dist(route['points'][1],start)<.000002 and math.dist(route['points'][0],end)<.000002))]
        assert len(matches)==1 and abs(matches[0].get('width_mm',matches[0].get('width'))-width)<1e-9, 'USB fanout geometry changed; update branch review'
        length += math.dist(start,end)
    branch_r = 1.724e-8 * length * 1e-3 / (width * 1e-3 * 35e-6)
    lines.append(f'{label}: {width:.3f}mm F.Cu neck, path length{length:.3f}mm to furthest via; two 0.30mm drilled vias. Analytic full 3A branch bound{branch_r*3000:.3f}mV/{branch_r*9:.5f}W, excluding pad widening.')
    entry = {'branch': label, 'width_mm': width, 'path_length_mm': length, 'full_3a_trace_bound_mohm': branch_r*1000, 'full_3a_trace_bound_loss_w': branch_r*9, 'cases': []}
    for case in finals:
        currents = case['segments']['USB_5V']['results'][0]['via_currents']
        selected = []
        for x,y in via_coordinates:
            matches = [via for via in currents if abs(via['x_mm']-x) < .01 and abs(via['y_mm']-y) < .01]
            assert len(matches) == 1, 'Input via bank changed or disconnected; update review identification'
            selected.append(matches[0])
        current = abs(sum(via['signed_F_to_B_current_a'] for via in selected))
        entry['cases'].append({'plating_um': case['via_plating_um'], 'bank_total_a': current, 'via_currents_a': [via['current_a'] for via in selected], 'via_losses_w': [via['loss_w'] for via in selected], 'branch_trace_loss_bound_w': current**2*branch_r})
        lines.append(f"  {case['via_plating_um']:g}um wall: bank{current:.3f}A; individual vias" + '/'.join(f"{via['current_a']:.3f}A" for via in selected) + f'; conservative neck loss at that share{current**2*branch_r:.5f}W.')
    fanout.append(entry)
for case in finals:
    bank_sum = sum(next(item['bank_total_a'] for item in branch['cases'] if item['plating_um'] == case['via_plating_um']) for branch in fanout)
    assert abs(bank_sum-3) < .03, f'VBUSbank total{bank_sum:.4f}A does not account for3A; inspect alternate source path and update review'
lines += ['Two branch currents sum to total source current; do not add independent nominal via/trace ampacities.', 'Normal current sharing assumes equipotential USB VBUS contacts. A single-input-pad stress model can be run with --usb-contact-group upper or lower.', 'Short-neck Joule losses are computed explicitly; a long isolated-track ampacity chart does not establish these short necks enclosure temperatures.', '', 'Assumptions and limitations:', '25um is the requested nominal assumption;20um and18um are sensitivity cases. None is a guaranteed local minimum.', 'JLCPCB current capabilities list18um average hole plating: https://jlcpcb.com/capabilities/pcb-capabilities', 'Planar35um is the specified saved stackup, not a measured finished copper thickness.', 'Grid error, local current crowding, etch/plating tolerances and connector/contact resistance remain.', 'Bench validation must measure total USB input current, board/cable voltage drop and connector/neck/buck temperatures inside the closed enclosure.', '', 'Grid comparison:']
lines.extend(json.dumps(item, sort_keys=True) for item in convergence)
lines += ['', 'Calculation reuse provenance:']
lines.extend(json.dumps(case['calculation_reuse'], sort_keys=True) for case in cases if case.get('calculation_reuse'))
lines += ['', f'Fresh DRC unconnected count: {unconnected}; electrical violations: {len(violations)}.', f"Other DRC categories: {dict(collections.Counter(item['type'] for item in drc.get('violations',[]) if item['type'] not in electrical))}", 'Re-run after every copper, via, placement or fill change.', '']
summary = {'board_sha256': board_hash, 'current_a': 3, 'usb_contact_group': args.usb_contact_group, 'copper_um': [35,35], 'final_resolution_mm': min(args.resolutions), 'grid_comparison': convergence, 'fanout': fanout, 'successful': True, 'unconnected': unconnected}
(args.evidence_dir/'current-review-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
if args.report.exists():
    history=root/'Assets/review-history';history.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(args.report.read_bytes()).hexdigest()[:12]
    archived=history/f'current-path-review-{digest}.txt'
    if not archived.exists():shutil.copy2(args.report,archived)
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text('\n'.join(lines))
print(f'Saved{args.report}; board unchanged')
