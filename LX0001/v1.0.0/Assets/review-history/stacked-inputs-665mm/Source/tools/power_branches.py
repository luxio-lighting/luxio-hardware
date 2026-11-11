"""Route low-current power branches around the locked load-current spines.

Run with KiCad Python. Explicit input/output paths are required; use a copy
for review. Tracks created by this script are identified by a reserved UUID
prefix and replaced on subsequent runs. Other tracks are preserved.
"""
import argparse
import heapq
import math
from pathlib import Path
import uuid
import pcbnew as pcb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("board", type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--only-branch", action="append", help="Replace only named auxiliary branches")
args = parser.parse_args()
board = pcb.LoadBoard(str(args.board))
fps = {f.GetReference(): f for f in board.GetFootprints()}
nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
namespace = uuid.UUID("311c3645-c6f2-4080-aaf5-cf1ebaa3a01d")
# ref/pad endpoints use current pad coordinates. Via endpoints lie on the
# locked VSYS bottom spine. These branches do not replace the5 A conductors.
branches = [
    ("dc_cap", "DC_FUSED", ("C5", "2"), ("F1", "2"), 0.2),
    ("dc_enable", "DC_FUSED", ("U3", "3"), ("F1", "2"), 0.2),
    ("dc_anode", "DC_FUSED", ("U3", "6"), ("U3", "3"), 0.2),
    ("dc_presence", "DC_FUSED", ("D1", "2"), ("F1", "2"), 0.2),
    ("vsys_usb_drain", "VSYS", ("Q3", "5"), (1, 24.5, 19.15), 0.6),
    ("vsys_wired_sense", "VSYS", ("U3", "4"), (1, 23.8, 19.15), 0.2),
    ("vsys_usb_sense", "VSYS", ("U5", "4"), (1, 23.8, 19.15), 0.2),
    ("vsys_buck", "VSYS", ("C8", "1"), (1, 32.5, 19.25), 0.4),
    ("vsys_zener", "VSYS", ("D5", "1"), ("Q6", "1"), 0.2),
    ("vsys_pullup", "VSYS", ("R34", "1"), ("D5", "1"), 0.2),
    ("vsys_test", "VSYS", ("TP9", "1"), (1, 33.9, 19.15), 0.2),
    ("led_bleed", "LED_VCC", ("R40", "1"), ("Q6", "5"), 0.2),
]
if args.only_branch:
    assert set(args.only_branch) <= {row[0] for row in branches}, "Unknown branch name"
    selected_ids = {"b0a7c001-" + str(uuid.uuid5(namespace, f"{name}:{index}"))[9:] for name in args.only_branch for index in range(2048)}
else:
    selected_ids = None
for track in list(board.GetTracks()):
    if (track.m_Uuid.AsString() in selected_ids if selected_ids is not None else track.m_Uuid.AsString().startswith("b0a7c001-")):
        board.Delete(track)
if not args.only_branch or "vsys_test" in args.only_branch:
    fps["TP9"].SetPosition(pcb.VECTOR2I(pcb.FromMM(33.4), pcb.FromMM(18.35)))
for branch, netname, start_spec, end_spec, width in branches:
    if args.only_branch and branch not in args.only_branch:
        continue
    endpoints = []
    for spec in [start_spec, end_spec]:
        if len(spec) == 2:
            pad = next(p for p in fps[spec[0]].Pads() if p.GetNumber() == spec[1])
            assert pad.GetNetname() == netname, f"Unexpected net at {spec}"
            endpoints.append((0 if pad.IsOnLayer(pcb.F_Cu) else 1, pcb.ToMM(pad.GetPosition().x), pcb.ToMM(pad.GetPosition().y)))
        else:
            endpoints.append(spec)
    start, goal = [(layer, round(x * 20), round(y * 20)) for layer, x, y in endpoints]
    bins, padbins, keep = [{}, {}], {}, []
    ruleareas = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowTracks()]
    ruleareas += [z for f in board.GetFootprints() for z in f.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowTracks()]
    allvias = [(v.GetPosition(), v.GetNetname(), pcb.ToMM(v.GetDrillValue())) for v in board.GetTracks() if isinstance(v, pcb.PCB_VIA)]
    ownpads = []
    for layer_index, layer in enumerate([pcb.F_Cu, pcb.B_Cu]):
        shapes = [pad.GetEffectiveShape(layer) for f in board.GetFootprints() for pad in f.Pads() if pad.IsOnLayer(layer) and pad.GetNetname() != netname]
        shapes += [t.GetEffectiveShape(layer) for t in board.GetTracks() if t.IsOnLayer(layer) and t.GetNetname() != netname]
        shapes += [z.Outline() for z in ruleareas if z.IsOnLayer(layer)]
        shapes += [pcb.SHAPE_CIRCLE(pad.GetPosition(), int(pad.GetDrillSize().x / 2) + pcb.FromMM(0.13)).Clone() for f in board.GetFootprints() for pad in f.Pads() if pad.GetAttribute() == pcb.PAD_ATTRIB_NPTH]
        for shape in shapes:
            keep.append(shape)
            bounds = shape.BBox()
            for bx in range(math.floor(pcb.ToMM(bounds.GetLeft()) / 2) - 1, math.floor(pcb.ToMM(bounds.GetRight()) / 2) + 2):
                for by in range(math.floor(pcb.ToMM(bounds.GetTop()) / 2) - 1, math.floor(pcb.ToMM(bounds.GetBottom()) / 2) + 2):
                    bins[layer_index].setdefault((bx, by), []).append(shape)
        for f in board.GetFootprints():
            for pad in f.Pads():
                if not pad.IsOnLayer(layer):
                    continue
                shape = pad.GetEffectiveShape(layer)
                keep.append(shape)
                if pad.GetNetname() == netname:
                    ownpads.append(shape)
                bounds = shape.BBox()
                for bx in range(math.floor(pcb.ToMM(bounds.GetLeft()) / 2) - 1, math.floor(pcb.ToMM(bounds.GetRight()) / 2) + 2):
                    for by in range(math.floor(pcb.ToMM(bounds.GetTop()) / 2) - 1, math.floor(pcb.ToMM(bounds.GetBottom()) / 2) + 2):
                        padbins.setdefault((bx, by), []).append(shape)
    queue, cost, parent = [(0, 0, start)], {start: 0}, {}
    free, via_free = {}, {}
    reached = False
    while queue:
        _, distance, current = heapq.heappop(queue)
        if distance != cost[current]:
            continue
        if current == goal:
            reached = True
            break
        if len(cost) > 600000:
            break
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1), (0, 0)]:
            next_point = (1 - current[0], current[1], current[2]) if dx == dy == 0 else (current[0], current[1] + dx, current[2] + dy)
            if not (10 <= next_point[1] <= 1190 and 10 <= next_point[2] <= 390):
                continue
            next_distance = distance + (100 if dx == dy == 0 else math.hypot(dx, dy))
            if next_distance >= cost.get(next_point, 1e12):
                continue
            point = pcb.VECTOR2I(pcb.FromMM(next_point[1] / 20), pcb.FromMM(next_point[2] / 20))
            bin_key = (next_point[1] // 40, next_point[2] // 40)
            if dx == dy == 0:
                xy = next_point[1:]
                if xy not in via_free:
                    via_free[xy] = not any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(0.36)) for sh in bins[0].get(bin_key, []) + bins[1].get(bin_key, [])) and not any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(0.24)) for sh in padbins.get(bin_key, []))
                if not via_free[xy]:
                    continue
                if any((point.x - q.x) ** 2 + (point.y - q.y) ** 2 < pcb.FromMM(0.255 + drill / 2 + 0.10) ** 2 for q, name, drill in allvias):
                    continue
            else:
                if next_point not in free:
                    free[next_point] = not any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(width / 2 + 0.13)) for sh in bins[next_point[0]].get(bin_key, []))
                if not free[next_point]:
                    continue
                segment = pcb.SEG(pcb.VECTOR2I(pcb.FromMM(current[1] / 20), pcb.FromMM(current[2] / 20)), point)
                if any(sh.Collide(segment, pcb.FromMM(width / 2 + 0.13)) for sh in bins[next_point[0]].get(bin_key, [])):
                    continue
            cost[next_point] = next_distance
            parent[next_point] = current
            heapq.heappush(queue, (next_distance + math.hypot(next_point[1] - goal[1], next_point[2] - goal[2]), next_distance, next_point))
    if not reached:
        raise RuntimeError(f"No clearance-checked route found for {branch}; input PCB was not modified")
    route = [goal]
    while route[-1] != start:
        route.append(parent[route[-1]])
    route.reverse()
    corners = [route[0]]
    for index in range(1, len(route) - 1):
        if tuple(route[index][k] - route[index - 1][k] for k in range(3)) != tuple(route[index + 1][k] - route[index][k] for k in range(3)):
            corners.append(route[index])
    corners.append(route[-1])
    segments = []
    item_index = 0
    for a, c in zip(corners, corners[1:]):
        if a[0] != c[0]:
            via = pcb.PCB_VIA(board)
            via.SetPosition(pcb.VECTOR2I(pcb.FromMM(a[1] / 20), pcb.FromMM(a[2] / 20)))
            via.SetWidth(pcb.FromMM(0.45))
            via.SetDrill(pcb.FromMM(0.2))
            via.SetViaType(pcb.VIATYPE_THROUGH)
            via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
            via.SetNet(nets[netname])
            via.SetLocked(True)
            via.SetUuid(pcb.KIID("b0a7c001-" + str(uuid.uuid5(namespace, f"{branch}:{item_index}"))[9:]))
            item_index += 1
            board.Add(via)
        else:
            segments.append(([pcb.F_Cu, pcb.B_Cu][a[0]], (a[1] / 20, a[2] / 20), (c[1] / 20, c[2] / 20)))
    for endpoint, grid_point in zip(endpoints, [start, goal]):
        segments.append(([pcb.F_Cu, pcb.B_Cu][endpoint[0]], endpoint[1:], (grid_point[1] / 20, grid_point[2] / 20)))
    for layer, a, c in segments:
        if a == c:
            continue
        track = pcb.PCB_TRACK(board)
        track.SetStart(pcb.VECTOR2I(pcb.FromMM(a[0]), pcb.FromMM(a[1])))
        track.SetEnd(pcb.VECTOR2I(pcb.FromMM(c[0]), pcb.FromMM(c[1])))
        track.SetWidth(pcb.FromMM(width))
        track.SetLayer(layer)
        track.SetNet(nets[netname])
        track.SetLocked(True)
        track.SetUuid(pcb.KIID("b0a7c001-" + str(uuid.uuid5(namespace, f"{branch}:{item_index}"))[9:]))
        item_index += 1
        board.Add(track)
    print(f"{branch}: {item_index} items, {len(cost)} search states", flush=True)
board.BuildConnectivity()
pcb.ZONE_FILLER(board).Fill(board.Zones())
args.output.parent.mkdir(parents=True, exist_ok=True)
pcb.SaveBoard(str(args.output), board)
print(f"Saved {args.output}; validate DRC before applying to the design")
