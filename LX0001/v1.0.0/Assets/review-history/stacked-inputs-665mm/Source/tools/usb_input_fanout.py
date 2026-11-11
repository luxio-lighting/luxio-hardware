"""Author the reversible USB-C data contacts and ESD array escape.

Use KiCad Python with INPUT --output DISTINCT_OUTPUT. This adds physical
copper, never replaces connector pin connections with an assumed internal
short. Run on the manual routing baseline before global routing.
"""
import argparse
import json
from pathlib import Path
import shutil
import uuid
import pcbnew as p

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('board', type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve()
board = p.LoadBoard(str(args.board))
nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
for reference, number, net, xy in [
    ('J1','B6','USB_DP_CONN',(6.175,9.25)),
    ('J1','A6','USB_DP_CONN',(6.175,10.25)),
    ('J1','A7','USB_DM_CONN',(6.175,9.75)),
    ('J1','B7','USB_DM_CONN',(6.175,10.75)),
    ('U2','3','USB_DP_CONN',(10.1525,11.9)),
    ('U2','1','USB_DM_CONN',(10.1525,13.8)),
]:
    pad = next(a for f in board.GetFootprints() if f.GetReference()==reference
               for a in f.Pads() if a.GetNumber()==number)
    assert pad.GetNetname()==net
    assert abs(p.ToMM(pad.GetPosition().x)-xy[0])<.001
    assert abs(p.ToMM(pad.GetPosition().y)-xy[1])<.001
for item in list(board.GetTracks()):
    if item.m_Uuid.AsString().startswith('ab001c01-'):
        board.Remove(item)
routes = [
    ('USB_DP_CONN', p.B_Cu, .15, [(6.175,9.25),(5.65,9.25),(5.4,9.5),(5.05,9.5)]),
    ('USB_DP_CONN', p.B_Cu, .15, [(6.175,10.25),(5.65,10.25),(5.4,10.5),(5.05,10.5)]),
    ('USB_DP_CONN', p.F_Cu, .15, [(5.05,9.5),(5.05,10.5)]),
    ('USB_DM_CONN', p.B_Cu, .2, [(6.175,9.75),(7.3,9.75),(7.3,10.65),(6.175,10.75)]),
    ('USB_DM_CONN', p.F_Cu, .2, [(7.3,10.6),(13.4,10.6)]),
    ('USB_DM_CONN', p.B_Cu, .2, [(13.4,10.6),(13.4,13.8),(10.1525,13.8)]),
    ('USB_DP_CONN', p.B_Cu, .15, [(6.175,9.25),(7.9,9.25),(7.9,9.7),(8.3,10.1),(8.3,11.1),(9.2,11.1),(9.2,11.9),(12.4275,11.9)]),
    ('USB_DM', p.F_Cu, .2, [(23.6,13.45),(23.6,14.3),(24.175,14.875),(25.2,14.875)]),
    ('USB_DP', p.F_Cu, .2, [(24,13.45),(24,14.1),(26.225,14.1),(27,14.875)]),
]
vias = [('USB_DP_CONN',5.05,9.5),('USB_DP_CONN',5.05,10.5),('USB_DM_CONN',7.3,10.6),('USB_DM_CONN',13.4,10.6)]
namespace = uuid.UUID('01858fa2-879d-40ce-9bf9-bf879c8e59be')
added = []
for net,layer,width,points in routes:
    for a,z in zip(points,points[1:]):
        item = p.PCB_TRACK(board)
        item.SetStart(p.VECTOR2I(p.FromMM(a[0]),p.FromMM(a[1])))
        item.SetEnd(p.VECTOR2I(p.FromMM(z[0]),p.FromMM(z[1])))
        item.SetWidth(p.FromMM(width))
        item.SetLayer(layer)
        item.SetNet(nets[net])
        item.SetLocked(True)
        identity = 'ab001c01-' + str(uuid.uuid5(namespace,f'{net}:{layer}:{a}:{z}'))[9:]
        item.SetUuid(p.KIID(identity))
        board.Add(item)
        added.append(identity)
for net,x,y in vias:
    item = p.PCB_VIA(board)
    item.SetPosition(p.VECTOR2I(p.FromMM(x),p.FromMM(y)))
    item.SetWidth(p.FromMM(.45))
    item.SetDrill(p.FromMM(.2))
    item.SetViaType(p.VIATYPE_THROUGH)
    item.SetLayerPair(p.F_Cu,p.B_Cu)
    item.SetNet(nets[net])
    item.SetLocked(True)
    identity = 'ab001c01-' + str(uuid.uuid5(namespace,f'{net}:via:{x}:{y}'))[9:]
    item.SetUuid(p.KIID(identity))
    board.Add(item)
    added.append(identity)
args.output.parent.mkdir(parents=True,exist_ok=True)
for suffix in ['.kicad_pro','.kicad_dru']:
    source = args.board.with_suffix(suffix)
    if source.exists():
        shutil.copy2(source,args.output.with_suffix(suffix))
board.BuildConnectivity()
p.ZONE_FILLER(board).Fill(board.Zones())
p.SaveBoard(str(args.output),board)
args.output.with_suffix('.usb-fanout.json').write_text(json.dumps({'added_locked_uuids':added},indent=2)+'\n')
print(f'Added {len(added)} USB data escape items')
