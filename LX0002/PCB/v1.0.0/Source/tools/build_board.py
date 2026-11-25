"""Build the initial LX0002 board from the reviewed circuit and placement tables.

Run with KiCad Python. This resets routing; routing is authored separately.
"""
from pathlib import Path
import json
import math
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import pcbnew as pcb

source = Path(__file__).resolve().parents[1]
mechanical = json.loads((source / 'mechanical.json').read_text())
parts = json.loads((source / 'parts.json').read_text())
placement = json.loads((source / 'placement.json').read_text())
length, width, thickness = mechanical['size_mm']
io = pcb.PCB_IO_KICAD_SEXPR()
board = pcb.BOARD()
board.SetCopperLayerCount(2)
board.GetDesignSettings().SetBoardThickness(pcb.FromMM(thickness))
with tempfile.TemporaryDirectory(prefix='lx0002-netlist-') as temporary:
    netlist_path = Path(temporary) / 'netlist.xml'
    subprocess.run(['/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', str(netlist_path), str(source / 'LX0002.kicad_sch')], check=True)
    schematic = ET.parse(netlist_path)
schematic_pad_nets = {}
for net in schematic.findall('.//nets/net'):
    for node in net.findall('node'):
        schematic_pad_nets[node.get('ref'), node.get('pin')] = net.get('name')
nets = {}
for code, name in enumerate(sorted(set(schematic_pad_nets.values())), 1):
    net = pcb.NETINFO_ITEM(board, name, code)
    board.Add(net)
    nets[name] = net
for part in parts:
    lib, name = part['footprint'].split(':')
    footprint = io.FootprintLoad(str(source / 'libraries' / (lib + '.pretty')), name)
    assert footprint, part['footprint']
    footprint.SetReference(part['ref'])
    footprint.SetValue(part['value'])
    footprint.SetFPID(pcb.LIB_ID(lib, name))
    footprint.SetPath(pcb.KIID_PATH(part['sheet_path'] + '/' + part['uuid']))
    board.Add(footprint)
    x, y, rotation, side = placement[part['ref']]
    footprint.SetPosition(pcb.VECTOR2I(round(x * 1e6), round(y * 1e6)))
    if side == 'Bottom':
        footprint.Flip(footprint.GetPosition(), False)
    footprint.SetOrientationDegrees(rotation)
    footprint.Value().SetVisible(False)
    fields = {field.GetName(): field for field in footprint.GetFields()}
    if 'LCSC' not in fields:
        field = pcb.PCB_FIELD(footprint, pcb.FIELD_T_USER, 'LCSC')
        footprint.Add(field)
        fields['LCSC'] = field
    fields['LCSC'].SetText(part['lcsc'])
    fields['LCSC'].SetVisible(False)
    fields['Datasheet'].SetText(part.get('datasheet', ''))
    footprint.Reference().SetLayer(pcb.B_Fab if side == 'Bottom' else pcb.F_Fab)
    footprint.Reference().SetTextSize(pcb.VECTOR2I(500000, 500000))
    footprint.Reference().SetTextThickness(80000)
    if not part['lcsc']:
        footprint.SetAttributes(footprint.GetAttributes() | pcb.FP_EXCLUDE_FROM_POS_FILES | pcb.FP_EXCLUDE_FROM_BOM)
    if part.get('dnp'):
        footprint.SetAttributes(footprint.GetAttributes() | pcb.FP_DNP)
    for pad in footprint.Pads():
        key = (part['ref'], pad.GetNumber())
        if pad.GetNumber() in part['pins']:
            assert schematic_pad_nets.get(key) == part['pins'][pad.GetNumber()], key
        if key in schematic_pad_nets:
            pad.SetNet(nets[schematic_pad_nets[key]])
for ref, (x, y) in mechanical['mounting_holes'].items():
    footprint = io.FootprintLoad(str(source / 'libraries' / 'MountingHole.pretty'), 'MountingHole_2.2mm_M2')
    footprint.SetReference(ref)
    footprint.SetAttributes(footprint.GetAttributes() | pcb.FP_BOARD_ONLY | pcb.FP_EXCLUDE_FROM_BOM | pcb.FP_EXCLUDE_FROM_POS_FILES)
    footprint.SetPosition(pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y)))
    footprint.Reference().SetLayer(pcb.F_Fab)
    footprint.Value().SetVisible(False)
    board.Add(footprint)
    keep = pcb.ZONE(board)
    keep.SetIsRuleArea(True)
    layers = pcb.LSET()
    layers.AddLayer(pcb.F_Cu)
    layers.AddLayer(pcb.B_Cu)
    keep.SetLayerSet(layers)
    keep.SetDoNotAllowTracks(True)
    keep.SetDoNotAllowVias(True)
    keep.SetDoNotAllowZoneFills(True)
    keep.SetDoNotAllowPads(False)
    keep.SetDoNotAllowFootprints(False)
    keep.SetZoneName(ref + ' case support clearance')
    outline = keep.Outline()
    outline.NewOutline()
    for angle in range(0, 360, 10):
        radius = mechanical['mounting_keepout_radius_mm']
        outline.Append(pcb.FromMM(x + radius * math.cos(math.radians(angle))), pcb.FromMM(y + radius * math.sin(math.radians(angle))))
    board.Add(keep)
for start, end in [((0, 0), (length, 0)), ((length, 0), (length, width)), ((length, width), (0, width)), ((0, width), (0, 0))]:
    edge = pcb.PCB_SHAPE()
    edge.SetShape(pcb.SHAPE_T_SEGMENT)
    edge.SetStart(pcb.VECTOR2I(pcb.FromMM(start[0]), pcb.FromMM(start[1])))
    edge.SetEnd(pcb.VECTOR2I(pcb.FromMM(end[0]), pcb.FromMM(end[1])))
    edge.SetLayer(pcb.Edge_Cuts)
    edge.SetWidth(50000)
    board.Add(edge)
for layer, polygon, name, no_tracks, no_pads, no_zones in [
    (pcb.F_Cu, mechanical['antenna_clearance'], 'Antenna radiator: no copper pour', False, False, True),
    (pcb.B_Cu, mechanical['antenna_clearance'], 'Antenna radiator: no copper', True, True, True),
]:
    keep = pcb.ZONE(board)
    keep.SetIsRuleArea(True)
    keep.SetLayer(layer)
    keep.SetDoNotAllowTracks(no_tracks)
    keep.SetDoNotAllowVias(no_zones)
    keep.SetDoNotAllowPads(no_pads)
    keep.SetDoNotAllowZoneFills(no_zones)
    keep.SetDoNotAllowFootprints(False)
    keep.SetZoneName(name)
    polygon_out = keep.Outline()
    polygon_out.NewOutline()
    for x, y in polygon:
        polygon_out.Append(pcb.FromMM(x), pcb.FromMM(y))
    board.Add(keep)
for entry in json.loads((source / 'silkscreen_layout.json').read_text()):
    text = pcb.PCB_TEXT(board)
    text.SetText(entry['text'])
    text.SetPosition(pcb.VECTOR2I(round(entry['at'][0] * 1e6), round(entry['at'][1] * 1e6)))
    text.SetTextSize(pcb.VECTOR2I(round(entry['size'] * 1e6), round(entry['size'] * 1e6)))
    text.SetTextThickness(round(entry['thickness'] * 1e6))
    text.SetTextAngle(pcb.EDA_ANGLE(entry.get('rotation', 0), pcb.DEGREES_T))
    text.SetLayer(pcb.F_SilkS if entry['layer'] == 'F.SilkS' else pcb.B_SilkS)
    text.SetMirrored(entry['layer'] == 'B.SilkS')
    board.Add(text)
board.GetDesignSettings().SetAuxOrigin(pcb.VECTOR2I(0, pcb.FromMM(width)))
board.GetTitleBlock().SetTitle('LX0002 USB 5V digital LED controller')
board.GetTitleBlock().SetRevision('1.0.0')
board.GetTitleBlock().SetDate('2026-11-25')
board.GetTitleBlock().SetCompany('Luxio')
board.BuildConnectivity()
pcb.SaveBoard(str(source / 'LX0002.kicad_pcb'), board)
print(f'Built {length} x {width}mm, {len(parts)} circuit footprints, 2 copper layers')
