"""Add reviewed ESP32 left/bottom escapes to an explicit private output.

Run with KiCad Python: mcu_left_fanout.py INPUT.kicad_pcb
  --original-reference ORIGINAL.kicad_pcb --output OUTPUT.kicad_pcb
Original-reference copper is always preserved. Only generated copper near
these escapes or on their target nets is removed, with an explicit UUID audit.
The capacitor moves and new routes still require full project DRC after use.
"""
import argparse
import json
from pathlib import Path
import shutil
import uuid
import pcbnew as p

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("board", type=Path)
parser.add_argument("--original-reference", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve(), "Use an explicit different output"
original = p.LoadBoard(str(args.original_reference))
protected = {t.m_Uuid.AsString() for t in original.GetTracks()}
assert not any(identity.startswith("c0a7c0de-") for identity in protected), "Original-reference must predate this repair"
board = p.LoadBoard(str(args.board))
fps = {f.GetReference(): f for f in board.GetFootprints()}
assert abs(p.ToMM(fps["U1"].GetPosition().x)-22.2) < .001
assert abs(p.ToMM(fps["U1"].GetPosition().y)-10) < .001
nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
targets = {"BOOT", "CC1_SENSE", "CC2_SENSE", "VBUS_SENSE", "USB_STRIP_EN",
           "USB_HIGH_CURRENT", "GPIO16", "GPIO17", "GPIO18_BUTTON"}
removed = []
for item in list(board.GetTracks()):
    identity = item.m_Uuid.AsString()
    # The independent top/UART repair is authored copper too. Its short
    # test-pad connections may reach this escape window after integration.
    if identity in protected or identity.startswith("a4710001-"):
        continue
    box = item.GetBoundingBox()
    intersects_escape = (p.ToMM(box.GetRight()) >= 17.4 and p.ToMM(box.GetLeft()) <= 24
                         and p.ToMM(box.GetBottom()) >= 8.6 and p.ToMM(box.GetTop()) <= 15.3)
    if item.GetNetname() in targets or intersects_escape or identity.startswith("c0a7c0de-"):
        removed.append({"uuid":identity, "net":item.GetNetname(), "via":isinstance(item,p.PCB_VIA)})
        board.Delete(item)

# C4 remains a VBUS ADC filter; moving it under the IC frees the outside pad
# escape corridor. The two inward vias are outside U1's exposed-ground pad.
positions = {"C4":[21.4,10.3,0], "C111":[17.1,11.98,90]}
for reference,(x,y,angle) in positions.items():
    fps[reference].SetPosition(p.VECTOR2I(p.FromMM(x),p.FromMM(y)))
    fps[reference].SetOrientationDegrees(angle)

routes = [
    ("BOOT",p.F_Cu,.15,[(18.75,9),(18.35,9),(17.95,9.4)]),
    ("CC1_SENSE",p.F_Cu,.15,[(18.75,9.4),(19.55,9.4),(19.65,9.3)]),
    ("CC2_SENSE",p.F_Cu,.15,[(18.75,9.8),(18.35,9.8),(17.95,10.2)]),
    ("VBUS_SENSE",p.F_Cu,.15,[(18.75,10.6),(19.55,10.6),(19.65,10.7)]),
    ("VBUS_SENSE",p.B_Cu,.15,[(19.65,10.7),(20.625,10.7),(20.625,10.3)]),
    ("USB_STRIP_EN",p.F_Cu,.15,[(18.75,11),(17.95,11)]),
    ("USB_HIGH_CURRENT",p.F_Cu,.15,[(18.75,11.4),(18.35,11.4),(17.95,11.8)]),
    ("GPIO16",p.F_Cu,.15,[(22.4,13.45),(22.4,14.3),(22.3,14.4)]),
    ("GPIO17",p.F_Cu,.15,[(22.8,13.45),(22.8,15)]),
    ("GPIO18_BUTTON",p.F_Cu,.15,[(23.2,13.45),(23.2,14.6),(23.3,14.7)]),
]
vias = [("BOOT",17.95,9.4),("CC1_SENSE",19.65,9.3),("CC2_SENSE",17.95,10.2),
        ("VBUS_SENSE",19.65,10.7),("USB_STRIP_EN",17.95,11),
        ("USB_HIGH_CURRENT",17.95,11.8),("GPIO16",22.3,14.4),
        ("GPIO17",22.8,15),("GPIO18_BUTTON",23.3,14.7)]
namespace = uuid.UUID("4e1bf624-245e-4c4f-8dbc-aaf323a7a4d0")
added = []
for netname,layer,width,points in routes:
    for a,z in zip(points,points[1:]):
        item = p.PCB_TRACK(board)
        item.SetStart(p.VECTOR2I(p.FromMM(a[0]),p.FromMM(a[1])))
        item.SetEnd(p.VECTOR2I(p.FromMM(z[0]),p.FromMM(z[1])))
        item.SetWidth(p.FromMM(width))
        item.SetLayer(layer)
        item.SetNet(nets[netname])
        item.SetLocked(True)
        identity = "c0a7c0de-" + str(uuid.uuid5(namespace,f"{netname}:{layer}:{a}:{z}"))[9:]
        item.SetUuid(p.KIID(identity))
        board.Add(item)
        added.append(identity)
for netname,x,y in vias:
    item = p.PCB_VIA(board)
    item.SetPosition(p.VECTOR2I(p.FromMM(x),p.FromMM(y)))
    item.SetWidth(p.FromMM(.45))
    item.SetDrill(p.FromMM(.2))
    item.SetViaType(p.VIATYPE_THROUGH)
    item.SetLayerPair(p.F_Cu,p.B_Cu)
    item.SetNet(nets[netname])
    item.SetLocked(True)
    identity = "c0a7c0de-" + str(uuid.uuid5(namespace,f"{netname}:via:{x}:{y}"))[9:]
    item.SetUuid(p.KIID(identity))
    board.Add(item)
    added.append(identity)
remaining = {t.m_Uuid.AsString() for t in board.GetTracks()}
assert protected <= remaining, "Original authored copper must survive"
args.output.parent.mkdir(parents=True,exist_ok=True)
for suffix in [".kicad_pro",".kicad_dru"]:
    source = args.board.with_suffix(suffix)
    target = args.output.with_suffix(suffix)
    if source.exists() and source.resolve() != target.resolve():
        shutil.copyfile(source,target)
board.BuildConnectivity()
p.ZONE_FILLER(board).Fill(board.Zones())
p.SaveBoard(str(args.output),board)
audit = {"input":str(args.board),"output":str(args.output),"original_reference":str(args.original_reference),
         "protected_items_preserved":len(protected),"positions":positions,"added_locked_uuids":added,
         "removed_generated_items":removed}
args.output.with_suffix(".fanout-audit.json").write_text(json.dumps(audit,indent=2)+"\n")
print(json.dumps({"protected":len(protected),"added":len(added),"removed_generated":len(removed),"positions":positions}))
