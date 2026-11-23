"""Escape U1 UART/strap pins and place two UART test pads beside the MCU.

KiCad Python: mcu_uart_fanout.py INPUT.kicad_pcb --output REVIEW.kicad_pcb
  --protected-board BASELINE.kicad_pcb [--project INPUT.kicad_pro]

Input is never modified. Use the combined manual-fanout board itself as the
protected reference to preserve every earlier fanout. Only the reviewed top
EP GND via/spoke may move. Added items have deterministic a4710001- UUIDs.
A repeat run replaces only these owned items. If a less-complete protected
baseline is supplied, colliding generated +3V3/ESP_EN segments may be removed
and are logged for subsequent routing; other nets are never silently removed.

TP11 UART_TX moves to B(23.3,8.5); TP12 UART_RX moves to B(22.0,8.5).
Both UART nets are completed locally. STRAP45/46 end at accessible .45/.20mm
via anchors for global routing. C4 at B(21.4,10.3) clears the test pads.
The two strap via-dangling warnings are expected until global routing.
"""
import argparse
import collections
import json
from pathlib import Path
import shutil
import subprocess
import uuid
import pcbnew as pcb

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('board',type=Path)
parser.add_argument('--output',required=True,type=Path)
parser.add_argument('--protected-board',required=True,type=Path)
parser.add_argument('--project',type=Path)
parser.add_argument('--kicad-cli',default=shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args=parser.parse_args()
assert args.board.resolve()!=args.output.resolve(), 'Use a distinct reviewed output'
project=args.project or args.board.with_suffix('.kicad_pro')
assert project.exists(), 'Supply project rules with --project'
args.output.parent.mkdir(parents=True,exist_ok=True)
trial_path=args.output.with_name('.'+args.output.stem+'.uart-trial.kicad_pcb')
before_path=args.output.with_name('.'+args.output.stem+'.uart-before.kicad_pcb')
for target in [args.output,trial_path,before_path]:
    for suffix in ['.kicad_pro','.kicad_dru']:
        source=project.with_suffix(suffix)
        if source.exists() and source.resolve()!=target.with_suffix(suffix).resolve():
            shutil.copy2(source,target.with_suffix(suffix))
before_path.write_bytes(args.board.read_bytes())
board=pcb.LoadBoard(str(before_path))
reference=pcb.LoadBoard(str(args.protected_board))
protected={t.m_Uuid.AsString() for t in reference.GetTracks()}
initial={t.m_Uuid.AsString():t for t in board.GetTracks()}
assert protected<=initial.keys(), 'Protected reference contains copper missing from input'
board.BuildConnectivity();pcb.ZONE_FILLER(board).Fill(board.Zones());pcb.SaveBoard(str(before_path),board)
before_drc=args.output.with_suffix('.uart-before.json')
after_drc=args.output.with_suffix('.uart-after.json')
run=subprocess.run([args.kicad_cli,'pcb','drc','--format','json','--output',str(before_drc),str(before_path)],capture_output=True,text=True)
assert run.returncode==0,run.stderr or run.stdout
before=json.loads(before_drc.read_text())
for t in list(board.GetTracks()):
    if t.m_Uuid.AsString().startswith('a4710001-'):
        board.Delete(t)
original=list(board.GetTracks())
fps={f.GetReference():f for f in board.GetFootprints()}
nets={n.GetNetname():n for n in board.GetNetInfo().NetsByNetcode().values()}
for number,net,x in [('49','UART_TX',22.4),('50','UART_RX',22.0),('51','STRAP45',21.6),('52','STRAP46',21.2)]:
    pad=next(p for p in fps['U1'].Pads() if p.GetNumber()==number)
    assert pad.GetNetname()==net and abs(pcb.ToMM(pad.GetPosition().x)-x)<.00001 and abs(pcb.ToMM(pad.GetPosition().y)-6.55)<.00001
changed_manual=[];new=[]
for t in original:
    if t.m_Uuid.AsString()=='63c01239-9f60-4ef1-a4ad-b7d7817f69b3':
        assert isinstance(t,pcb.PCB_VIA) and t.GetNetname()=='GND'
        assert (round(pcb.ToMM(t.GetPosition().x),5),round(pcb.ToMM(t.GetPosition().y),5)) in [(22.2,7.45),(23.2,7.55)]
        t.SetPosition(pcb.VECTOR2I(pcb.FromMM(23.2),pcb.FromMM(7.55)))
        t.SetFrontTentingMode(pcb.TENTING_MODE_TENTED);t.SetBackTentingMode(pcb.TENTING_MODE_TENTED);t.SetLocked(True)
        changed_manual.append(t.m_Uuid.AsString());new.append(t)
    if t.m_Uuid.AsString()=='6b39abb5-167d-43ac-9420-ad70181718e3':
        assert t.GetNetname()=='GND' and t.GetLayer()==pcb.F_Cu
        t.SetStart(pcb.VECTOR2I(pcb.FromMM(23.2),pcb.FromMM(8.2)));t.SetEnd(pcb.VECTOR2I(pcb.FromMM(23.2),pcb.FromMM(7.55)));t.SetLocked(True)
        changed_manual.append(t.m_Uuid.AsString());new.append(t)
assert len(changed_manual)==2, 'Reviewed EP ground via/spoke were not found'
placements={'TP11':[23.3,8.5,0,'Bottom'],'TP12':[22.0,8.5,0,'Bottom']}
for ref,(x,y,angle,side) in placements.items():
    assert fps[ref].GetLayer()==pcb.B_Cu
    fps[ref].SetPosition(pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y)));fps[ref].SetOrientationDegrees(angle)
namespace=uuid.UUID('94fcd9be-8fca-44f1-b97d-4cd8427d3d19')
paths=[('STRAP46',pcb.F_Cu,[(21.2,6.55),(21.2,7.05),(20.8,7.45),(20.8,7.55)]),
       ('STRAP45',pcb.F_Cu,[(21.6,6.55),(21.6,7.05),(21.4,7.25),(21.4,7.55)]),
       ('UART_RX',pcb.F_Cu,[(22,6.55),(22,7.55)]),
       ('UART_TX',pcb.F_Cu,[(22.4,6.55),(22.4,7.05),(22.6,7.25),(22.6,7.55)]),
       ('UART_RX',pcb.B_Cu,[(22,7.55),(22,8.5)]),
       ('UART_TX',pcb.B_Cu,[(22.6,7.55),(22.6,7.95),(23.15,8.5),(23.3,8.5)])]
for path_index,(net,layer,points) in enumerate(paths):
    for index,(a,c) in enumerate(zip(points,points[1:])):
        t=pcb.PCB_TRACK(board);t.SetStart(pcb.VECTOR2I(pcb.FromMM(a[0]),pcb.FromMM(a[1])));t.SetEnd(pcb.VECTOR2I(pcb.FromMM(c[0]),pcb.FromMM(c[1])))
        t.SetWidth(pcb.FromMM(.15));t.SetLayer(layer);t.SetNet(nets[net]);t.SetLocked(True)
        t.SetUuid(pcb.KIID('a4710001-'+str(uuid.uuid5(namespace,f'track:{path_index}:{index}'))[9:]));board.Add(t);new.append(t)
    if layer==pcb.F_Cu:
        v=pcb.PCB_VIA(board);v.SetPosition(pcb.VECTOR2I(pcb.FromMM(points[-1][0]),pcb.FromMM(points[-1][1])));v.SetWidth(pcb.FromMM(.45));v.SetDrill(pcb.FromMM(.2))
        v.SetLayerPair(pcb.F_Cu,pcb.B_Cu);v.SetViaType(pcb.VIATYPE_THROUGH);v.SetNet(nets[net]);v.SetLocked(True)
        v.SetFrontTentingMode(pcb.TENTING_MODE_TENTED);v.SetBackTentingMode(pcb.TENTING_MODE_TENTED)
        v.SetUuid(pcb.KIID('a4710001-'+str(uuid.uuid5(namespace,f'via:{net}'))[9:]));board.Add(v);new.append(v)
removed=[]
for old in original:
    if old.m_Uuid.AsString() in changed_manual:continue
    collided=False
    for item in new:
        if old.GetNetname()==item.GetNetname():continue
        for layer in [pcb.F_Cu,pcb.B_Cu]:
            if old.IsOnLayer(layer) and item.IsOnLayer(layer) and old.GetEffectiveShape(layer).Collide(item.GetEffectiveShape(layer),pcb.FromMM(.132)):
                collided=True
    if collided:
        assert old.m_Uuid.AsString() not in protected, f'Would touch protected copper {old.m_Uuid.AsString()}'
        assert not old.m_Uuid.AsString().startswith(('c0a7c0de-','a4710001-')), 'Would remove another manual fanout'
        assert old.GetNetname() in ['+3V3','ESP_EN'], f'Unexpected generated obstacle on {old.GetNetname()}'
        removed.append({'uuid':old.m_Uuid.AsString(),'net':old.GetNetname()});board.Delete(old)
for item in new:
    if not isinstance(item,pcb.PCB_VIA):continue
    point=item.GetPosition()
    for f in board.GetFootprints():
        for pad in f.Pads():
            for layer in [pcb.F_Cu,pcb.B_Cu]:
                if pad.IsOnLayer(layer):
                    assert not pad.GetEffectiveShape(layer).Collide(pcb.SEG(point,point),pcb.FromMM(.25)), f'Via-in-pad/paste at {f.GetReference()}/{pad.GetNumber()}'
board.BuildConnectivity();pcb.ZONE_FILLER(board).Fill(board.Zones());pcb.SaveBoard(str(trial_path),board)
run=subprocess.run([args.kicad_cli,'pcb','drc','--format','json','--output',str(after_drc),str(trial_path)],capture_output=True,text=True)
assert run.returncode==0,run.stderr or run.stdout
after=json.loads(after_drc.read_text())
electrical={'clearance','shorting_items','hole_to_hole','hole_clearance','edge_clearance','track_width','via_annulus','via_diameter','drill_out_of_range','copper_edge_clearance','track_crossing','tracks_crossing','items_not_allowed','courtyard_overlap'}
base={(v['type'],tuple(sorted(i['uuid'] for i in v.get('items',[])))) for v in before.get('violations',[]) if v['type'] in electrical}
new_errors=[v for v in after.get('violations',[]) if v['type'] in electrical and (v['type'],tuple(sorted(i['uuid'] for i in v.get('items',[])))) not in base]
remaining_uart=[r for r in after.get('unconnected_items',[]) if any('[UART_TX]' in i.get('description','') or '[UART_RX]' in i.get('description','') for i in r.get('items',[]))]
audit={'input':str(args.board.resolve()),'output':str(args.output.resolve()),'protected_items':len(protected),
       'reviewed_baseline_changes':changed_manual,'removed_generated':removed,'placements':placements,
       'escape_anchors':{'STRAP46':[20.8,7.55],'STRAP45':[21.4,7.55],'UART_RX':[22,7.55],'UART_TX':[22.6,7.55]},
       'new_items':len(new)-2,'before_unconnected':len(before.get('unconnected_items',[])),
       'after_unconnected':len(after.get('unconnected_items',[])),'new_electrical_errors':new_errors,
       'uart_unconnected':remaining_uart,'after_violation_counts':dict(collections.Counter(v['type'] for v in after.get('violations',[]))),
       'remaining_work':['Global route from STRAP45/46 anchors to R102/R103','Reroute any logged generated +3V3/ESP_EN removals'],'output_saved':False}
if not new_errors and not remaining_uart:
    args.output.write_bytes(trial_path.read_bytes());audit['output_saved']=True
args.output.with_suffix('.uart-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
if not audit['output_saved']:raise SystemExit('No reviewed output saved; inspect trial DRC')
for temporary in [trial_path,before_path]:
    for suffix in ['.kicad_pcb','.kicad_pro','.kicad_dru']:temporary.with_suffix(suffix).unlink(missing_ok=True)
