"""Lock the RFECA middle-edge antenna feed and ESP32 matching network.

Run after generator/preroute/clock_fanout. An optional board path allows
validation on a temporary copy. Does not fill zones or change other parts.
"""
from pathlib import Path
import sys
import pcbnew as p

root = Path(__file__).resolve().parents[1]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "LX0001.kicad_pcb"
io = p.PCB_IO_KICAD_SEXPR()
board = io.LoadBoard(str(path), None)
fps = {f.GetReference(): f for f in board.GetFootprints()}
for ref, (x, y, angle) in {
    "U1": (22.2, 10, 0), "ANT1": (14.5, 1.5, 0),
    "L104": (11.1, 1.5, 0), "C114": (17.7, 7.4, 270),
    "C115": (15.1, 7.4, 270), "L102": (16.4, 7.72, 180),
}.items():
    fp = fps[ref]
    position = fp.GetPosition()
    if (abs(p.ToMM(position.x) - x) > 0.005
            or abs(p.ToMM(position.y) - y) > 0.005
            or abs((fp.GetOrientationDegrees() - angle + 180) % 360 - 180) > 0.01):
        raise RuntimeError(f"RF placement changed at {ref}; review fanout first")
if "RFECA3216060A1T_Type1" not in str(fps["ANT1"].GetFPID().GetLibItemName()):
    raise RuntimeError("ANT1 must use the verified RFECA Type1 footprint")
nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
routes = [
    ("RF_CHIP", .20, [(18.75,7.4),(18.4,7.4),(18.08,7.08),(17.7,7.08),(17.2,7.08),(16.72,7.56),(16.72,7.72)]),
    ("RF_50", .20, [(16.08,7.72),(15.44,7.08),(15.1,7.08),(15.1,6.4)]),
    ("RF_50", .80, [(15.1,6.4),(17.2,4.3),(17.2,3.275)]),
    # Short antenna transition inside the clearance window. It requires RF
    # tuning; nominal CPWG dimensions apply only over continuous ground.
    ("RF_50", .50, [(17.2,3.275),(18.5,1.975)]),
    ("GND", .20, [(17.7,7.72),(17.31,7.72)]),
    ("GND", .20, [(15.1,7.72),(14.6,7.72)]),
    ("GND", .30, [(18.5,1.025),(19.0,1.025)]),
    ("GND", .20, [(10.65,1.5),(10.0,1.5),(10.0,.65)]),
]
via_points = [(17.31,7.72),(14.6,7.72),(19.0,1.025),(10.0,.65)]
existing_tracks = set()
existing_vias = set()
for item in board.GetTracks():
    if isinstance(item, p.PCB_VIA):
        pos = item.GetPosition()
        existing_vias.add((item.GetNetname(),pos.x,pos.y))
    else:
        a,z = item.GetStart(),item.GetEnd()
        existing_tracks.add((item.GetNetname(),item.GetLayer(),tuple(sorted(((a.x,a.y),(z.x,z.y))))))
added_tracks = added_vias = 0
for net,width,points in routes:
    for start,end in zip(points,points[1:]):
        a=p.VECTOR2I(p.FromMM(start[0]),p.FromMM(start[1]))
        z=p.VECTOR2I(p.FromMM(end[0]),p.FromMM(end[1]))
        key=(net,p.F_Cu,tuple(sorted(((a.x,a.y),(z.x,z.y)))))
        if key in existing_tracks:
            continue
        track=p.PCB_TRACK(board)
        track.SetStart(a);track.SetEnd(z);track.SetLayer(p.F_Cu)
        track.SetWidth(p.FromMM(width));track.SetNet(nets[net]);track.SetLocked(True)
        board.Add(track);existing_tracks.add(key);added_tracks+=1
for x,y in via_points:
    pos=p.VECTOR2I(p.FromMM(x),p.FromMM(y))
    key=("GND",pos.x,pos.y)
    if key in existing_vias:
        continue
    via=p.PCB_VIA(board);via.SetPosition(pos)
    via.SetWidth(p.FromMM(.45));via.SetDrill(p.FromMM(.20))
    via.SetViaType(p.VIATYPE_THROUGH);via.SetLayerPair(p.F_Cu,p.B_Cu)
    via.SetNet(nets["GND"]);via.SetLocked(True)
    board.Add(via);existing_vias.add(key);added_vias+=1
board.BuildConnectivity()
io.SaveBoard(str(path),board)
print(f"Added {added_tracks} locked RF segments and {added_vias} GND vias; refill and DRC required")
