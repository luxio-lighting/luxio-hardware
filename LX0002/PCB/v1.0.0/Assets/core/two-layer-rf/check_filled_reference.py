"""Read-only geometric audit of an already-filled LX0002 board.

Run with KiCad's Python. This samples GND copper and checks the straight RF
sections; it does not replace native DRC, connectivity, or RF measurements.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import pcbnew as pcb

parser = argparse.ArgumentParser()
parser.add_argument('board', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source = Path(__file__).resolve().parents[3] / 'Source'
layout = json.loads((source / 'rf_clock_layout.json').read_text())
board = pcb.LoadBoard(str(args.board))
polys = {pcb.F_Cu: [], pcb.B_Cu: []}
for zone in board.Zones():
    if zone.GetIsRuleArea() or zone.GetNetname() != 'GND':
        continue
    for layer in polys:
        if zone.IsOnLayer(layer) and zone.HasFilledPolysForLayer(layer):
            poly = zone.GetFilledPolysList(layer)
            if poly.OutlineCount():
                polys[layer].append(poly)
pads = {layer: [pad for footprint in board.GetFootprints() for pad in footprint.Pads()
                if pad.IsOnLayer(layer) and pad.GetNetname() == 'GND'] for layer in polys}
tracks = {layer: [track for track in board.GetTracks() if track.IsOnLayer(layer)
                 and track.GetNetname() == 'GND'] for layer in polys}
report = {
    'board': str(args.board.resolve()),
    'board_sha256': hashlib.sha256(args.board.read_bytes()).hexdigest(),
    'rf_layout_sha256': hashlib.sha256((source / 'rf_clock_layout.json').read_bytes()).hexdigest(),
    'method': 'Native filled polygons, GND pads, and GND tracks/vias sampled in XY. GND via drill centers count as intentional ground-via locations.',
    'limits': 'Sampling is not a field solver or electrical connectivity proof. Run native DRC and inspect ground-island connectivity separately. Component launches, bends, and the antenna land pattern are not uniform transmission lines.',
    'filled_ground_zones': {pcb.LayerName(layer): len(polys[layer]) for layer in polys},
}
if not all(polys.values()):
    report['status'] = 'unfilled_or_missing_ground_zone'
else:
    samples = []
    regions = []
    reference_vertices = []
    for area in sorted((zone for zone in board.Zones() if zone.GetIsRuleArea() and zone.GetZoneName().startswith('RF ground reference ')), key=lambda zone: zone.GetZoneName()):
        outline = area.Outline().Outline(0)
        reference_vertices.append([[pcb.ToMM(outline.CPoint(index).x), pcb.ToMM(outline.CPoint(index).y)] for index in range(outline.PointCount())])
    report['native_reference_regions_mm'] = reference_vertices
    for index, vertices in enumerate(reference_vertices):
        region = pcb.SHAPE_POLY_SET(); region.NewOutline()
        for x, y in vertices:
            region.Append(pcb.FromMM(x), pcb.FromMM(y))
        regions.append(region)
        xmin, xmax = min(p[0] for p in vertices), max(p[0] for p in vertices)
        ymin, ymax = min(p[1] for p in vertices), max(p[1] for p in vertices)
        # Keep samples off exact rule boundaries and omit the expanded antenna
        # copper-free window, which overrides the ground-reference polygons.
        for ix in range(math.ceil((xmax-xmin)/.1)):
            x = round(xmin + .05 + ix*.1, 6)
            for iy in range(math.ceil((ymax-ymin)/.1)):
                y = round(ymin + .05 + iy*.1, 6)
                pt = pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))
                if not region.Contains(pt):
                    continue
                if 6.0 <= x <= 14.4 and y <= 3.2:
                    continue
                samples.append({'group': 'bottom_reference_'+str(index+1), 'layer': pcb.B_Cu, 'xy': [x,y]})
    cross_sections = []
    rf_segments = []
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA) or track.GetNetname() != 'RF_50' or abs(pcb.ToMM(track.GetWidth())-.8) > .00001:
            continue
        start = [pcb.ToMM(track.GetStart().x), pcb.ToMM(track.GetStart().y)]
        end = [pcb.ToMM(track.GetEnd().x), pcb.ToMM(track.GetEnd().y)]
        if math.dist(start, end) >= 1.1:
            rf_segments.append((start, end))
    report['uniform_rf_segments_mm'] = rf_segments
    for segment_index, (start, end) in enumerate(rf_segments):
        dx, dy = end[0]-start[0], end[1]-start[1]
        length = math.hypot(dx, dy); nx, ny = -dy/length, dx/length
        distance = .55
        while distance <= length-.55+1e-6:
            center = [start[0]+distance*dx/length, start[1]+distance*dy/length]
            section = {'segment': segment_index+1, 'center_mm': center, 'sides': {}}
            cross_sections.append(section)
            section_index = len(cross_sections)-1
            for side in [-1,1]:
                key = 'rf_section_'+str(section_index)+'_side_'+str(side)
                section['sides'][str(side)] = {'group': key}
                for step in range(121):
                    offset = .4 + step*.005
                    samples.append({'group': key, 'layer': pcb.F_Cu, 'xy': [center[0]+side*nx*offset,center[1]+side*ny*offset], 'offset_mm': offset})
            for offset in [-.8,-.4,0,.4,.8]:
                samples.append({'group': 'RF_bottom_reference', 'layer': pcb.B_Cu, 'xy': [center[0]+nx*offset,center[1]+ny*offset]})
            distance += .35
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA) or track.GetNetname() not in {'XTAL_P', 'XTAL_P_CRYSTAL', 'XTAL_N'}:
            continue
        start = [pcb.ToMM(track.GetStart().x), pcb.ToMM(track.GetStart().y)]
        end = [pcb.ToMM(track.GetEnd().x), pcb.ToMM(track.GetEnd().y)]
        dx, dy = end[0]-start[0], end[1]-start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        for index in range(math.ceil(length/.025)+1):
            t = min(1, index*.025/length)
            for offset in [-.15, 0, .15]:
                samples.append({'group': 'clock_bottom_reference', 'layer': pcb.B_Cu, 'xy': [start[0]+t*dx-offset*dy/length, start[1]+t*dy+offset*dx/length]})
    groups = {}
    for sample in samples:
        layer = sample['layer']; x,y = sample['xy']
        point = pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))
        has_ground = (any(poly.Contains(point) for poly in polys[layer])
                      or any(pad.HitTest(point) for pad in pads[layer])
                      or any(track.HitTest(point) for track in tracks[layer]))
        group = groups.setdefault(sample['group'], {'count':0,'ground_count':0,'missing_xy_mm':[],'first_ground_offset_mm':None})
        group['count'] += 1
        if has_ground:
            group['ground_count'] += 1
            if 'offset_mm' in sample and group['first_ground_offset_mm'] is None:
                group['first_ground_offset_mm'] = sample['offset_mm']
        elif 'offset_mm' not in sample:
            group['missing_xy_mm'].append([round(x,5),round(y,5)])
    report['bottom_ground_coverage'] = {}
    for name, group in groups.items():
        if not name.startswith('rf_section_'):
            report['bottom_ground_coverage'][name] = {
                'samples': group['count'], 'ground_samples': group['ground_count'],
                'missing_count': len(group['missing_xy_mm']),
                'missing_xy_mm': group['missing_xy_mm'][:100],
            }
    for section in cross_sections:
        for side in section['sides'].values():
            group = groups[side.pop('group')]
            side['first_ground_distance_from_center_mm'] = group['first_ground_offset_mm']
            side['inferred_gap_from_nominal_trace_edge_mm'] = None if group['first_ground_offset_mm'] is None else round(group['first_ground_offset_mm']-.4,5)
    report['rf_cross_sections'] = cross_sections
    non_ground_vias = []
    for track in board.GetTracks():
        if not isinstance(track, pcb.PCB_VIA) or track.GetNetname() == 'GND':
            continue
        center = track.GetPosition(); radius = track.GetWidth(pcb.B_Cu)/2
        probe = [center] + [pcb.VECTOR2I(round(center.x+radius*math.cos(i*math.pi/16)),round(center.y+radius*math.sin(i*math.pi/16))) for i in range(32)]
        hits = [index+1 for index, region in enumerate(regions) if any(region.Contains(point) for point in probe)]
        if hits:
            non_ground_vias.append({'net':track.GetNetname(),'xy_mm':[pcb.ToMM(center.x),pcb.ToMM(center.y)],'reference_regions':hits})
    report['non_ground_vias_touching_reference_regions'] = non_ground_vias
    antenna_fill = []
    for layer in polys:
        count = 0; examples = []
        for ix in range(80):
            for iy in range(30):
                x,y = 6.25+ix*.1,.05+iy*.1
                point = pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y))
                if any(poly.Contains(point) for poly in polys[layer]):
                    count += 1
                    if len(examples)<10:examples.append([round(x,5),round(y,5)])
        antenna_fill.append({'layer':pcb.LayerName(layer),'ground_fill_samples_inside_window':count,'examples_xy_mm':examples})
    report['antenna_ground_fill'] = antenna_fill
    # Measure the complete FH4R2 exposed-pad projection separately from the
    # protected core. The static BOOT route may use only the documented outer
    # right rim; this is an explicit deviation from a completely solid plane.
    ep = pcb.SHAPE_POLY_SET(); ep.NewOutline()
    for x,y in [(12.15,7.15),(17.85,7.15),(17.85,12.85),(12.15,12.85)]:
        ep.Append(round(x*1e6),round(y*1e6))
    ep_ground = pcb.SHAPE_POLY_SET()
    for polygon in polys[pcb.B_Cu]:
        ep_ground.BooleanAdd(polygon)
    ep_ground.BooleanIntersection(ep)
    ep_missing = pcb.SHAPE_POLY_SET(ep)
    ep_missing.BooleanSubtract(ep_ground)
    allowed_rim = pcb.SHAPE_POLY_SET()
    for area in board.Zones():
        if area.GetIsRuleArea() and (area.GetZoneName() == 'EP outer rim: BOOT only' or area.GetZoneName().startswith('EP pour corner rounding ')):
            allowed_rim.BooleanAdd(area.Outline())
    unexpected_missing = pcb.SHAPE_POLY_SET(ep_missing)
    unexpected_missing.BooleanSubtract(allowed_rim)
    ep_pad = next(pad for footprint in board.GetFootprints() if footprint.GetReference() == 'U1' for pad in footprint.Pads() if pad.GetNumber() == '57')
    full_front_ground = ep_pad.GetNetname() == 'GND' and ep_pad.GetSize(pcb.F_Cu).x == ep_pad.GetSize(pcb.F_Cu).y == 5700000
    central_vias = []
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA) and track.GetNetname() == 'GND':
            x,y = pcb.ToMM(track.GetPosition().x),pcb.ToMM(track.GetPosition().y)
            if any(abs(x-a)<.00001 and abs(y-b)<.00001 for a in [13.6,15,16.4] for b in [8.6,10,11.4]):
                central_vias.append([x,y,pcb.ToMM(track.GetWidth(pcb.B_Cu)),pcb.ToMM(track.GetDrillValue())])
    ep_coverage = 100*ep_ground.Area()/ep.Area()
    ep_outside_rim = unexpected_missing.Area()/1e12
    ep_issue = ep_coverage < 95 or ep_outside_rim > .000001 or ep_ground.OutlineCount() != 1 or len(central_vias) != 9 or not full_front_ground
    report['ep_ground_reference'] = {
        'method': 'Exact native filled-GND polygon intersection with the full 5.7mm exposed-pad projection; intentional GND via drill locations remain reference connections.',
        'full_projection_area_mm2': ep.Area()/1e12,
        'bottom_ground_area_mm2': ep_ground.Area()/1e12,
        'bottom_ground_coverage_percent': ep_coverage,
        'minimum_accepted_coverage_percent': 95,
        'missing_ground_outside_documented_allowance_mm2': ep_outside_rim,
        'allowed_bottom_corner_chamfer_max_mm': .05,
        'covered_projection_connected_outlines': ep_ground.OutlineCount(),
        'full_front_exposed_pad_ground': full_front_ground,
        'central_ground_vias_xy_diameter_drill_mm': sorted(central_vias),
        'documented_tradeoff': 'Static BOOT routing occupies the outer-right 0.28mm EP rim; two bottom-corner pour-rounding chamfers are bounded to 0.05mm each. This is a compact two-layer deviation from Espressif complete-chip-ground guidance, not production/RF qualification.',
        'status': 'pass' if not ep_issue else 'review_required',
    }
    missing = sum(group['missing_count'] for group in report['bottom_ground_coverage'].values())
    gap_issue = any(side['inferred_gap_from_nominal_trace_edge_mm'] is None or not .18 <= side['inferred_gap_from_nominal_trace_edge_mm'] <= .23 for section in cross_sections for side in section['sides'].values())
    report['status'] = 'review_required' if not reference_vertices or not cross_sections or missing or gap_issue or ep_issue or non_ground_vias or any(item['ground_fill_samples_inside_window'] for item in antenna_fill) else 'sampled_geometry_pass'
if args.output:
    args.output.write_text(json.dumps(report, indent=2)+'\n')
else:
    print(json.dumps(report, indent=2))
