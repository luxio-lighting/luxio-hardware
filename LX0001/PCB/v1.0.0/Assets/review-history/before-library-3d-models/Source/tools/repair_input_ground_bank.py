"""Move the four input GND return vias clear of the terminal's SMT paste lands.

KiCad Python usage:
  repair_input_ground_bank.py INPUT.kicad_pcb --output REVIEW.kicad_pcb
  [--project INPUT.kicad_pro]

The four original 0.60/0.30 mm GND vias and the original vertical GND spine
are recognized by their exact geometry, then moved in place with UUIDs kept.
The same repaired geometry is recognized on a repeat run. No other item is
changed. The 1.8 mm horizontal terminal bridge is retained; the vertical feed
becomes 1.2 mm wide. Four parallel plated barrels remain, all tented both sides.
This preserves the via-bank geometry for the separate load/thermal review;
it does not independently certify a continuous-current rating.

Input and output must differ. A separate trial is refilled and DRC checked.
The output is saved only when no new violation or disconnect is introduced,
and every relocated via clears all pads/paste, drills and via keepouts.
"""
import argparse
import collections
import json
from pathlib import Path
import shutil
import subprocess
import pcbnew as pcb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('board', type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--project', type=Path)
parser.add_argument('--kicad-cli', default=shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve(), 'Use a distinct reviewed output'
project = args.project or args.board.with_suffix('.kicad_pro')
assert project.exists(), 'Project rules required; provide --project for detached copies'
args.output.parent.mkdir(parents=True, exist_ok=True)
baseline_path = args.output.with_name('.' + args.output.stem + '.ground-bank-before.kicad_pcb')
trial_path = args.output.with_name('.' + args.output.stem + '.ground-bank-trial.kicad_pcb')
for target in [baseline_path, trial_path, args.output]:
    for suffix in ['.kicad_pro', '.kicad_dru']:
        source = project.with_suffix(suffix)
        destination = target.with_suffix(suffix)
        if source.exists() and source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
baseline_path.write_bytes(args.board.read_bytes())
board = pcb.LoadBoard(str(baseline_path))
board.BuildConnectivity()
pcb.ZONE_FILLER(board).Fill(board.Zones())
pcb.SaveBoard(str(baseline_path), board)
before_drc = args.output.with_suffix('.ground-bank-before.json')
after_drc = args.output.with_suffix('.ground-bank-after.json')
result = subprocess.run([args.kicad_cli,'pcb','drc','--format','json','--output',str(before_drc),str(baseline_path)],capture_output=True,text=True)
assert result.returncode == 0, result.stderr or result.stdout
before = json.loads(before_drc.read_text())
old_positions = [(13.6,y) for y in [6.7,7.4,8.1,8.8]]
new_positions = [(13.85,y) for y in [4.2,4.9,5.6,6.3]]
changes = []
bank = []
for old,new in zip(old_positions,new_positions):
    matches = []
    for item in board.GetTracks():
        if not isinstance(item,pcb.PCB_VIA) or item.GetNetname()!='GND':
            continue
        xy=(round(pcb.ToMM(item.GetPosition().x),5),round(pcb.ToMM(item.GetPosition().y),5))
        if xy in [old,new]:
            matches.append(item)
    assert len(matches)==1, f'Expected one original/repaired GND via at {old}/{new}; found {len(matches)}'
    via=matches[0]
    assert via.GetWidth(pcb.F_Cu)==pcb.FromMM(.6) and via.GetWidth(pcb.B_Cu)==pcb.FromMM(.6) and via.GetDrillValue()==pcb.FromMM(.3), 'Unexpected bank via dimensions'
    previous=[pcb.ToMM(via.GetPosition().x),pcb.ToMM(via.GetPosition().y)]
    via.SetPosition(pcb.VECTOR2I(pcb.FromMM(new[0]),pcb.FromMM(new[1])))
    via.SetFrontTentingMode(pcb.TENTING_MODE_TENTED)
    via.SetBackTentingMode(pcb.TENTING_MODE_TENTED)
    via.SetLocked(True)
    bank.append(via)
    changes.append({'uuid':via.m_Uuid.AsString(),'from_mm':previous,'to_mm':list(new)})
spines=[]
for item in board.GetTracks():
    if isinstance(item,pcb.PCB_VIA) or item.GetNetname()!='GND' or item.GetLayer()!=pcb.F_Cu:
        continue
    endpoints={tuple(round(pcb.ToMM(v),5) for v in [item.GetStart().x,item.GetStart().y]),tuple(round(pcb.ToMM(v),5) for v in [item.GetEnd().x,item.GetEnd().y])}
    if endpoints in [{(13.6,6.7),(13.6,8.8)},{(13.85,4.2),(13.85,8.0)}]:
        spines.append(item)
assert len(spines)==1, f'Expected one original/repaired vertical input GND spine; found {len(spines)}'
spine=spines[0]
spine.SetStart(pcb.VECTOR2I(pcb.FromMM(13.85),pcb.FromMM(4.2)))
spine.SetEnd(pcb.VECTOR2I(pcb.FromMM(13.85),pcb.FromMM(8.0)))
spine.SetWidth(pcb.FromMM(1.2))
spine.SetLocked(True)
# Vias are intentionally kept outside copper/paste lands on BOTH faces,
# including GND pads; same-net DRC alone would not catch via-in-pad.
all_pads=[pad for footprint in board.GetFootprints() for pad in footprint.Pads()]
ruleareas=[zone for zone in board.Zones() if zone.GetIsRuleArea() and zone.GetDoNotAllowVias()]
ruleareas += [zone for f in board.GetFootprints() for zone in f.Zones() if zone.GetIsRuleArea() and zone.GetDoNotAllowVias()]
for via in bank:
    point=via.GetPosition()
    for pad in all_pads:
        for layer in [pcb.F_Cu,pcb.B_Cu]:
            if pad.IsOnLayer(layer):
                assert not pad.GetEffectiveShape(layer).Collide(pcb.SEG(point,point),pcb.FromMM(.325)), f'Bank via overlaps pad/paste {pad.GetParentFootprint().GetReference()}/{pad.GetNumber()}'
        if pad.HasDrilledHole():
            assert not pad.GetEffectiveHoleShape().Collide(pcb.SEG(point,point),pcb.FromMM(.405)), 'Bank via violates pad drill spacing'
    for other in board.GetTracks():
        if not isinstance(other,pcb.PCB_VIA) or other.m_Uuid.AsString()==via.m_Uuid.AsString():
            continue
        q=other.GetPosition()
        min_distance=pcb.FromMM(.405)+other.GetDrillValue()/2
        assert (point.x-q.x)**2+(point.y-q.y)**2>=min_distance**2, 'Bank via violates via drill spacing'
    for area in ruleareas:
        assert not area.Outline().Collide(pcb.SEG(point,point),pcb.FromMM(.305)), 'Bank via enters prohibited rule area'
board.BuildConnectivity()
pcb.ZONE_FILLER(board).Fill(board.Zones())
pcb.SaveBoard(str(trial_path),board)
result = subprocess.run([args.kicad_cli,'pcb','drc','--format','json','--output',str(after_drc),str(trial_path)],capture_output=True,text=True)
assert result.returncode == 0, result.stderr or result.stdout
after=json.loads(after_drc.read_text())
existing={(v['type'],tuple(sorted(i['uuid'] for i in v.get('items',[])))) for v in before.get('violations',[])}
new_violations=[v for v in after.get('violations',[]) if (v['type'],tuple(sorted(i['uuid'] for i in v.get('items',[])))) not in existing]
objects={x.m_Uuid.AsString():x for x in list(board.GetTracks())+[pad for f in board.GetFootprints() for pad in f.Pads()]+list(board.Zones())}
counts=[]
for report in [before,after]:
    per_net=collections.Counter()
    for record in report.get('unconnected_items',[]):
        names={objects[i['uuid']].GetNetname() for i in record.get('items',[]) if i['uuid'] in objects}
        per_net['|'.join(sorted(names))]+=1
    counts.append(dict(per_net))
increased={net:count for net,count in counts[1].items() if count>counts[0].get(net,0)}
log={'input_board':str(args.board.resolve()),'output_board':str(args.output.resolve()),'vias':changes,
     'spine_uuid':spine.m_Uuid.AsString(),'spine_width_mm':1.2,'spine_endpoints_mm':[[13.85,4.2],[13.85,8.0]],
     'before_violations':dict(collections.Counter(v['type'] for v in before.get('violations',[]))),
     'after_violations':dict(collections.Counter(v['type'] for v in after.get('violations',[]))),
     'before_unconnected':counts[0],'after_unconnected':counts[1],
     'new_violations':new_violations,'increased_disconnects':increased,'output_saved':False}
if not new_violations and not increased:
    args.output.write_bytes(trial_path.read_bytes())
    log['output_saved']=True
args.output.with_suffix('.ground-bank.json').write_text(json.dumps(log,indent=2)+'\n')
print(json.dumps({'output_saved':log['output_saved'],'new_violation_types':[v['type'] for v in new_violations],
                  'increased_disconnects':increased,'via_count':4,'spine_width_mm':1.2},indent=2))
if not log['output_saved']:
    raise SystemExit('No output board saved: inspect the private trial and DRC report')
for target in [baseline_path,trial_path]:
    for suffix in ['.kicad_pcb','.kicad_pro','.kicad_dru']:
        target.with_suffix(suffix).unlink(missing_ok=True)
