"""Join disconnected GND copper with clearance-checked, tented stitching vias.

Run with KiCad's bundled Python:
  stitch_ground.py INPUT.kicad_pcb --output REVIEW.kicad_pcb
  [--project INPUT.kicad_pro] [--max-vias 40]

Input and output must differ. No input board or existing item is changed.
The utility uses each actual filled contour as a separate connectivity node,
including thermal spokes and holes. A zone UUID/DRC origin is never treated
as an island position. Only front/back filled-copper intersections that join
separate GND components are candidates; this does not create a blind via grid.
0.60/0.30 mm vias are preferred, with 0.45/0.20 mm fallback for tight islands.
Pads/paste lands, all drills, other nets, board edges and via-prohibited rule
areas are excluded. Track-only RF reference areas can receive GND vias.
Each accepted via must reduce GND DRC unconnected records without new
violations or additional non-GND disconnects. Failed trials are rolled back.
The output is always the last verified checkpoint; an incomplete result exits2.
"""
import argparse
import collections
import json
import math
from pathlib import Path
import shutil
import subprocess
import pcbnew as pcb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('board', type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--project', type=Path, help='Project rules if the input copy has no matching .kicad_pro')
parser.add_argument('--max-vias', type=int, default=40)
parser.add_argument('--grid', type=float, default=0.20, help='Candidate search pitch, not output via pitch')
parser.add_argument('--region', type=float, nargs=4, metavar=('XMIN', 'YMIN', 'XMAX', 'YMAX'), help='Restrict new via centers to this board region in mm')
parser.add_argument('--kicad-cli', default=shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args = parser.parse_args()
assert args.board.resolve() != args.output.resolve(), 'Use a distinct output board for review'
assert 0 < args.max_vias <= 100 and 0.05 <= args.grid <= 0.5
assert not args.region or (args.region[0] < args.region[2] and args.region[1] < args.region[3])
assert args.board.exists(), args.board
project = args.project or args.board.with_suffix('.kicad_pro')
assert project.exists(), 'Project rules are required; supply --project for a detached board copy'
args.output.parent.mkdir(parents=True, exist_ok=True)
trial_path = args.output.with_name('.' + args.output.stem + '.stitch-trial.kicad_pcb')
for suffix in ['.kicad_pro', '.kicad_dru']:
    source = project.with_suffix(suffix)
    destination = args.output.with_suffix(suffix)
    if source.exists() and source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    if source.exists():
        shutil.copy2(source, trial_path.with_suffix(suffix))
board = pcb.LoadBoard(str(args.board))
copper_layers = [pcb.F_Cu, pcb.In1_Cu, pcb.In2_Cu, pcb.B_Cu] if board.GetCopperLayerCount() == 4 else [pcb.F_Cu, pcb.B_Cu]
board.BuildConnectivity()
pcb.ZONE_FILLER(board).Fill(board.Zones())
pcb.SaveBoard(str(args.output), board)
drc_path = args.output.with_suffix('.stitch-drc.json')
log_path = args.output.with_suffix('.stitch.json')
result = subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--output', str(drc_path), str(args.output)], capture_output=True, text=True)
assert result.returncode == 0 and drc_path.exists(), result.stderr or result.stdout
report = json.loads(drc_path.read_text())
# Known library/courtyard warnings must not hide a newly introduced electrical,
# mechanical or silkscreen violation. Compare all types by their item UUIDs.
baseline = {(v['type'], tuple(sorted(x['uuid'] for x in v.get('items', [])))) for v in report.get('violations', [])}
initial_violations = dict(collections.Counter(v['type'] for v in report.get('violations', [])))
log = {'input_board': str(args.board.resolve()), 'output_board': str(args.output.resolve()),
       'project': str(project.resolve()), 'initial_violations': initial_violations,
       'accepted': [], 'rejected': [], 'rounds': [], 'candidate_region_mm': args.region}
rejected_points = set()
complete = False
search_grid = args.grid
for round_index in range(args.max_vias + 2):
    objects = {x.m_Uuid.AsString(): x for x in list(board.GetTracks()) + [pad for f in board.GetFootprints() for pad in f.Pads()] + list(board.Zones())}
    ground_records = [r for r in report.get('unconnected_items', []) if r.get('items') and all(objects.get(i['uuid']) is not None and objects[i['uuid']].GetNetname() == 'GND' for i in r['items'])]
    nonground_count = len(report.get('unconnected_items', [])) - len(ground_records)
    if round_index == 0:
        log['initial_ground_unconnected'] = len(ground_records)
        log['initial_other_unconnected'] = nonground_count
    if not ground_records:
        complete = True
        break
    # Filled contours belong to separate nodes. A single ZONE object can contain
    # disconnected copper contours, so treating the ZONE UUID as one node is wrong.
    nodes = []
    for zone in board.Zones():
        if zone.GetIsRuleArea() or zone.GetNetname() != 'GND':
            continue
        for layer in copper_layers:
            if not zone.IsOnLayer(layer):
                continue
            polygons = zone.GetFilledPolysList(layer)
            for index in range(polygons.OutlineCount()):
                polygon = polygons.UnitSet(index)
                if polygon.IsEmpty():
                    continue
                nodes.append({'kind': 'island', 'key': (zone.m_Uuid.AsString(), layer, index),
                              'name': '%s:%s:%d' % (zone.m_Uuid.AsString(), board.GetLayerName(layer), index),
                              'shapes': {layer: polygon}, 'zone': zone, 'island_index': index})
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            if pad.GetNetname() != 'GND':
                continue
            shapes = {layer: pad.GetEffectiveShape(layer) for layer in copper_layers
                      if pad.IsOnLayer(layer)}
            if shapes:
                # One plated pad is one conductive node on all its copper layers.
                nodes.append({'kind': 'pad', 'key': pad.m_Uuid.AsString(),
                              'name': footprint.GetReference() + '/' + pad.GetNumber(),
                              'shapes': shapes, 'item': pad})
    for track in board.GetTracks():
        if track.GetNetname() != 'GND':
            continue
        shapes = {layer: track.GetEffectiveShape(layer) for layer in copper_layers
                  if track.IsOnLayer(layer)}
        if shapes:
            # A plated through-via likewise unifies its front/back copper shapes.
            nodes.append({'kind': 'via' if isinstance(track, pcb.PCB_VIA) else 'track',
                          'key': track.m_Uuid.AsString(), 'name': track.m_Uuid.AsString(),
                          'shapes': shapes, 'item': track})
    # Cache integer bounding boxes before exact shape collision. Keep every shape
    # object alive in nodes; temporary C++ shape references otherwise risk SWIG GC.
    for node in nodes:
        node['bounds'] = {}
        for layer, shape in node['shapes'].items():
            box = shape.BBox()
            node['bounds'][layer] = (box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom())
    parents = list(range(len(nodes)))
    edges = 0
    for i, a in enumerate(nodes):
        for j in range(i):
            b = nodes[j]
            connected = False
            for layer in set(a['shapes']) & set(b['shapes']):
                x = a['bounds'][layer]
                y = b['bounds'][layer]
                if x[0] > y[2] or x[2] < y[0] or x[1] > y[3] or x[3] < y[1]:
                    continue
                # Zero clearance means actual physical copper overlap/touch.
                if a['shapes'][layer].Collide(b['shapes'][layer], 0):
                    connected = True
                    break
            if connected:
                ra, rb = i, j
                while parents[ra] != ra:
                    parents[ra] = parents[parents[ra]]
                    ra = parents[ra]
                while parents[rb] != rb:
                    parents[rb] = parents[parents[rb]]
                    rb = parents[rb]
                if ra != rb:
                    parents[ra] = rb
                edges += 1
    components = {}
    for index, node in enumerate(nodes):
        root = index
        while parents[root] != root:
            parents[root] = parents[parents[root]]
            root = parents[root]
        node['component'] = root
        components.setdefault(root, []).append(index)
    log['rounds'].append({'round': round_index, 'ground_components': len(components),
                          'ground_unconnected': len(ground_records), 'nodes': len(nodes),
                          'filled_contours': sum(n['kind'] == 'island' for n in nodes), 'search_grid_mm':search_grid})
    print(f'GND: {len(ground_records)} DRC connections, {len(components)} physical components', flush=True)
    if len(log['accepted']) >= args.max_vias:
        break
    # Rebuild safe-placement obstacles after each refill. Shape references are
    # retained for the entire round so SWIG cannot free their C++ storage.
    foreign, pads, holes, forbidden = [], [], [], []
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            for layer in copper_layers:
                if pad.IsOnLayer(layer):
                    shape = pad.GetEffectiveShape(layer)
                    pads.append(shape)
                    if pad.GetNetname() != 'GND':
                        foreign.append(shape)
            if pad.HasDrilledHole():
                holes.append(pad.GetEffectiveHoleShape())
        for zone in footprint.Zones():
            if zone.GetIsRuleArea() and zone.GetDoNotAllowVias():
                forbidden.append(zone.Outline())
    for track in board.GetTracks():
        if track.GetNetname() != 'GND':
            for layer in copper_layers:
                if track.IsOnLayer(layer):
                    foreign.append(track.GetEffectiveShape(layer))
        if isinstance(track, pcb.PCB_VIA):
            holes.append(pcb.SHAPE_CIRCLE(track.GetPosition(), track.GetDrillValue() // 2).Clone())
    for zone in board.Zones():
        if zone.GetIsRuleArea():
            if zone.GetDoNotAllowVias():
                forbidden.append(zone.Outline())
        elif zone.GetNetname() != 'GND':
            for layer in copper_layers:
                if zone.IsOnLayer(layer):
                    foreign.append(zone.GetFilledPolysList(layer).Clone())
    # Every supplied board pad is excluded, including same-net SMT pads. The
    # extra 0.025 mm copper gap plus via tenting keeps drill/paste wicking away.
    bins = {'foreign': {}, 'pads': {}, 'holes': {}, 'forbidden': {}}
    for category, shapes in [('foreign', foreign), ('pads', pads), ('holes', holes), ('forbidden', forbidden)]:
        for shape in shapes:
            box = shape.BBox()
            for bx in range(math.floor(pcb.ToMM(box.GetLeft()) / 2) - 1, math.floor(pcb.ToMM(box.GetRight()) / 2) + 2):
                for by in range(math.floor(pcb.ToMM(box.GetTop()) / 2) - 1, math.floor(pcb.ToMM(box.GetBottom()) / 2) + 2):
                    bins[category].setdefault((bx, by), []).append(shape)
    edge = board.GetBoardEdgesBoundingBox()
    candidates = []
    island_nodes = [n for n in nodes if n['kind'] == 'island']
    # The via center must lie within actual GND fill on both sides, inset by
    # 0.025 mm to avoid marginal boundary contacts. Its annulus may extend into
    # clear space: exact other-net/pad/keepout checks below protect that area.
    for diameter, drill in [(0.60, 0.30), (0.45, 0.20)]:
        insets = {}
        for i, node in enumerate(island_nodes):
            layer = next(iter(node['shapes']))
            polygon = node['shapes'][layer].CloneDropTriangulation()
            polygon.Deflate(pcb.FromMM(0.025), pcb.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcb.FromMM(0.005))
            insets[i] = polygon
        for i, a in enumerate(island_nodes):
            if insets[i].IsEmpty():
                continue
            for j, b in enumerate(island_nodes):
                if j <= i or next(iter(a['shapes'])) == next(iter(b['shapes'])) or a['component'] == b['component'] or insets[j].IsEmpty():
                    continue
                x, y = a['bounds'][next(iter(a['shapes']))], b['bounds'][next(iter(b['shapes']))]
                if x[0] > y[2] or x[2] < y[0] or x[1] > y[3] or x[3] < y[1]:
                    continue
                intersection = insets[i].CloneDropTriangulation()
                intersection.BooleanIntersection(insets[j])
                if intersection.IsEmpty():
                    continue
                box = intersection.BBox()
                margin = 0.305 + diameter / 2
                x0 = max(pcb.ToMM(box.GetLeft()), pcb.ToMM(edge.GetLeft()) + margin)
                x1 = min(pcb.ToMM(box.GetRight()), pcb.ToMM(edge.GetRight()) - margin)
                y0 = max(pcb.ToMM(box.GetTop()), pcb.ToMM(edge.GetTop()) + margin)
                y1 = min(pcb.ToMM(box.GetBottom()), pcb.ToMM(edge.GetBottom()) - margin)
                if x0 > x1 or y0 > y1:
                    continue
                cx, cy = (x0+x1)/2, (y0+y1)/2
                points = [(round(cx, 4), round(cy, 4))]
                points += [(round(ix*search_grid, 4), round(iy*search_grid, 4))
                           for ix in range(math.ceil(x0/search_grid), math.floor(x1/search_grid)+1)
                           for iy in range(math.ceil(y0/search_grid), math.floor(y1/search_grid)+1)]
                points.sort(key=lambda q: (q[0]-cx)**2+(q[1]-cy)**2)
                found = []
                for x, y in points:
                    if args.region and not (args.region[0] <= x <= args.region[2] and args.region[1] <= y <= args.region[3]):
                        continue
                    point_key = (round(x,4), round(y,4), diameter)
                    if point_key in rejected_points or any((x-q[0])**2+(y-q[1])**2 < 0.8**2 for q in found):
                        continue
                    point = pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))
                    if not intersection.Contains(point):
                        continue
                    key = (math.floor(x/2), math.floor(y/2))
                    if any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(diameter/2 + 0.135)) for sh in bins['foreign'].get(key, [])):
                        continue
                    if any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(diameter/2 + 0.025)) for sh in bins['pads'].get(key, [])):
                        continue
                    if any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(drill/2 + 0.255)) for sh in bins['holes'].get(key, [])):
                        continue
                    if any(sh.Collide(pcb.SEG(point, point), pcb.FromMM(diameter/2 + 0.005)) for sh in bins['forbidden'].get(key, [])):
                        continue
                    candidates.append({'x':x, 'y':y, 'diameter':diameter, 'drill':drill,
                        'islands':[a['name'],b['name']], 'components':[a['component'],b['component']],
                        'component_nodes':[len(components[a['component']]),len(components[b['component']])],
                        'overlap_area_mm2':intersection.Area()/1e12})
                    found.append((x,y))
                    if len(found) == 3:
                        break
    # Connect the largest available groups first. Prefer the larger via and
    # broad copper overlap; only a handful of candidates are ever installed.
    candidates.sort(key=lambda c: (-sum(c['component_nodes']), -c['diameter'], -c['overlap_area_mm2']))
    log['rounds'][-1]['candidate_count'] = len(candidates)
    if not candidates and search_grid > 0.05:
        search_grid = 0.05
        print('Refining the remaining island search to 0.05 mm', flush=True)
        continue
    if not candidates:
        log['stopped_reason'] = 'No safe front/back filled-copper overlap connects the remaining components; a short reviewed GND route may be required.'
        break
    accepted = False
    checkpoint = args.output.read_bytes()
    previous_report = report
    for candidate in candidates:
        via = pcb.PCB_VIA(board)
        via.SetPosition(pcb.VECTOR2I(pcb.FromMM(candidate['x']), pcb.FromMM(candidate['y'])))
        via.SetWidth(pcb.FromMM(candidate['diameter']))
        via.SetDrill(pcb.FromMM(candidate['drill']))
        via.SetViaType(pcb.VIATYPE_THROUGH)
        via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
        via.SetNet(board.FindNet('GND'))
        via.SetFrontTentingMode(pcb.TENTING_MODE_TENTED)
        via.SetBackTentingMode(pcb.TENTING_MODE_TENTED)
        via.SetLocked(True)
        candidate['uuid'] = via.m_Uuid.AsString()
        board.Add(via)
        board.BuildConnectivity()
        pcb.ZONE_FILLER(board).Fill(board.Zones())
        # Validate a separate trial file so even an interrupted CLI or script
        # exception cannot replace the last verified output with bad geometry.
        pcb.SaveBoard(str(trial_path), board)
        result = subprocess.run([args.kicad_cli, 'pcb', 'drc', '--format', 'json', '--output', str(drc_path), str(trial_path)], capture_output=True, text=True)
        trial = json.loads(drc_path.read_text()) if result.returncode == 0 and drc_path.exists() else None
        new_violations, after_ground, after_other = [], None, None
        if trial is not None:
            trial_objects = {x.m_Uuid.AsString(): x for x in list(board.GetTracks()) + [p for f in board.GetFootprints() for p in f.Pads()] + list(board.Zones())}
            after_ground = sum(bool(r.get('items')) and all(trial_objects.get(i['uuid']) is not None and trial_objects[i['uuid']].GetNetname() == 'GND' for i in r['items']) for r in trial.get('unconnected_items', []))
            after_other = len(trial.get('unconnected_items', [])) - after_ground
            new_violations = [v for v in trial.get('violations', []) if (v['type'], tuple(sorted(x['uuid'] for x in v.get('items', [])))) not in baseline]
        if trial is not None and not new_violations and after_ground < len(ground_records) and after_other <= nonground_count:
            candidate.update(before_ground=len(ground_records), after_ground=after_ground, after_other=after_other)
            args.output.write_bytes(trial_path.read_bytes())
            log['accepted'].append(candidate)
            report = trial
            accepted = True
            print(f"Accepted GND via ({candidate['x']:.3f},{candidate['y']:.3f}) {candidate['diameter']:.2f}/{candidate['drill']:.2f}: {len(ground_records)} -> {after_ground}", flush=True)
            break
        # Restore the last good copper fill and geometry, not just the via.
        candidate.update(new_violations=[v['type'] for v in new_violations], after_ground=after_ground, after_other=after_other,
                         reason='DRC command failed' if trial is None else 'No improvement or new DRC violation')
        log['rejected'].append(candidate)
        rejected_points.add((round(candidate['x'],4),round(candidate['y'],4),candidate['diameter']))
        args.output.write_bytes(checkpoint)
        board = pcb.LoadBoard(str(args.output))
        report = previous_report
        drc_path.write_text(json.dumps(report, indent=2)+'\n')
        print(f"Rejected GND via ({candidate['x']:.3f},{candidate['y']:.3f}); checkpoint restored", flush=True)
    log_path.write_text(json.dumps(log, indent=2)+'\n')
    if not accepted:
        log['stopped_reason'] = 'All safe geometric candidates failed DRC/improvement validation; last good board retained.'
        break
log['remaining_components'] = []
if not complete:
    for root, indexes in sorted(components.items(), key=lambda x: -len(x[1])):
        bounds = [b for i in indexes for b in nodes[i]['bounds'].values()]
        log['remaining_components'].append({'nodes':len(indexes),
            'pads':[nodes[i]['name'] for i in indexes if nodes[i]['kind']=='pad'],
            'bounds_mm':[pcb.ToMM(min(b[0] for b in bounds)),pcb.ToMM(min(b[1] for b in bounds)),
                         pcb.ToMM(max(b[2] for b in bounds)),pcb.ToMM(max(b[3] for b in bounds))]})
log['complete'] = complete
log['final_ground_unconnected'] = len(ground_records)
log['final_other_unconnected'] = nonground_count
log['final_violations'] = dict(collections.Counter(v['type'] for v in report.get('violations', [])))
log['output_verified'] = True
log_path.write_text(json.dumps(log, indent=2)+'\n')
for temporary in [trial_path, trial_path.with_suffix('.kicad_pro'), trial_path.with_suffix('.kicad_dru')]:
    temporary.unlink(missing_ok=True)
print(f"Saved verified output {args.output}: {len(log['accepted'])} useful GND vias; {len(ground_records)} GND records remain", flush=True)
if not complete:
    raise SystemExit(2)
