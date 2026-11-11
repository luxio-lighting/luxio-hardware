"""Remove only generated low-current power branches from a distinct routing baseline.

Retain the 0.6 mm USB drain branch, 0.4 mm buck branch, and every item outside
our exact auxiliary-branch UUID namespace. Existing retained geometry and
locks are independently compared after save/reload. No autorouter is run.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid
import pcbnew as p

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('board', type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--kicad-cli', default='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve(), 'A distinct output is required'
args.output.parent.mkdir(parents=True, exist_ok=True)
source_bytes = args.board.read_bytes()
for extension in ['.kicad_pro', '.kicad_dru']:
    if args.board.with_suffix(extension).exists():
        shutil.copy2(args.board.with_suffix(extension), args.output.with_suffix(extension))
source_drc = args.output.with_name(args.output.stem + '-before-drc.json')
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(source_drc), str(args.board)], check=True)
board = p.LoadBoard(str(args.board))
namespace = uuid.UUID('311c3645-c6f2-4080-aaf5-cf1ebaa3a01d')
branches = ['dc_cap', 'dc_enable', 'dc_anode', 'dc_presence', 'vsys_usb_drain', 'vsys_wired_sense', 'vsys_usb_sense', 'vsys_buck', 'vsys_zener', 'vsys_pullup', 'vsys_test', 'led_bleed']
retain_branches = {'vsys_usb_drain', 'vsys_buck'}
branch_ids = {'b0a7c001-' + str(uuid.uuid5(namespace, f'{branch}:{index}'))[9:]: branch for branch in branches for index in range(2048)}
before = {}
footprints_before = {}
removed = []
retained_branch_counts = collections.Counter()
for item in board.GetTracks():
    key = item.m_Uuid.AsString()
    before[key] = {'uuid': key, 'type': item.GetClass(), 'net': item.GetNetname(), 'layer': item.GetLayer(), 'start_iu': [item.GetStart().x, item.GetStart().y], 'end_iu': [item.GetEnd().x, item.GetEnd().y], 'width_iu': item.GetWidth(p.F_Cu) if isinstance(item, p.PCB_VIA) else item.GetWidth(), 'drill_iu': item.GetDrillValue() if isinstance(item, p.PCB_VIA) else None, 'locked': item.IsLocked(), 'arc_mid_iu': [item.GetMid().x, item.GetMid().y] if isinstance(item, p.PCB_ARC) else None}
    if key.startswith('b0a7c001-'):
        assert key in branch_ids, f'Unknown generated-branch UUID: {key}'
        branch = branch_ids[key]
        if branch in retain_branches:
            retained_branch_counts[branch] += 1
        else:
            assert isinstance(item, p.PCB_VIA) or item.GetWidth() <= p.FromMM(0.2), f'Refusing to remove a wide conductor: {branch} {key}'
            removed.append(dict(before[key], branch=branch))
for footprint in board.GetFootprints():
    footprints_before[footprint.m_Uuid.AsString()] = {'reference': footprint.GetReference(), 'value': footprint.GetValue(), 'position_iu': [footprint.GetPosition().x, footprint.GetPosition().y], 'rotation_deg': footprint.GetOrientationDegrees(), 'layer': footprint.GetLayer(), 'pads': {pad.m_Uuid.AsString(): [pad.GetNumber(), pad.GetNetname(), pad.GetPosition().x, pad.GetPosition().y, pad.GetOrientationDegrees(), pad.GetSize().x, pad.GetSize().y, pad.GetDrillSize().x, pad.GetDrillSize().y, pad.GetLayerSet().FmtBin()] for pad in footprint.Pads()}}
assert all(retained_branch_counts[branch] for branch in retain_branches), 'Required USB/buck branches were not found'
removed_ids = {row['uuid'] for row in removed}
for item in list(board.GetTracks()):
    if item.m_Uuid.AsString() in removed_ids:
        board.Delete(item)
p.ZONE_FILLER(board).Fill(board.Zones())
p.SaveBoard(str(args.output), board)
reloaded = p.LoadBoard(str(args.output))
after = {}
footprints_after = {}
for item in reloaded.GetTracks():
    key = item.m_Uuid.AsString()
    after[key] = {'uuid': key, 'type': item.GetClass(), 'net': item.GetNetname(), 'layer': item.GetLayer(), 'start_iu': [item.GetStart().x, item.GetStart().y], 'end_iu': [item.GetEnd().x, item.GetEnd().y], 'width_iu': item.GetWidth(p.F_Cu) if isinstance(item, p.PCB_VIA) else item.GetWidth(), 'drill_iu': item.GetDrillValue() if isinstance(item, p.PCB_VIA) else None, 'locked': item.IsLocked(), 'arc_mid_iu': [item.GetMid().x, item.GetMid().y] if isinstance(item, p.PCB_ARC) else None}
for footprint in reloaded.GetFootprints():
    footprints_after[footprint.m_Uuid.AsString()] = {'reference': footprint.GetReference(), 'value': footprint.GetValue(), 'position_iu': [footprint.GetPosition().x, footprint.GetPosition().y], 'rotation_deg': footprint.GetOrientationDegrees(), 'layer': footprint.GetLayer(), 'pads': {pad.m_Uuid.AsString(): [pad.GetNumber(), pad.GetNetname(), pad.GetPosition().x, pad.GetPosition().y, pad.GetOrientationDegrees(), pad.GetSize().x, pad.GetSize().y, pad.GetDrillSize().x, pad.GetDrillSize().y, pad.GetLayerSet().FmtBin()] for pad in footprint.Pads()}}
assert set(after) == set(before) - removed_ids, 'Unexpected track/via added or removed'
assert all(after[key] == before[key] for key in after), 'Retained track/via geometry or lock changed'
assert footprints_after == footprints_before, 'Footprint or pad geometry changed'
assert args.board.read_bytes() == source_bytes, 'Input PCB changed during review'
output_drc = args.output.with_name(args.output.stem + '-drc.json')
subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(output_drc), str(args.output)], check=True)
a = json.loads(source_drc.read_text())
b = json.loads(output_drc.read_text())
initial_violations = {(v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) for v in a.get('violations', [])}
new_violations = [v for v in b.get('violations', []) if (v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) not in initial_violations]
electrical = {'clearance', 'shorting_items', 'hole_to_hole', 'hole_clearance', 'edge_clearance', 'track_width', 'via_annulus', 'via_diameter', 'drill_out_of_range', 'copper_edge_clearance', 'track_crossing', 'tracks_crossing', 'items_not_allowed', 'solder_mask_bridge'}
assert not [v for v in new_violations if v['type'] in electrical], 'New electrical DRC error'
report = {'input_board': str(args.board.resolve()), 'input_sha256': hashlib.sha256(source_bytes).hexdigest(), 'output_board': str(args.output.resolve()), 'output_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(), 'input_tracks_and_vias': len(before), 'output_tracks_and_vias': len(after), 'removed_count': len(removed), 'removed_by_branch': dict(collections.Counter(row['branch'] for row in removed)), 'retained_auxiliary_branches': dict(retained_branch_counts), 'removed_items': removed, 'all_retained_items_exactly_preserved': True, 'all_footprints_and_pads_exactly_preserved': True, 'input_file_unchanged': True, 'unconnected_before': len(a.get('unconnected_items', [])), 'unconnected_after': len(b.get('unconnected_items', [])), 'drc_before_categories': dict(collections.Counter(v['type'] for v in a.get('violations', []))), 'drc_after_categories': dict(collections.Counter(v['type'] for v in b.get('violations', []))), 'new_drc_violations': new_violations, 'new_electrical_drc_violations': 0, 'before_drc': str(source_drc), 'after_drc': str(output_drc)}
audit = args.output.with_name(args.output.stem + '-audit.json')
audit.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: value for key, value in report.items() if key not in ['removed_items', 'new_drc_violations']}, indent=2))
