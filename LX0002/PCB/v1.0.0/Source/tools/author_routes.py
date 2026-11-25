"""Apply reviewed manual routing tables before routing the remaining signals.

Run immediately after build_board.py. Does not move footprints.
"""
from pathlib import Path
import argparse
import json
import pcbnew as pcb

source = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--board', type=Path, default=source / 'LX0002.kicad_pcb')
parser.add_argument('--layout', action='append')
args = parser.parse_args()
board_path = args.board
board = pcb.LoadBoard(str(board_path))
nets = {net.GetNetname(): net for net in board.GetNetInfo().NetsByNetcode().values()}
footprints = {footprint.GetReference(): footprint for footprint in board.GetFootprints()}
count = 0
for name in args.layout or ['rf_clock_layout.json', 'power_layout.json', 'usb_layout.json', 'power_distribution_layout.json', 'manual_layout.json']:
    path = source / name
    if not path.exists():
        continue
    layout = json.loads(path.read_text())
    for ref, position in layout.get('placements', {}).items():
        footprint = footprints[ref]
        assert abs(pcb.ToMM(footprint.GetPosition().x)-position[0]) < .005, (name, ref, 'X changed')
        assert abs(pcb.ToMM(footprint.GetPosition().y)-position[1]) < .005, (name, ref, 'Y changed')
        assert abs((footprint.GetOrientationDegrees()-position[2]+180)%360-180) < .01, (name, ref, 'rotation changed')
    for route in layout.get('routes', []):
        layer = pcb.F_Cu if route.get('layer', 'F.Cu') == 'F.Cu' else pcb.B_Cu
        for start, end in zip(route['points'], route['points'][1:]):
            if start == end:
                continue
            track = pcb.PCB_TRACK(board)
            track.SetStart(pcb.VECTOR2I(round(start[0] * 1e6), round(start[1] * 1e6)))
            track.SetEnd(pcb.VECTOR2I(round(end[0] * 1e6), round(end[1] * 1e6)))
            track.SetWidth(round(route.get('width_mm', route.get('width')) * 1e6))
            track.SetNet(nets[route['net']])
            track.SetLayer(layer)
            track.SetLocked(True)
            board.Add(track)
            count += 1
    vias = layout.get('vias', []) + layout.get('signal_vias', []) + [{'net': 'GND', 'xy': point, 'diameter_mm': layout.get('via_diameter_mm', .6), 'drill_mm': layout.get('via_drill_mm', .3)} for point in layout.get('ground_vias_mm', [])]
    for entry in vias:
        x, y = entry.get('xy', entry.get('at'))
        via = pcb.PCB_VIA(board)
        via.SetPosition(pcb.VECTOR2I(round(x * 1e6), round(y * 1e6)))
        via.SetWidth(round(entry.get('diameter_mm', entry.get('diameter', .6)) * 1e6))
        via.SetDrill(round(entry.get('drill_mm', entry.get('drill', .3)) * 1e6))
        via.SetViaType(pcb.VIATYPE_THROUGH)
        via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
        via.SetNet(nets[entry['net']])
        via.SetFrontTentingMode(pcb.TENTING_MODE_TENTED)
        via.SetBackTentingMode(pcb.TENTING_MODE_TENTED)
        via.SetLocked(True)
        board.Add(via)
        count += 1
    for index, polygon in enumerate(layout.get('bottom_reference_regions_mm', [])):
        area = pcb.ZONE(board)
        area.SetIsRuleArea(True)
        area.SetLayer(pcb.B_Cu)
        area.SetDoNotAllowTracks(True)
        area.SetDoNotAllowVias(False)
        area.SetDoNotAllowPads(True)
        area.SetDoNotAllowZoneFills(False)
        area.SetDoNotAllowFootprints(False)
        area.SetZoneName(('RF ground reference ' if name == 'rf_clock_layout.json' else 'Buck input ground reference ') + str(index+1))
        outline = area.Outline()
        outline.NewOutline()
        for x, y in polygon:
            outline.Append(pcb.FromMM(x), pcb.FromMM(y))
        board.Add(area)
    if layout.get('ep_outer_rim_boot_allowance_mm'):
        area = pcb.ZONE(board)
        area.SetIsRuleArea(True)
        area.SetLayer(pcb.B_Cu)
        area.SetDoNotAllowTracks(False)
        area.SetDoNotAllowVias(False)
        area.SetDoNotAllowPads(False)
        area.SetDoNotAllowZoneFills(False)
        area.SetDoNotAllowFootprints(False)
        area.SetZoneName('EP outer rim: BOOT only')
        outline = area.Outline()
        outline.NewOutline()
        for x, y in layout['ep_outer_rim_boot_allowance_mm']:
            outline.Append(round(x*1e6),round(y*1e6))
        board.Add(area)
    for index, polygon in enumerate(layout.get('ep_corner_rounding_allowances_mm', [])):
        area = pcb.ZONE(board)
        area.SetIsRuleArea(True)
        area.SetLayer(pcb.B_Cu)
        area.SetDoNotAllowTracks(True)
        area.SetDoNotAllowVias(True)
        area.SetDoNotAllowPads(True)
        area.SetDoNotAllowZoneFills(False)
        area.SetDoNotAllowFootprints(False)
        area.SetZoneName('EP pour corner rounding ' + str(index+1))
        outline = area.Outline()
        outline.NewOutline()
        for x, y in polygon:
            outline.Append(round(x*1e6),round(y*1e6))
        board.Add(area)
mechanical = json.loads((source / 'mechanical.json').read_text())
length, width, _ = mechanical['size_mm']
for layer in [pcb.F_Cu, pcb.B_Cu]:
    zone = pcb.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(nets['GND'])
    zone.SetLocalClearance(pcb.FromMM(.15))
    zone.SetMinThickness(pcb.FromMM(.15))
    zone.SetPadConnection(pcb.ZONE_CONNECTION_FULL)
    zone.SetAssignedPriority(0)
    zone.SetThermalReliefGap(pcb.FromMM(.25))
    zone.SetThermalReliefSpokeWidth(pcb.FromMM(.4))
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in [(.3, .3), (length-.3, .3), (length-.3, width-.3), (.3, width-.3)]:
        outline.Append(pcb.FromMM(x), pcb.FromMM(y))
    board.Add(zone)
board.BuildConnectivity()
pcb.ZONE_FILLER(board).Fill(board.Zones())
pcb.SaveBoard(str(board_path), board)
print('Applied', count, 'manual track/via items and ground references')
