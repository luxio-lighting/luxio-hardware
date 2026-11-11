"""Complete the locked 40 MHz crystal branches after generate.py/preroute.py.

Run with KiCad's bundled Python. Geometry targets 0.127 mm copper clearance,
0.15 mm tracks, and 0.45/0.20 mm through vias. Ground vias sit outside the
component pads; the subsequent ground-plane refill connects their returns.
The placement guard intentionally refuses to route a changed clock layout.
"""
from pathlib import Path
import pcbnew as p

root = Path(__file__).resolve().parents[1]
board_path = root / "LX0001.kicad_pcb"
io = p.PCB_IO_KICAD_SEXPR()
board = io.LoadBoard(str(board_path), None)
pads = {(f.GetReference(), pad.GetNumber()): pad
        for f in board.GetFootprints() for pad in f.Pads()}

expected = {
    ("C112", "1"): ("XTAL_P_CRYSTAL", 19.05, 3.96),
    ("C112", "2"): ("GND", 19.05, 3.00),
    ("C113", "1"): ("XTAL_N", 25.52, 2.07),
    ("C113", "2"): ("GND", 25.52, 1.11),
    ("Y1", "1"): ("XTAL_P_CRYSTAL", 20.70, 3.25),
    ("Y1", "2"): ("GND", 22.90, 3.25),
    ("Y1", "3"): ("XTAL_N", 22.90, 1.55),
    ("Y1", "4"): ("GND", 20.70, 1.55),
    ("L101", "2"): ("XTAL_P_CRYSTAL", 20.885, 5.00),
}
for key, (net, x, y) in expected.items():
    pad = pads[key]
    position = pad.GetPosition()
    if (pad.GetNetname() != net or pad.GetLayer() != p.F_Cu
            or abs(p.ToMM(position.x) - x) > 0.005
            or abs(p.ToMM(position.y) - y) > 0.005):
        raise RuntimeError(f"Clock placement/net changed at {key}; review fanout first")

# Join the existing preroute traces exactly, without duplicate overlapping
# segments. The N junction (23.42, 2.07) lies on the 45-degree Y1 escape.
routes = [
    ("XTAL_P_CRYSTAL", [(19.05, 3.96), (20.70, 3.96)]),
    ("XTAL_N", [(25.52, 2.07), (23.42, 2.07)]),
    ("GND", [(19.05, 3.00), (19.05, 2.40)]),
    ("GND", [(25.52, 1.11), (24.90, 1.11)]),
    ("GND", [(22.90, 3.25), (22.90, 3.80), (22.60, 4.10)]),
    ("GND", [(20.70, 1.55), (20.70, 0.65)]),
]
ground_vias = [(19.05, 2.40), (24.90, 1.11), (22.60, 4.10), (20.70, 0.65)]
nets = {net.GetNetname(): net
        for net in board.GetNetInfo().NetsByNetcode().values()}
existing_tracks = set()
existing_vias = set()
for item in board.GetTracks():
    if isinstance(item, p.PCB_VIA):
        position = item.GetPosition()
        existing_vias.add((item.GetNetname(), position.x, position.y))
    else:
        start, end = item.GetStart(), item.GetEnd()
        ends = tuple(sorted(((start.x, start.y), (end.x, end.y))))
        existing_tracks.add((item.GetNetname(), item.GetLayer(), ends))

tracks_added = vias_added = 0
for net, points in routes:
    for start, end in zip(points, points[1:]):
        a = p.VECTOR2I(p.FromMM(start[0]), p.FromMM(start[1]))
        z = p.VECTOR2I(p.FromMM(end[0]), p.FromMM(end[1]))
        key = (net, p.F_Cu, tuple(sorted(((a.x, a.y), (z.x, z.y)))))
        if key in existing_tracks:
            continue
        track = p.PCB_TRACK(board)
        track.SetStart(a)
        track.SetEnd(z)
        track.SetLayer(p.F_Cu)
        track.SetWidth(p.FromMM(0.15))
        track.SetNet(nets[net])
        track.SetLocked(True)
        board.Add(track)
        existing_tracks.add(key)
        tracks_added += 1
for x, y in ground_vias:
    position = p.VECTOR2I(p.FromMM(x), p.FromMM(y))
    key = ("GND", position.x, position.y)
    if key in existing_vias:
        continue
    via = p.PCB_VIA(board)
    via.SetPosition(position)
    via.SetWidth(p.FromMM(0.45))
    via.SetDrill(p.FromMM(0.20))
    via.SetViaType(p.VIATYPE_THROUGH)
    via.SetLayerPair(p.F_Cu, p.B_Cu)
    via.SetNet(nets["GND"])
    via.SetLocked(True)
    board.Add(via)
    existing_vias.add(key)
    vias_added += 1

board.BuildConnectivity()
p.ZONE_FILLER(board).Fill(board.Zones())
io.SaveBoard(str(board_path), board)
print(f"Added {tracks_added} locked crystal tracks and {vias_added} ground vias; filled zones")
