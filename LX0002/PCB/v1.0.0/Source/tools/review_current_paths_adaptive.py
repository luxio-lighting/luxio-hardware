"""Summarize separately converged USB-positive and ground DC meshes.

Inputs are freshly generated .10mm/.05mm two-net results and .025mm
positive-only sparse results, all tied to the exact current PCB hash.
"""
import argparse,collections,datetime,hashlib,json,math,shutil,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board',type=Path,default=root/'Source/LX0002.kicad_pcb')
parser.add_argument('--report',type=Path,default=root/'Source/current_path_review.txt')
parser.add_argument('--evidence-dir',type=Path,default=root/'Export/current-path-model')
args=parser.parse_args()
args.usb_contact_group='all'
args.resolutions=[.10,.05,.025]
board_hash=hashlib.sha256(args.board.read_bytes()).hexdigest()
subprocess.run(['/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli','pcb','drc','--schematic-parity','--all-track-errors','--severity-all','--format','json','-o',str(args.evidence_dir/'current-board-drc.json'),str(args.board)],check=True)
drc=json.loads((args.evidence_dir/'current-board-drc.json').read_text());unconnected=len(drc['unconnected_items']);violations=drc['violations'];electrical={item['type'] for item in violations}
assert not violations and not unconnected and not drc['schematic_parity']
mesh_paths={.10:args.evidence_dir/'usb-all-0p1-mesh.json',.05:args.evidence_dir/'usb-all-0p05-mesh.json',.025:args.evidence_dir/'usb-positive-0p025-mesh.json'}
mesh_hashes={}
for pitch,path in mesh_paths.items():
 mesh=json.loads(path.read_text())
 assert mesh['board_sha256']==board_hash and mesh['resolution_mm']==pitch
 assert mesh['copper_thickness_um']==[35.0,35.0] and mesh['actual_copper_layers']==2
 assert mesh['rasterizer_sha256']==hashlib.sha256((root/'Source/tools/current_path_mesh.py').read_bytes()).hexdigest()
 mesh_hashes[pitch]=hashlib.sha256(path.read_bytes()).hexdigest()
convergence=[];finals=[];cases=[]
for wall in [25,20,18]:
 coarse=json.loads((args.evidence_dir/f'usb-all-0p1-{wall}um-results.json').read_text())
 middle=json.loads((args.evidence_dir/f'usb-all-0p05-{wall}um-results.json').read_text())
 fine=json.loads((args.evidence_dir/f'usb-positive-0p025-{wall}um-results.json').read_text())
 for data in [coarse,middle,fine]:
  assert data['mesh_sha256']==mesh_hashes[data['resolution_mm']]
  assert data['successful'] and data['board_sha256']==board_hash and data['current_a']==3 and data['copper_um']==[35] and data['board_thickness_mm']==1.6 and data['via_plating_um']==wall
  assert data['solver_sha256']==hashlib.sha256((root/'Source/tools/current_path_solve_sparse.py').read_bytes()).hexdigest()
 for net,low,high in [('USB_5V',middle,fine),('GND',coarse,middle)]:
  x=low['segments'][net]['results'][0];y=high['segments'][net]['results'][0];change=abs(x['resistance_mohm']-y['resistance_mohm'])/y['resistance_mohm']*100
  assert x['converged'] and y['converged'] and change<=5,(net,change)
  convergence.append({'net':net,'wall_um':wall,'coarse_mm':low['resolution_mm'],'fine_mm':high['resolution_mm'],'change_percent':change})
 segments={'USB_5V':fine['segments']['USB_5V'],'GND':middle['segments']['GND']}
 resistance=sum(s['results'][0]['resistance_mohm'] for s in segments.values())
 totals=[{'copper_um':35,'resistance_mohm':resistance,'drop_mv':3*resistance,'loss_w':9*resistance/1000}]
 finals.append({'via_plating_um':wall,'segments':segments,'totals':totals,'net_resolution_mm':{'USB_5V':.025,'GND':.05}})
 cases.extend([middle,fine])
assert hashlib.sha256(args.board.read_bytes()).hexdigest()==board_hash
lines = ['LX0002 USB copper-path review', f'PCB SHA256: {board_hash}', f'Board: {args.board.resolve()}', f'Generated UTC: {datetime.datetime.now(datetime.timezone.utc).isoformat()}', 'Status: PROVISIONAL; routing incomplete' if unconnected else 'Status: routed snapshot, zero unconnected items in fresh DRC', '', '3A total USB connector ceiling; both actual 35um copper layers, 1.6mm full through-barrel model.', 'USB_5V: J1 VBUS contacts to J4 VCC. GND: J3 ground to J1 ground contacts.', 'USB cable shield is not assumed to carry return current; shell stakes still provide PCB interlayer copper.', 'The entire 3A is assigned to the strip loop; actual controller current reduces allowable strip current.', 'Copper/barrel dissipation only: no cable, connector/contact, solder, controller or regulator losses.', 'No temperature, continuous-current qualification or fault-clearing claim is made.', '']
lines += ['Adaptive convergence: USB_5V uses 0.025mm, checked against 0.05mm; GND uses 0.05mm, checked against 0.10mm. Each net meets the preset 5% grid-change limit.', 'All three grids were extracted anew from this exact PCB snapshot and solved with the SciPy sparse conductance solver.', '']
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
layout = {'routes': json.loads(mesh_paths[.025].read_text())['segments']['USB_5V']['tracks']}
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
lines += ['', 'Provenance: fresh current-board meshes; no conductance results reused from earlier revisions.']
lines += ['', f'Fresh DRC unconnected count: {unconnected}; electrical violations: {len(violations)}.', f"Other DRC categories: {dict(collections.Counter(item['type'] for item in drc.get('violations',[]) if item['type'] not in electrical))}", 'Re-run after every copper, via, placement or fill change.', '']
summary = {'board_sha256': board_hash, 'current_a': 3, 'usb_contact_group': args.usb_contact_group, 'copper_um': [35,35], 'net_resolutions_mm': {'USB_5V':0.025,'GND':0.05}, 'grid_comparison': convergence, 'fanout': fanout, 'successful': True, 'unconnected': unconnected}
(args.evidence_dir/'current-review-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
if args.report.exists():
    history=root/'Assets/review-history';history.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(args.report.read_bytes()).hexdigest()[:12]
    archived=history/f'current-path-review-{digest}.txt'
    if not archived.exists():shutil.copy2(args.report,archived)
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text('\n'.join(lines))
print(f'Saved{args.report}; board unchanged')
