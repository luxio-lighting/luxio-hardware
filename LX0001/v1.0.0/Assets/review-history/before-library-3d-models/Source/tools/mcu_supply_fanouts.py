"""Add the reviewed U1.46 and R22 supply escapes before other signal routing.

Run with KiCad Python and distinct INPUT --output OUTPUT paths. These escape
vias give the 3.3 V network access to both layers outside component paste.
The utility does not replace the final connectivity/DRC/paste release checks.
"""
import argparse
import json
from pathlib import Path
import shutil
import uuid
import pcbnew as p

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('board',type=Path)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
assert args.board.resolve()!=args.output.resolve()
b=p.LoadBoard(str(args.board))
net=b.FindNet('+3V3')
for ref,number,xy in [('U1','46',(23.6,6.55)),('R22','1',(27.9,6.425))]:
    pad=next(a for f in b.GetFootprints() if f.GetReference()==ref for a in f.Pads() if a.GetNumber()==number)
    assert pad.GetNetname()=='+3V3'
    assert abs(p.ToMM(pad.GetPosition().x)-xy[0])<.001
    assert abs(p.ToMM(pad.GetPosition().y)-xy[1])<.001
for item in list(b.GetTracks()):
    if item.m_Uuid.AsString().startswith(('c0a7aa01-','c0a7aa02-')):
        b.Delete(item)
namespace=uuid.UUID('dfc65931-46b2-47e3-b84a-1c47a1be419e')
added=[]
for prefix,layer,points in [
    ('c0a7aa01-',p.F_Cu,[(23.6,6.55),(23.6,7.15),(23.9,7.45),(23.9,7.55)]),
    ('c0a7aa02-',p.B_Cu,[(27.9,6.425),(27.5,6.425),(27.475,6.45),(26.45,6.35)]),
]:
    for index,(a,z) in enumerate(zip(points,points[1:])):
        t=p.PCB_TRACK(b)
        t.SetStart(p.VECTOR2I(p.FromMM(a[0]),p.FromMM(a[1])))
        t.SetEnd(p.VECTOR2I(p.FromMM(z[0]),p.FromMM(z[1])))
        t.SetLayer(layer);t.SetWidth(p.FromMM(.2));t.SetNet(net);t.SetLocked(True)
        identity=prefix+str(uuid.uuid5(namespace,prefix+str(index)))[9:]
        t.SetUuid(p.KIID(identity));b.Add(t);added.append(identity)
    x,y=points[-1]
    v=p.PCB_VIA(b);v.SetPosition(p.VECTOR2I(p.FromMM(x),p.FromMM(y)))
    v.SetWidth(p.FromMM(.45));v.SetDrill(p.FromMM(.2));v.SetViaType(p.VIATYPE_THROUGH)
    v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetNet(net);v.SetLocked(True)
    identity=prefix+str(uuid.uuid5(namespace,prefix+'via'))[9:]
    v.SetUuid(p.KIID(identity));b.Add(v);added.append(identity)
args.output.parent.mkdir(parents=True,exist_ok=True)
for suffix in ['.kicad_pro','.kicad_dru']:
    if args.board.with_suffix(suffix).exists():
        shutil.copy2(args.board.with_suffix(suffix),args.output.with_suffix(suffix))
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(args.output),b)
args.output.with_suffix('.supply-fanouts.json').write_text(json.dumps({'added_locked_uuids':added},indent=2)+'\n')
print(f'Added {len(added)} supply escape items')
