"""Reconnect DC_GATE by moving only the two generated low-current VSYS sense branches.

Run using KiCad Python with explicit input and output paths. The final output
is published only after all DC_GATE/VSYS gaps close and no electrical DRC error
is added. Intermediate boards/reports are retained beside the output.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import pcbnew as pcb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('board', type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--kicad-cli', default='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve(), 'Use a distinct output for review'
args.output.parent.mkdir(parents=True, exist_ok=True)
folder = Path(__file__).resolve().parent
stages = [args.output.with_name(args.output.stem + suffix + '.kicad_pcb') for suffix in ['-source', '-opened', '-gate', '-restored']]
for stage in stages + [args.output]:
    for extension in ['.kicad_pro', '.kicad_dru']:
        source = args.board.with_suffix(extension)
        if source.exists():
            shutil.copy2(source, stage.with_suffix(extension))
shutil.copy2(args.board, stages[0])
source_drc = stages[0].with_suffix('.json')
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(source_drc), str(stages[0])], check=True)
initial = json.loads(source_drc.read_text())
if not any('[DC_GATE]' in i.get('description', '') for r in initial.get('unconnected_items', []) for i in r.get('items', [])):
    shutil.copy2(args.board, args.output)
    print('DC_GATE already connected; no copper changed')
    raise SystemExit(0)
board = pcb.LoadBoard(str(stages[0]))
namespace = uuid.UUID('311c3645-c6f2-4080-aaf5-cf1ebaa3a01d')
selected = {'b0a7c001-' + str(uuid.uuid5(namespace, f'{name}:{index}'))[9:] for name in ['vsys_wired_sense', 'vsys_usb_sense'] for index in range(2048)}
removed = []
for track in list(board.GetTracks()):
    if track.m_Uuid.AsString() in selected:
        assert track.GetNetname() == 'VSYS' and (isinstance(track, pcb.PCB_VIA) or pcb.ToMM(track.GetWidth()) <= 0.2)
        removed.append(track.m_Uuid.AsString())
        board.Delete(track)
assert removed, 'Expected generated VSYS sense branches were not found'
pcb.ZONE_FILLER(board).Fill(board.Zones())
pcb.SaveBoard(str(stages[1]), board)
opened_drc = stages[1].with_suffix('.json')
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(opened_drc), str(stages[1])], check=True)
subprocess.run([sys.executable, str(folder / 'route_remaining.py'), str(stages[1]), str(opened_drc), '--output', str(stages[2]), '--only-net', 'DC_GATE', '--rounds', '2', '--batch-size', '1', '--max-states', '300000'], check=True)
subprocess.run([sys.executable, str(folder / 'power_branches.py'), str(stages[2]), '--output', str(stages[3]), '--only-branch', 'vsys_wired_sense', '--only-branch', 'vsys_usb_sense'], check=True)
final_drc = stages[3].with_suffix('.json')
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(final_drc), str(stages[3])], check=True)
final = json.loads(final_drc.read_text())
electrical = {'clearance', 'shorting_items', 'hole_to_hole', 'hole_clearance', 'edge_clearance', 'track_width', 'via_annulus', 'via_diameter', 'drill_out_of_range', 'copper_edge_clearance', 'track_crossing', 'tracks_crossing', 'items_not_allowed'}
baseline = {(v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) for v in initial.get('violations', []) if v['type'] in electrical}
new_errors = [v for v in final.get('violations', []) if v['type'] in electrical and (v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) not in baseline]
remaining = [r for r in final.get('unconnected_items', []) if any(any('[' + net + ']' in i.get('description', '') for net in ['DC_GATE', 'VSYS']) for i in r.get('items', []))]
assert not new_errors, json.dumps(new_errors, indent=2)
assert not remaining, 'DC_GATE or VSYS remains disconnected: ' + json.dumps(remaining, indent=2)
shutil.copy2(stages[3], args.output)
args.output.with_name(args.output.stem + '-drc.json').write_text(json.dumps(final, indent=2) + '\n')
args.output.with_name(args.output.stem + '-repair.json').write_text(json.dumps({'input': str(args.board.resolve()), 'output': str(args.output.resolve()), 'replaced_sense_branch_items': removed, 'new_electrical_violations': 0, 'DC_GATE_and_VSYS_unconnected': 0}, indent=2) + '\n')
print(f'Validated DC_GATE repair saved to {args.output}')
