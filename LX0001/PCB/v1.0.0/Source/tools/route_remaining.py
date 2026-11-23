"""Complete DRC-reported pad/track/via connections while preserving existing copper.

Run with KiCad Python: route_remaining.py INPUT.kicad_pcb INPUT-drc.json
  --output OUTPUT.kicad_pcb [--batch-size8] [--rounds20]

GND and RF/clock/switch-node nets are deferred by default. Zone-only records
are reported explicitly: DRC zone coordinates identify the zone origin, not
the disconnected island. Resolve heavy nets with power_branches.py first.
Each accepted batch is refilled and checked with kicad-cli DRC. A batch that
introduces an electrical violation is retained separately and rolled back.
Existing copper is preserved by default. --ripup-unlocked may remove only
unlocked noncritical tracks/vias obstructing a new route; exact UUIDs are logged.
All existing locked tracks, pads and footprints remain unchanged.
"""
import argparse
import heapq
import json
import math
from pathlib import Path
import shutil
import subprocess
import pcbnew as pcb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("board", type=Path)
parser.add_argument("drc", type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--batch-size", type=int, default=8)
parser.add_argument("--rounds", type=int, default=20)
parser.add_argument("--max-states", type=int, default=300000)
parser.add_argument("--signal-width", type=float, default=0.15)
parser.add_argument("--logic-power-width", type=float, default=0.2, help="Width for reviewed logic-supply branches; does not alter wired or USB power nets")
parser.add_argument("--usb-power-width", type=float, default=0.6, help="Width for USB_5V and USB_LIMITED; default 0.6 mm, smaller reviewed widths require a copper-loss assessment")
parser.add_argument("--via-diameter", type=float, default=0.45)
parser.add_argument("--via-drill", type=float, default=0.2)
parser.add_argument("--skip-net", action="append", default=["GND"])
parser.add_argument("--only-net", action="append")
parser.add_argument("--include-critical", action="store_true")
parser.add_argument("--ripup-unlocked", action="store_true")
parser.add_argument("--use-island-vias", action="store_true", help="Start from an existing connected escape via when available")
parser.add_argument("--use-island-anchors", action="store_true", help="Search from sampled tracks, vias and pads throughout each connected island")
parser.add_argument("--save-reachable", action="store_true", help="Save failed-search reachable grid points for local routing diagnosis")
parser.add_argument("--stagnation-rounds", type=int, default=20, help="Stop ripup search after this many batches without a better non-GND checkpoint")
parser.add_argument("--kicad-cli", default=shutil.which("kicad-cli") or "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
args = parser.parse_args()
assert args.batch_size > 0 and args.rounds > 0 and args.max_states > 0
assert args.signal_width >= 0.127 and args.via_drill >= 0.2 and args.via_diameter - args.via_drill >= 0.2
assert args.logic_power_width >= 0.127 and args.usb_power_width >= 0.127
board = pcb.LoadBoard(str(args.board))
board.BuildConnectivity()
routing_layers = [pcb.F_Cu, pcb.In2_Cu, pcb.B_Cu] if board.GetCopperLayerCount() == 4 else [pcb.F_Cu, pcb.B_Cu]
nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
report = json.loads(args.drc.read_text())
critical = {"RF_CHIP", "RF_50", "ANT_FEED", "ANT_TUNE", "XTAL_P", "XTAL_P_CRYSTAL", "XTAL_N", "BUCK_BST", "BUCK_SW", "BOOST_SW"}
power = {"+3V3", "VDD_SPI", "VDD3P3_RF", "USB_5V", "USB_LIMITED", "+5V_DATA", "DC_FUSED", "VSYS", "LED_VCC"}
usb = {"USB_DM", "USB_DP", "USB_DM_CONN", "USB_DP_CONN"}
electrical_types = {"clearance", "shorting_items", "hole_to_hole", "hole_clearance", "edge_clearance", "track_width", "via_annulus", "via_diameter", "drill_out_of_range", "copper_edge_clearance", "track_crossing", "tracks_crossing", "items_not_allowed"}
baseline = {(v["type"], tuple(sorted(x["uuid"] for x in v.get("items", [])))) for v in report.get("violations", []) if v["type"] in electrical_types}
args.output.parent.mkdir(parents=True, exist_ok=True)
source_project = args.board.with_suffix(".kicad_pro")
output_project = args.output.with_suffix(".kicad_pro")
if source_project.exists() and source_project.resolve() != output_project.resolve():
    shutil.copy2(source_project, output_project)
source_rules = args.board.with_suffix(".kicad_dru")
output_rules = args.output.with_suffix(".kicad_dru")
if source_rules.exists() and source_rules.resolve() != output_rules.resolve():
    shutil.copy2(source_rules, output_rules)
pcb.SaveBoard(str(args.output), board)
log = {"input_board": str(args.board.resolve()), "input_drc": str(args.drc.resolve()), "output_board": str(args.output.resolve()), "routed": [], "failed": [], "deferred": [], "batches": [], "baseline_electrical_violations": len(baseline), "ripup_unlocked": args.ripup_unlocked, "removed_items": []}
failed_pairs = set()
deferred_pairs = set()
failed_validation = False
best_checkpoint = args.output.read_bytes()
best_report = report
best_score = (sum(not any("[GND]" in i.get("description", "") for i in r.get("items", [])) for r in report.get("unconnected_items", [])), len(report.get("unconnected_items", [])))
best_round = 0
stagnant_rounds = 0
ripped_net_counts = {}
priority_nets = set()
for round_index in range(args.rounds):
    checkpoint = args.output.read_bytes()
    before_count = len(report.get("unconnected_items", []))
    objects = {x.m_Uuid.AsString(): x for x in list(board.GetTracks()) + [pad for f in board.GetFootprints() for pad in f.Pads()] + list(board.Zones())}
    completed = 0
    # The DRC list is refreshed after each accepted batch. Within a batch,
    # connectivity checks suppress pairs already joined by an earlier route.
    records = report.get("unconnected_items", [])
    if args.only_net:
        records = sorted(records, key=lambda r: next((index for index, name in enumerate(args.only_net) if any("[" + name + "]" in i.get("description", "") for i in r.get("items", []))), len(args.only_net)))
    if priority_nets:
        records = sorted(records, key=lambda r: not any(any("[" + n + "]" in i.get("description", "") for n in priority_nets) for i in r.get("items", [])))
    for record in records:
        items = record.get("items", [])
        if len(items) != 2 or any(item["uuid"] not in objects for item in items):
            continue
        a_object, b_object = [objects[item["uuid"]] for item in items]
        netname = a_object.GetNetname()
        if not netname or b_object.GetNetname() != netname:
            continue
        pair_key = (netname,) + tuple(sorted(item["uuid"] for item in items))
        if pair_key in failed_pairs:
            continue
        reason = None
        if netname in args.skip_net or (args.only_net and netname not in args.only_net):
            reason = "Net excluded by options"
        elif netname in critical and not args.include_critical:
            reason = "Critical RF/clock/switch-node net requires manual review"
        elif any(isinstance(obj, pcb.ZONE) for obj in [a_object, b_object]):
            reason = "Zone DRC origin does not identify the disconnected copper island"
        elif any(isinstance(obj, pcb.PCB_ARC) for obj in [a_object, b_object]):
            reason = "Arc endpoint requires manual review"
        if reason:
            if pair_key not in deferred_pairs:
                deferred_pairs.add(pair_key)
                log["deferred"].append({"net": netname, "items": list(pair_key[1:]), "reason": reason})
            continue
        connected = {obj.m_Uuid.AsString() for obj in board.GetConnectivity().GetConnectedItems(a_object)}
        if b_object.m_Uuid.AsString() in connected:
            continue
        endpoint_objects = [a_object, b_object]
        if args.use_island_vias:
            typed_vias = {v.m_Uuid.AsString(): v for v in board.GetTracks() if isinstance(v, pcb.PCB_VIA)}
            for index, obj in enumerate(endpoint_objects[:]):
                # Connectivity returns generic SWIG proxies, so recover the
                # actual via objects by UUID instead of testing proxy type.
                connected_vias = [typed_vias[v.m_Uuid.AsString()] for v in board.GetConnectivity().GetConnectedItems(obj) if v.m_Uuid.AsString() in typed_vias and v.GetNetname() == netname]
                if connected_vias:
                    target_pos = items[1 - index]["pos"]
                    endpoint_objects[index] = min(connected_vias, key=lambda v: (pcb.ToMM(v.GetPosition().x) - target_pos["x"]) ** 2 + (pcb.ToMM(v.GetPosition().y) - target_pos["y"]) ** 2)
        coordinates = []
        layer_sets = []
        for obj, item in zip(endpoint_objects, items):
            if isinstance(obj, pcb.PAD) or isinstance(obj, pcb.PCB_VIA):
                coordinates.append([pcb.ToMM(obj.GetPosition().x), pcb.ToMM(obj.GetPosition().y)])
            else:
                coordinates.append([item["pos"]["x"], item["pos"]["y"]])
            layer_sets.append([i for i, layer in enumerate(routing_layers) if obj.IsOnLayer(layer)])
        # Project onto the actual segment instead of routing unnecessarily
        # to the track's start point printed in the DRC record.
        for _ in range(2):
            for i, obj in enumerate(endpoint_objects):
                if isinstance(obj, pcb.PCB_TRACK) and not isinstance(obj, pcb.PCB_VIA):
                    x0, y0 = pcb.ToMM(obj.GetStart().x), pcb.ToMM(obj.GetStart().y)
                    x1, y1 = pcb.ToMM(obj.GetEnd().x), pcb.ToMM(obj.GetEnd().y)
                    tx, ty = coordinates[1 - i]
                    length2 = (x1 - x0) ** 2 + (y1 - y0) ** 2
                    fraction = max(0, min(1, ((tx - x0) * (x1 - x0) + (ty - y0) * (y1 - y0)) / length2)) if length2 else 0
                    coordinates[i] = [x0 + fraction * (x1 - x0), y0 + fraction * (y1 - y0)]
        shared = set(layer_sets[0]) & set(layer_sets[1])
        layers = [min(shared), min(shared)] if shared else [layer_sets[0][0], layer_sets[1][0]]
        endpoints = [(layer, *point) for layer, point in zip(layers, coordinates)]
        start, goal = [(layer, round(x * 20), round(y * 20)) for layer, x, y in endpoints]
        anchors = [{start: endpoints[0]}, {goal: endpoints[1]}]
        if args.use_island_anchors:
            for side, obj in enumerate([a_object, b_object]):
                island = [obj] + [objects[item.m_Uuid.AsString()] for item in board.GetConnectivity().GetConnectedItems(obj) if item.m_Uuid.AsString() in objects]
                for item in island:
                    if isinstance(item, pcb.ZONE) or isinstance(item, pcb.PCB_ARC):
                        continue
                    if isinstance(item, pcb.PCB_TRACK) and not isinstance(item, pcb.PCB_VIA):
                        x0, y0 = pcb.ToMM(item.GetStart().x), pcb.ToMM(item.GetStart().y)
                        x1, y1 = pcb.ToMM(item.GetEnd().x), pcb.ToMM(item.GetEnd().y)
                        steps = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / 0.25))
                        points = [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps) for i in range(steps + 1)]
                    else:
                        points = [(pcb.ToMM(item.GetPosition().x), pcb.ToMM(item.GetPosition().y))]
                    for layer_index, layer in enumerate(routing_layers):
                        if item.IsOnLayer(layer):
                            for x, y in points:
                                anchors[side][(layer_index, round(x * 20), round(y * 20))] = (layer_index, x, y)
        width = 2.0 if netname == "DC_IN" else args.usb_power_width if netname in {"USB_5V", "USB_LIMITED"} else args.logic_power_width if netname in {"+3V3", "VDD_SPI", "VDD3P3_RF", "+5V_DATA"} else 0.2 if netname in power or netname in usb else args.signal_width
        bounds = board.GetBoardEdgesBoundingBox()
        margin = 0.3 + max(width / 2, args.via_diameter / 2)
        xmin, xmax = pcb.ToMM(bounds.GetLeft()) + margin, pcb.ToMM(bounds.GetRight()) - margin
        ymin, ymax = pcb.ToMM(bounds.GetTop()) + margin, pcb.ToMM(bounds.GetBottom()) - margin
        routing_bin_mm = 0.5
        routing_bin_cells = round(routing_bin_mm * 20)
        routing_bin_padding = math.ceil(max(width / 2 + 0.135, args.via_diameter / 2 + 0.135) / routing_bin_mm)
        bins, padbins, keep = [{} for _ in routing_layers], {}, []
        # The antenna courtyard permits its existing RF feed, but all generic
        # new front-layer routing and vias must stay outside this window.
        antenna_guard = pcb.SHAPE_POLY_SET()
        antenna_guard.NewOutline()
        for gx, gy in [(10.5, 0), (18.5, 0), (18.5, 3), (10.5, 3)]:
            antenna_guard.Append(pcb.FromMM(gx), pcb.FromMM(gy))
        soft_bins = [{} for _ in routing_layers]
        soft_via_positions = {(v.GetPosition().x, v.GetPosition().y) for v in board.GetTracks() if isinstance(v, pcb.PCB_VIA) and args.ripup_unlocked and not v.IsLocked() and v.GetNetname() not in critical and v.GetNetname() != netname}
        ruleareas = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowTracks()]
        ruleareas += [z for f in board.GetFootprints() for z in f.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowTracks()]
        allvias = [(v.GetPosition(), v.GetNetname(), pcb.ToMM(v.GetDrillValue())) for v in board.GetTracks() if isinstance(v, pcb.PCB_VIA)]
        own_via_grid = set()
        for via_pos, via_net, via_drill in allvias:
            if via_net != netname:
                continue
            vx, vy = round(pcb.ToMM(via_pos.x) * 20), round(pcb.ToMM(via_pos.y) * 20)
            for gx in range(vx - 2, vx + 3):
                for gy in range(vy - 2, vy + 3):
                    if (pcb.FromMM(gx / 20) - via_pos.x) ** 2 + (pcb.FromMM(gy / 20) - via_pos.y) ** 2 < pcb.FromMM(0.06) ** 2:
                        own_via_grid.add((gx, gy))
        ownpads = []
        for layer_index, layer in enumerate(routing_layers):
            shapes = [pad.GetEffectiveShape(layer) for f in board.GetFootprints() for pad in f.Pads() if pad.IsOnLayer(layer) and pad.GetNetname() != netname]
            shapes += [t.GetEffectiveShape(layer) for t in board.GetTracks() if t.IsOnLayer(layer) and t.GetNetname() != netname and not (args.ripup_unlocked and not t.IsLocked() and t.GetNetname() not in critical)]
            if args.ripup_unlocked:
                for t in board.GetTracks():
                    if t.IsOnLayer(layer) and t.GetNetname() != netname and not t.IsLocked() and t.GetNetname() not in critical:
                        shape = t.GetEffectiveShape(layer)
                        keep.append(shape)
                        bounds = shape.BBox()
                        for bx in range(math.floor(pcb.ToMM(bounds.GetLeft()) / routing_bin_mm) - routing_bin_padding, math.floor(pcb.ToMM(bounds.GetRight()) / routing_bin_mm) + routing_bin_padding + 1):
                            for by in range(math.floor(pcb.ToMM(bounds.GetTop()) / routing_bin_mm) - routing_bin_padding, math.floor(pcb.ToMM(bounds.GetBottom()) / routing_bin_mm) + routing_bin_padding + 1):
                                soft_bins[layer_index].setdefault((bx, by), []).append((shape, t))
            shapes += [z.Outline() for z in ruleareas if z.IsOnLayer(layer)]
            if layer in [pcb.F_Cu, pcb.In2_Cu]:
                shapes.append(antenna_guard)
            shapes += [pcb.SHAPE_CIRCLE(pad.GetPosition(), int(pad.GetDrillSize().x / 2) + pcb.FromMM(0.13)).Clone() for f in board.GetFootprints() for pad in f.Pads() if pad.GetAttribute() == pcb.PAD_ATTRIB_NPTH]
            for shape in shapes:
                keep.append(shape)
                bounds = shape.BBox()
                for bx in range(math.floor(pcb.ToMM(bounds.GetLeft()) / routing_bin_mm) - routing_bin_padding, math.floor(pcb.ToMM(bounds.GetRight()) / routing_bin_mm) + routing_bin_padding + 1):
                    for by in range(math.floor(pcb.ToMM(bounds.GetTop()) / routing_bin_mm) - routing_bin_padding, math.floor(pcb.ToMM(bounds.GetBottom()) / routing_bin_mm) + routing_bin_padding + 1):
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
                    for bx in range(math.floor(pcb.ToMM(bounds.GetLeft()) / routing_bin_mm) - routing_bin_padding, math.floor(pcb.ToMM(bounds.GetRight()) / routing_bin_mm) + routing_bin_padding + 1):
                        for by in range(math.floor(pcb.ToMM(bounds.GetTop()) / routing_bin_mm) - routing_bin_padding, math.floor(pcb.ToMM(bounds.GetBottom()) / routing_bin_mm) + routing_bin_padding + 1):
                            padbins.setdefault((bx, by), []).append(shape)
        forbidden_vias = set()
        for via_attempt in range(8):
            queues = [[(0, 0, seed) for seed in seeds] for seeds in anchors]
            for queue in queues:
                heapq.heapify(queue)
            costs, parents = [{seed: 0 for seed in seeds} for seeds in anchors], [{}, {}]
            anchor_bounds = [(min(s[1] for s in seeds), max(s[1] for s in seeds), min(s[2] for s in seeds), max(s[2] for s in seeds)) for seeds in anchors]
            free, via_free, via_spacing_free = {}, {}, {}
            reached = False
            turn = 0
            meeting = None
            while queues[0] and queues[1]:
                side = turn % 2
                turn += 1
                queue, cost, parent = queues[side], costs[side], parents[side]
                target = goal if side == 0 else start
                _, distance, current = heapq.heappop(queue)
                if distance != cost[current]:
                    continue
                if current in costs[1 - side]:
                    reached = True
                    meeting = current
                    break
                if sum(len(c) for c in costs) > args.max_states:
                    break
                for next_layer, dx, dy in [(current[0], dx, dy) for dx, dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]] + [(li,0,0) for li in range(len(routing_layers)) if li != current[0]]:
                    next_point = (next_layer, current[1] + dx, current[2] + dy)
                    if not (xmin <= next_point[1] / 20 <= xmax and ymin <= next_point[2] / 20 <= ymax):
                        continue
                    next_distance = distance + (100 if dx == dy == 0 else math.hypot(dx, dy))
                    reuse = dx == dy == 0 and next_point[1:] in own_via_grid
                    if reuse:
                        next_distance = distance + 1
                    # Geometry checks cannot improve a path whose base cost
                    # already exceeds its recorded cost. Rip-up penalties are
                    # nonnegative, so this pruning is also valid in that mode.
                    if next_distance >= cost.get(next_point, 1e12):
                        continue
                    point = pcb.VECTOR2I(pcb.FromMM(next_point[1] / 20), pcb.FromMM(next_point[2] / 20))
                    bin_key = (next_point[1] // routing_bin_cells, next_point[2] // routing_bin_cells)
                    if dx == dy == 0:
                        # Reuse plated through-vias already belonging to this net.
                        # A snapped grid point remains inside the existing via land.
                        if reuse:
                            next_distance = distance + 1
                        else:
                            xy = next_point[1:]
                            if xy in forbidden_vias:
                                continue
                            if xy not in via_free:
                                via_free[xy] = not any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(args.via_diameter / 2 + 0.135)) for sh in sum((bi.get(bin_key, []) for bi in bins), [])) and not any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(args.via_drill / 2 + 0.105)) for sh in padbins.get(bin_key, []))
                            if not via_free[xy]:
                                continue
                            if xy not in via_spacing_free:
                                via_spacing_free[xy] = not any((point.x - q.x) ** 2 + (point.y - q.y) ** 2 < pcb.FromMM(0.255 + drill / 2 + args.via_drill / 2) ** 2 for q, name, drill in allvias if (q.x, q.y) not in soft_via_positions)
                            if not via_spacing_free[xy]:
                                continue
                    else:
                        if next_point not in free:
                            free[next_point] = not any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(width / 2 + 0.13)) for sh in bins[next_point[0]].get(bin_key, []))
                        if not free[next_point]:
                            continue
                        segment = pcb.SEG(pcb.VECTOR2I(pcb.FromMM(current[1] / 20), pcb.FromMM(current[2] / 20)), point)
                        if any(sh.Collide(segment, pcb.FromMM(width / 2 + 0.13)) for sh in bins[next_point[0]].get(bin_key, [])):
                            continue
                    if args.ripup_unlocked:
                        if dx == dy == 0:
                            soft_candidates = sum((bi.get(bin_key, []) for bi in soft_bins), [])
                            soft_segment, soft_margin = pcb.SEG(point, point), args.via_diameter / 2 + 0.135
                        else:
                            soft_candidates = soft_bins[next_point[0]].get(bin_key, [])
                            soft_segment, soft_margin = segment, width / 2 + 0.13
                        crossed = {t.m_Uuid.AsString(): t.GetNetname() for sh, t in soft_candidates if sh.Collide(soft_segment, pcb.FromMM(soft_margin))}
                        next_distance += sum(80 * (1 + ripped_net_counts.get(name, 0)) for name in crossed.values())
                    if next_distance >= cost.get(next_point, 1e12):
                        continue
                    cost[next_point] = next_distance
                    parent[next_point] = current
                    target_bounds = anchor_bounds[1 - side]
                    heuristic = math.hypot(max(target_bounds[0] - next_point[1], 0, next_point[1] - target_bounds[1]), max(target_bounds[2] - next_point[2], 0, next_point[2] - target_bounds[3]))
                    heapq.heappush(queue, (next_distance + heuristic, next_distance, next_point))
            if not reached:
                break
            route = [meeting]
            while route[-1] not in anchors[0]:
                route.append(parents[0][route[-1]])
            route.reverse()
            current = meeting
            while current not in anchors[1]:
                current = parents[1][current]
                route.append(current)
            proposed_vias = []
            invalid_via = None
            for current_point, next_point in zip(route, route[1:]):
                if current_point[0] == next_point[0]:
                    continue
                x_mm, y_mm = current_point[1] / 20, current_point[2] / 20
                if any(name == netname and (pcb.FromMM(x_mm) - q.x) ** 2 + (pcb.FromMM(y_mm) - q.y) ** 2 < pcb.FromMM(0.06) ** 2 for q, name, drill in allvias):
                    continue
                if any((x_mm - vx) ** 2 + (y_mm - vy) ** 2 < (0.255 + args.via_drill) ** 2 for vx, vy in proposed_vias):
                    invalid_via = current_point[1:]
                    break
                proposed_vias.append((x_mm, y_mm))
            if invalid_via is None:
                break
            forbidden_vias.update((invalid_via[0] + dx, invalid_via[1] + dy) for dx in range(-4, 5) for dy in range(-4, 5) if dx * dx + dy * dy <= 16)
            reached = False
            print(f"Retrying {netname}: proposed via pair violates drill spacing", flush=True)
        if not reached:
            if args.save_reachable:
                args.output.with_name(args.output.stem + "-reachable-" + netname.replace("/", "_") + ".json").write_text(json.dumps({"net": netname, "grid_mm": 0.05, "points": [list(c) for c in costs]}))
            failed_pairs.add(pair_key)
            log["failed"].append({"net": netname, "items": list(pair_key[1:]), "reason": "No path within search limit or drill-spacing retries", "states": sum(len(c) for c in costs)})
            print(f"No route: {netname}, {sum(len(c) for c in costs)} search states", flush=True)
            continue
        corners = [route[0]]
        for index in range(1, len(route) - 1):
            if tuple(route[index][k] - route[index - 1][k] for k in range(3)) != tuple(route[index + 1][k] - route[index][k] for k in range(3)):
                corners.append(route[index])
        corners.append(route[-1])
        segments = []
        ripup_ids = set()
        item_index = 0
        for a, c in zip(corners, corners[1:]):
            if a[0] != c[0]:
                via_position = pcb.VECTOR2I(pcb.FromMM(a[1] / 20), pcb.FromMM(a[2] / 20))
                if any(name == netname and (via_position.x - q.x) ** 2 + (via_position.y - q.y) ** 2 < pcb.FromMM(0.06) ** 2 for q, name, drill in allvias):
                    continue
                if args.ripup_unlocked:
                    via_key = (a[1] // routing_bin_cells, a[2] // routing_bin_cells)
                    ripup_ids.update(t.m_Uuid.AsString() for sh, t in sum((bi.get(via_key, []) for bi in soft_bins), []) if sh.Collide(pcb.SEG(via_position, via_position), pcb.FromMM(args.via_diameter / 2 + 0.135)))
                via = pcb.PCB_VIA(board)
                via.SetPosition(pcb.VECTOR2I(pcb.FromMM(a[1] / 20), pcb.FromMM(a[2] / 20)))
                via.SetWidth(pcb.FromMM(args.via_diameter))
                via.SetDrill(pcb.FromMM(args.via_drill))
                via.SetViaType(pcb.VIATYPE_THROUGH)
                via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
                via.SetNet(nets[netname])
                via.SetLocked(not args.ripup_unlocked)
                item_index += 1
                board.Add(via)
            else:
                segments.append((routing_layers[a[0]], (a[1] / 20, a[2] / 20), (c[1] / 20, c[2] / 20)))
        for endpoint, grid_point in zip([anchors[0][route[0]], anchors[1][route[-1]]], [route[0], route[-1]]):
            segments.append((routing_layers[endpoint[0]], endpoint[1:], (grid_point[1] / 20, grid_point[2] / 20)))
        for layer, a, c in segments:
            if a == c:
                continue
            if args.ripup_unlocked:
                seg = pcb.SEG(pcb.VECTOR2I(pcb.FromMM(a[0]), pcb.FromMM(a[1])), pcb.VECTOR2I(pcb.FromMM(c[0]), pcb.FromMM(c[1])))
                for bx in range(math.floor(min(a[0], c[0]) / routing_bin_mm) - routing_bin_padding, math.floor(max(a[0], c[0]) / routing_bin_mm) + routing_bin_padding + 1):
                    for by in range(math.floor(min(a[1], c[1]) / routing_bin_mm) - routing_bin_padding, math.floor(max(a[1], c[1]) / routing_bin_mm) + routing_bin_padding + 1):
                        ripup_ids.update(t.m_Uuid.AsString() for sh, t in soft_bins[routing_layers.index(layer)].get((bx, by), []) if sh.Collide(seg, pcb.FromMM(width / 2 + 0.13)))
            track = pcb.PCB_TRACK(board)
            track.SetStart(pcb.VECTOR2I(pcb.FromMM(a[0]), pcb.FromMM(a[1])))
            track.SetEnd(pcb.VECTOR2I(pcb.FromMM(c[0]), pcb.FromMM(c[1])))
            track.SetWidth(pcb.FromMM(width))
            track.SetLayer(layer)
            track.SetNet(nets[netname])
            track.SetLocked(not args.ripup_unlocked)
            item_index += 1
            board.Add(track)
        if ripup_ids:
            priority_nets = set()
            for t in list(board.GetTracks()):
                if t.m_Uuid.AsString() in ripup_ids:
                    assert not t.IsLocked() and t.GetNetname() not in critical and t.GetNetname() != netname
                    log["removed_items"].append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetname(), "for_net": netname, "layer": t.GetLayerName(), "start_mm": [pcb.ToMM(t.GetStart().x), pcb.ToMM(t.GetStart().y)], "end_mm": [pcb.ToMM(t.GetEnd().x), pcb.ToMM(t.GetEnd().y)]})
                    priority_nets.add(t.GetNetname())
                    board.Delete(t)
            for removed_net in priority_nets:
                ripped_net_counts[removed_net] = ripped_net_counts.get(removed_net, 0) + 1
            print(f"Removed {len(ripup_ids)} unlocked items to open {netname}", flush=True)
            failed_pairs.clear()
        board.BuildConnectivity()
        completed += 1
        log["routed"].append({"net": netname, "items": list(pair_key[1:]), "new_items": item_index, "search_states": sum(len(c) for c in costs), "width_mm": width})
        print(f"{netname}: {item_index} items, {sum(len(c) for c in costs)} search states", flush=True)
        if ripup_ids or completed >= args.batch_size:
            break
    if not completed:
        print("No additional routable pairs in the current DRC report", flush=True)
        break
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    pcb.SaveBoard(str(args.output), board)
    drc_path = args.output.with_name(args.output.stem + f"-pass{round_index + 1}-drc.json")
    process = subprocess.run([args.kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", str(drc_path), str(args.output)], capture_output=True, text=True)
    if process.returncode not in [0, 5] or not drc_path.exists():
        args.output.write_bytes(checkpoint)
        raise RuntimeError("DRC failed; last batch rolled back: " + process.stderr + process.stdout)
    next_report = json.loads(drc_path.read_text())
    new_violations = [v for v in next_report.get("violations", []) if v["type"] in electrical_types and (v["type"], tuple(sorted(x["uuid"] for x in v.get("items", [])))) not in baseline]
    if new_violations:
        rejected = args.output.with_name(args.output.stem + f"-rejected-pass{round_index + 1}.kicad_pcb")
        rejected.write_bytes(args.output.read_bytes())
        args.output.write_bytes(checkpoint)
        log["rejected_batch"] = {"board": str(rejected), "new_electrical_violations": new_violations}
        failed_validation = True
        print(f"Rolled back batch: {len(new_violations)} new electrical violations; inspect {rejected}", flush=True)
        break
    report = next_report
    log["batches"].append({"round": round_index + 1, "routed_pairs": completed, "unconnected_before": before_count, "unconnected_after": len(report.get("unconnected_items", [])), "drc": str(drc_path)})
    score = (sum(not any("[GND]" in i.get("description", "") for i in r.get("items", [])) for r in report.get("unconnected_items", [])), len(report.get("unconnected_items", [])))
    if score < best_score:
        best_score, best_round, best_report = score, round_index + 1, report
        best_checkpoint = args.output.read_bytes()
        stagnant_rounds = 0
    else:
        stagnant_rounds += 1
    print(f"Accepted batch{round_index + 1}: {before_count} -> {len(report.get('unconnected_items', []))} unconnected items; non-GND {score[0]}, best {best_score[0]}", flush=True)
    if args.ripup_unlocked and stagnant_rounds >= args.stagnation_rounds:
        print(f"Stopping after {stagnant_rounds} batches without a better checkpoint", flush=True)
        break
if args.ripup_unlocked:
    args.output.with_name(args.output.stem + "-last-attempt.kicad_pcb").write_bytes(args.output.read_bytes())
    args.output.write_bytes(best_checkpoint)
    report = best_report
    log["best_checkpoint"] = {"round": best_round, "non_gnd_unconnected": best_score[0], "total_unconnected": best_score[1], "restored": True}
    best_drc = args.output.with_name(args.output.stem + "-best-drc.json")
    best_drc.write_text(json.dumps(report, indent=2) + "\n")
log["remaining_unconnected"] = report.get("unconnected_items", [])
log["validation_failed"] = failed_validation
log_path = args.output.with_name(args.output.stem + "-routing-log.json")
log_path.write_text(json.dumps(log, indent=2) + "\n")
print(f"Saved {args.output}; {len(log['remaining_unconnected'])} connections remain; log {log_path}")
raise SystemExit(2 if failed_validation else 0)
