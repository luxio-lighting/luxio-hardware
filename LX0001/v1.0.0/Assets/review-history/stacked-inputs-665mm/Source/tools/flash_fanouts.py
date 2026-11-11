"""Add DRC-validated MCU flash and series-clock escapes without moving components.

KiCad Python flash_fanouts.py INPUT --preserve-board MANUAL_BASE --output OUTPUT
Only flash/VDD_SPI tracks absent from MANUAL_BASE are cleared. Existing manual
copper, other nets and all footprint positions remain unchanged. New escapes
are locked and have deterministic UUIDs. Use a distinct output for review.
"""
import argparse
import collections
import json
from pathlib import Path
import shutil
import subprocess
import uuid
import pcbnew as p

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('board', type=Path)
parser.add_argument('--preserve-board', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--kicad-cli', default='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve(), 'Use a distinct output for review'
args.output.parent.mkdir(parents=True, exist_ok=True)
source = args.output.with_name(args.output.stem + '-source.kicad_pcb')
trial = args.output.with_name(args.output.stem + '-trial.kicad_pcb')
for target in [source, trial, args.output]:
    for ext in ['.kicad_pro', '.kicad_dru']:
        if args.board.with_suffix(ext).exists():
            shutil.copy2(args.board.with_suffix(ext), target.with_suffix(ext))
shutil.copy2(args.board, source)
source_drc = source.with_suffix('.json')
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(source_drc), str(source)], check=True)
initial = json.loads(source_drc.read_text())
b = p.LoadBoard(str(args.board))
manual_board = p.LoadBoard(str(args.preserve_board))
manual = {t.m_Uuid.AsString() for t in manual_board.GetTracks() if t.IsLocked()}
nets = {n.GetNetname(): n for n in b.GetNetInfo().NetsByNetcode().values()}
flash_nets = {'FLASH_IO0', 'FLASH_IO1', 'FLASH_IO2', 'FLASH_IO3', 'FLASH_CS', 'FLASH_CLK', 'SPICLK', 'VDD_SPI'}
removed = collections.Counter()
for t in list(b.GetTracks()):
    if t.GetNetname() in flash_nets and (t.m_Uuid.AsString() not in manual or t.m_Uuid.AsString().startswith('f1a5c001-')):
        removed[t.GetNetname()] += 1
        b.Delete(t)
for ref, number, expected in [('U1', '34', (25.65, 10.6)), ('R105', '2', (28.11, 12.5))]:
    pad = next(pad for f in b.GetFootprints() if f.GetReference() == ref for pad in f.Pads() if pad.GetNumber() == number)
    assert abs(p.ToMM(pad.GetPosition().x) - expected[0]) < 0.005 and abs(p.ToMM(pad.GetPosition().y) - expected[1]) < 0.005, 'Footprint placement changed; review flash escape coordinates'
namespace = uuid.UUID('92eea27d-bb50-4337-aab6-216701f85f82')
created = []
paths={
'FLASH_IO0':[(25.65,10.2),(26.1,10.2),(26.2,10.1),(26.875,10.1)],
'FLASH_IO1':[(25.65,10.6),(26.1,10.6),(26.425,10.55)],
'SPICLK':[(25.65,11),(26.875,11)],
'FLASH_CLK':[(28.11,12.5),(28.11,12.05),(27.9,11.84),(27.9,11.8)],
'FLASH_CS':[(25.65,11.4),(26.1,11.4),(26.4,11.3),(27.0,11.5),(27.4,11.5)],
'FLASH_IO2':[(25.65,11.8),(26.1,11.8),(26.6,11.825)],
'FLASH_IO3':[(25.65,12.2),(26.1,12.2),(26.425,12.4)],
'VDD_SPI':[(25.65,12.6),(26.025,12.6),(26.025,12.8),(26.225,13),(26.425,13)],
}
for name, points in paths.items():
    for index, (a, c) in enumerate(zip(points, points[1:])):
        t = p.PCB_TRACK(b)
        t.SetStart(p.VECTOR2I(p.FromMM(a[0]), p.FromMM(a[1])))
        t.SetEnd(p.VECTOR2I(p.FromMM(c[0]), p.FromMM(c[1])))
        t.SetWidth(p.FromMM(0.15))
        t.SetLayer(p.F_Cu)
        t.SetNet(nets[name])
        t.SetLocked(True)
        t.SetUuid(p.KIID('f1a5c001-' + str(uuid.uuid5(namespace, f'{name}:track:{index}'))[9:]))
        b.Add(t)
        created.append(t.m_Uuid.AsString())
    v = p.PCB_VIA(b)
    v.SetPosition(p.VECTOR2I(p.FromMM(points[-1][0]), p.FromMM(points[-1][1])))
    v.SetWidth(p.FromMM(0.45))
    v.SetDrill(p.FromMM(0.2))
    v.SetViaType(p.VIATYPE_THROUGH)
    v.SetLayerPair(p.F_Cu, p.B_Cu)
    v.SetNet(nets[name])
    v.SetLocked(True)
    v.SetUuid(p.KIID('f1a5c001-' + str(uuid.uuid5(namespace, f'{name}:via'))[9:]))
    b.Add(v)
    created.append(v.m_Uuid.AsString())
p.ZONE_FILLER(b).Fill(b.Zones())
p.SaveBoard(str(trial), b)
trial_drc = trial.with_suffix('.json')
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(trial_drc), str(trial)], check=True)
final = json.loads(trial_drc.read_text())
electrical = {'clearance', 'shorting_items', 'hole_to_hole', 'hole_clearance', 'edge_clearance', 'track_width', 'via_annulus', 'via_diameter', 'drill_out_of_range', 'copper_edge_clearance', 'track_crossing', 'tracks_crossing', 'items_not_allowed', 'solder_mask_bridge'}
baseline = {(v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) for v in initial.get('violations', []) if v['type'] in electrical}
new_errors = [v for v in final.get('violations', []) if v['type'] in electrical and (v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) not in baseline]
assert not new_errors, json.dumps(new_errors, indent=2)
shutil.copy2(trial, args.output)
args.output.with_name(args.output.stem + '-drc.json').write_text(json.dumps(final, indent=2) + '\n')
args.output.with_name(args.output.stem + '-fanouts.json').write_text(json.dumps({'input': str(args.board.resolve()), 'preserve_board': str(args.preserve_board.resolve()), 'output': str(args.output.resolve()), 'removed_auto_flash_items': dict(removed), 'created_locked_item_uuids': created, 'new_electrical_errors': 0, 'footprint_positions_changed': False}, indent=2) + '\n')
print(f'Validated {len(created)} flash escape items saved to {args.output}; removed {dict(removed)}')
