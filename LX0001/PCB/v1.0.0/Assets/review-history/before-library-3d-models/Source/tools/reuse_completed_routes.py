"""Guardedly graft complete donor nets onto an explicit, stable routing input.

Run with KiCad Python. Input copper is never removed or moved. Each donor net
is a transaction: gaps must decrease, no other net may acquire more gaps,
and electrical DRC plus the 0.10 mm drill/paste gate must pass. Rejected nets
are rolled back in full. New copied items remain unlocked. GND must already
be connected unless --allow-existing-ground-gaps is explicit; its gap count
may never increase. Pad/net mappings must match globally; each imported net requires exact
geometry for every participating footprint.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import pcbnew as p

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('board', type=Path)
parser.add_argument('--donor', type=Path, default=Path('/tmp/lx0001-combined-reduced-finite-check/Source/LX0001-astar.kicad_pcb'))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--only-net', action='append')
parser.add_argument('--max-nets', type=int, default=1000)
parser.add_argument('--allow-existing-ground-gaps', action='store_true', help='Permit existing GND gaps, but reject every candidate that increases their count')
parser.add_argument('--kicad-cli', default='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
parser.add_argument('--kicad-python', default='/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9')
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve() and args.donor.resolve() != args.output.resolve(), 'Use a distinct output'
assert args.max_nets > 0
args.output.parent.mkdir(parents=True, exist_ok=True)
folder = Path(__file__).resolve().parent
source_bytes = args.board.read_bytes()
donor_bytes = args.donor.read_bytes()
board = p.LoadBoard(str(args.board))
donor = p.LoadBoard(str(args.donor))
assert board.GetCopperLayerCount() == donor.GetCopperLayerCount() == 2
poses = []
for candidate in [board, donor]:
    poses.append({f.GetReference(): {'value': f.GetValue(), 'footprint': f.GetFPID().GetLibItemName(), 'position_iu': [f.GetPosition().x, f.GetPosition().y], 'rotation_deg': f.GetOrientationDegrees(), 'layer': f.GetLayer(), 'pads': sorted([[pad.GetNumber(), pad.GetNetname(), pad.GetPosition().x, pad.GetPosition().y, pad.GetOrientationDegrees(), pad.GetSize().x, pad.GetSize().y, pad.GetDrillSize().x, pad.GetDrillSize().y, pad.GetLayerSet().FmtBin()] for pad in f.Pads()])} for f in candidate.GetFootprints()})
pose_mismatches = [ref for ref in sorted(set(poses[0]) | set(poses[1])) if poses[0].get(ref) != poses[1].get(ref)]
assert set(poses[0]) == set(poses[1]), 'Footprint reference sets differ; nothing imported'
net_mappings = [{ref: sorted([pad[0], pad[1]] for pad in data['pads']) for ref, data in pose.items()} for pose in poses]
assert net_mappings[0] == net_mappings[1], 'Footprint pad/net mappings differ; nothing imported'
participating_footprints = collections.defaultdict(set)
for ref, data in poses[0].items():
    for pad in data['pads']:
        if pad[1]:
            participating_footprints[pad[1]].add(ref)
original_tracks = {}
for t in board.GetTracks():
    original_tracks[t.m_Uuid.AsString()] = {'net': t.GetNetname(), 'class': t.GetClass(), 'layer': t.GetLayer(), 'start_iu': [t.GetStart().x, t.GetStart().y], 'end_iu': [t.GetEnd().x, t.GetEnd().y], 'width_iu': t.GetWidth(p.F_Cu) if isinstance(t, p.PCB_VIA) else t.GetWidth(), 'drill_iu': t.GetDrillValue() if isinstance(t, p.PCB_VIA) else None, 'locked': t.IsLocked(), 'arc_mid_iu': [t.GetMid().x, t.GetMid().y] if isinstance(t, p.PCB_ARC) else None}
for extension in ['.kicad_pro', '.kicad_dru']:
    if args.board.with_suffix(extension).exists():
        shutil.copy2(args.board.with_suffix(extension), args.output.with_suffix(extension))
args.output.write_bytes(source_bytes)
work = args.output.with_name(args.output.stem + '-reuse-evidence')
work.mkdir(exist_ok=True)
reports = []
for name, path in [('input', args.output), ('donor', args.donor)]:
    drc_path = work / (name + '-drc.json')
    process = subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(drc_path), str(path)], capture_output=True, text=True)
    assert process.returncode in [0, 5] and drc_path.exists(), process.stdout + process.stderr
    reports.append(json.loads(drc_path.read_text()))
net_names = {n.GetNetname() for n in board.GetNetInfo().NetsByNetcode().values() if n.GetNetname()}
gap_counts = []
for report in reports:
    counts = collections.Counter()
    for record in report.get('unconnected_items', []):
        names = {name for item in record.get('items', []) for name in re.findall(r'\[([^\]]+)\]', item.get('description', '')) if name in net_names}
        assert len(names) == 1, 'Cannot identify DRC unconnected net: ' + json.dumps(record)
        counts[next(iter(names))] += 1
    gap_counts.append(counts)
current_report, donor_report = reports
current_gaps, donor_gaps = gap_counts
assert args.allow_existing_ground_gaps or not current_gaps['GND'], 'Input GND is disconnected; finish ground or explicitly allow existing gaps'
electrical = {'clearance', 'shorting_items', 'hole_to_hole', 'hole_clearance', 'edge_clearance', 'track_width', 'via_annulus', 'via_diameter', 'drill_out_of_range', 'copper_edge_clearance', 'track_crossing', 'tracks_crossing', 'items_not_allowed', 'solder_mask_bridge'}
assert not [v for v in current_report.get('violations', []) if v['type'] in electrical], 'Input has electrical DRC errors'
initial_paste = work / 'input-paste'
process = subprocess.run([args.kicad_python, str(folder / 'verify_design.py'), '--board', str(args.output), '--geometry-only', '--reports-dir', str(initial_paste)], capture_output=True, text=True)
assert process.returncode == 0, 'Input fails the independent paste-margin gate: ' + process.stdout + process.stderr
existing_ids = set(original_tracks)
donor_groups = collections.defaultdict(list)
for t in donor.GetTracks():
    name = t.GetNetname()
    if name and name != 'GND' and donor_gaps[name] == 0 and t.m_Uuid.AsString() not in existing_ids:
        donor_groups[name].append(t)
skipped_changed_poses = {name: sorted(participating_footprints[name] & set(pose_mismatches)) for name in donor_groups if current_gaps[name] > 0 and participating_footprints[name] & set(pose_mismatches)}
candidates = [name for name in donor_groups if current_gaps[name] > 0 and name not in skipped_changed_poses and (not args.only_net or name in args.only_net)]
candidates.sort(key=lambda name: (args.only_net.index(name) if args.only_net else len(donor_groups[name]), name))
log = {'input_board': str(args.board.resolve()), 'input_sha256': hashlib.sha256(source_bytes).hexdigest(), 'donor_board': str(args.donor.resolve()), 'donor_sha256': hashlib.sha256(donor_bytes).hexdigest(), 'output_board': str(args.output.resolve()), 'global_pad_net_mappings_match': True, 'donor_pose_mismatches': pose_mismatches, 'nets_skipped_for_changed_participating_footprints': skipped_changed_poses, 'allow_existing_ground_gaps': args.allow_existing_ground_gaps, 'original_item_count': len(original_tracks), 'donor_complete_candidates': candidates, 'input_gap_counts': dict(current_gaps), 'trials': [], 'accepted_nets': []}
for index, name in enumerate(candidates[:args.max_nets]):
    if not current_gaps[name]:
        continue
    checkpoint = args.output.read_bytes()
    existing_ids = {t.m_Uuid.AsString() for t in board.GetTracks()}
    target_nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
    imported = []
    for item in donor_groups[name]:
        uid = item.m_Uuid.AsString()
        if uid in existing_ids:
            continue
        duplicate = item.Duplicate()
        duplicate.SetParent(board)
        duplicate.SetNet(target_nets[name])
        duplicate.SetUuid(p.KIID(uid))
        duplicate.SetLocked(False)
        board.Add(duplicate)
        imported.append(uid)
    if not imported:
        continue
    p.ZONE_FILLER(board).Fill(board.Zones())
    p.SaveBoard(str(args.output), board)
    label = f'{index + 1:03d}-' + re.sub(r'[^A-Za-z0-9_-]', '_', name)
    drc_path = work / (label + '-drc.json')
    process = subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', str(drc_path), str(args.output)], capture_output=True, text=True)
    reasons = []
    next_report = None
    next_gaps = current_gaps.copy()
    if process.returncode not in [0, 5] or not drc_path.exists():
        reasons.append('DRC command failed: ' + process.stdout + process.stderr)
    else:
        next_report = json.loads(drc_path.read_text())
        next_gaps = collections.Counter()
        for record in next_report.get('unconnected_items', []):
            names = {n for item in record.get('items', []) for n in re.findall(r'\[([^\]]+)\]', item.get('description', '')) if n in net_names}
            if len(names) != 1:
                reasons.append('Unidentified DRC net: ' + json.dumps(record))
                continue
            next_gaps[next(iter(names))] += 1
        baseline_keys = {(v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) for v in current_report.get('violations', [])}
        new_errors = [v for v in next_report.get('violations', []) if v['type'] in electrical | {'via_dangling'} and (v['type'], tuple(sorted(i['uuid'] for i in v.get('items', [])))) not in baseline_keys]
        if new_errors:
            reasons.append({'new_electrical_or_dangling_via_violations': new_errors})
        if next_gaps[name] >= current_gaps[name]:
            reasons.append('Target net gaps did not decrease')
        worsened = {n: {'before': current_gaps[n], 'after': next_gaps[n]} for n in net_names if n != name and next_gaps[n] > current_gaps[n]}
        if worsened:
            reasons.append({'other_net_gaps_increased': worsened})
        if next_gaps['GND'] > current_gaps['GND']:
            reasons.append('GND gap count increased')
    paste_dir = work / (label + '-paste')
    if not reasons:
        process = subprocess.run([args.kicad_python, str(folder / 'verify_design.py'), '--board', str(args.output), '--geometry-only', '--reports-dir', str(paste_dir)], capture_output=True, text=True)
        if process.returncode:
            reasons.append('Independent paste-margin gate failed; see ' + str(paste_dir))
    # Reload and independently ensure all original routing and pad poses survived.
    candidate_board = p.LoadBoard(str(args.output))
    candidate_tracks = {}
    for t in candidate_board.GetTracks():
        candidate_tracks[t.m_Uuid.AsString()] = {'net': t.GetNetname(), 'class': t.GetClass(), 'layer': t.GetLayer(), 'start_iu': [t.GetStart().x, t.GetStart().y], 'end_iu': [t.GetEnd().x, t.GetEnd().y], 'width_iu': t.GetWidth(p.F_Cu) if isinstance(t, p.PCB_VIA) else t.GetWidth(), 'drill_iu': t.GetDrillValue() if isinstance(t, p.PCB_VIA) else None, 'locked': t.IsLocked(), 'arc_mid_iu': [t.GetMid().x, t.GetMid().y] if isinstance(t, p.PCB_ARC) else None}
    if not all(candidate_tracks.get(uid) == value for uid, value in original_tracks.items()):
        reasons.append('An original routing item changed after save/reload')
    candidate_poses = {f.GetReference(): {'value': f.GetValue(), 'footprint': f.GetFPID().GetLibItemName(), 'position_iu': [f.GetPosition().x, f.GetPosition().y], 'rotation_deg': f.GetOrientationDegrees(), 'layer': f.GetLayer(), 'pads': sorted([[pad.GetNumber(), pad.GetNetname(), pad.GetPosition().x, pad.GetPosition().y, pad.GetOrientationDegrees(), pad.GetSize().x, pad.GetSize().y, pad.GetDrillSize().x, pad.GetDrillSize().y, pad.GetLayerSet().FmtBin()] for pad in f.Pads()])} for f in candidate_board.GetFootprints()}
    if candidate_poses != poses[0]:
        reasons.append('Footprint/pad pose or net geometry changed')
    trial = {'net': name, 'participating_footprints_verified': sorted(participating_footprints[name]), 'imported_uuids': imported, 'imported_count': len(imported), 'gaps_before': current_gaps[name], 'gaps_after_trial': next_gaps[name], 'accepted': not reasons, 'rejection_reasons': reasons, 'drc': str(drc_path), 'paste_report_directory': str(paste_dir)}
    if reasons:
        rejected = work / (label + '-rejected.kicad_pcb')
        rejected.write_bytes(args.output.read_bytes())
        for extension in ['.kicad_pro', '.kicad_dru']:
            if args.output.with_suffix(extension).exists():
                shutil.copy2(args.output.with_suffix(extension), rejected.with_suffix(extension))
        args.output.write_bytes(checkpoint)
        trial['rejected_board'] = str(rejected)
        board = p.LoadBoard(str(args.output))
        print(f'Rejected {name}: {len(reasons)} guard failures; rolled back {len(imported)} items', flush=True)
    else:
        board = candidate_board
        current_report, current_gaps = next_report, next_gaps
        log['accepted_nets'].append(name)
        print(f'Accepted {name}: {trial["gaps_before"]}->{trial["gaps_after_trial"]} gaps, {len(imported)} unlocked items', flush=True)
    log['trials'].append(trial)
    args.output.with_name(args.output.stem + '-reuse-audit.json').write_text(json.dumps(log, indent=2) + '\n')
    assert args.board.read_bytes() == source_bytes and args.donor.read_bytes() == donor_bytes, 'An input changed during reuse; stop and review immutable snapshots'
log['final_gap_counts'] = dict(current_gaps)
log['final_unconnected_count'] = len(current_report.get('unconnected_items', []))
log['output_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
log['all_original_items_preserved'] = True
args.output.with_name(args.output.stem + '-reuse-audit.json').write_text(json.dumps(log, indent=2) + '\n')
args.output.with_name(args.output.stem + '-drc.json').write_text(json.dumps(current_report, indent=2) + '\n')
print(f'Saved {args.output}; accepted {len(log["accepted_nets"])} nets; {log["final_unconnected_count"]} gaps remain')
