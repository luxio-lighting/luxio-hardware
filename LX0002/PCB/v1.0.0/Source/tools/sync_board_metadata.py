"""Synchronize symbol fields and explicit NC net names without changing geometry."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import pcbnew as pcb

source = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board', type=Path, default=source / 'LX0002.kicad_pcb')
args = parser.parse_args()
parts = {part['ref']: part for part in json.loads((source / 'parts.json').read_text())}
mechanical = json.loads((source / 'mechanical.json').read_text())
with tempfile.TemporaryDirectory(prefix='lx0002-netlist-') as temporary:
    netlist_path = Path(temporary) / 'netlist.xml'
    subprocess.run(['/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', str(netlist_path), str(source / 'LX0002.kicad_sch')], check=True)
    schematic = ET.parse(netlist_path)
pad_nets = {}
for net in schematic.findall('.//nets/net'):
    for node in net.findall('node'):
        pad_nets[node.get('ref'), node.get('pin')] = (net.get('name'), 'no_connect' in node.get('pintype', ''))
board = pcb.LoadBoard(str(args.board))
nets = {net.GetNetname(): net for net in board.GetNetInfo().NetsByNetcode().values()}
for name, _ in pad_nets.values():
    if name not in nets:
        net = pcb.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net
for footprint in board.GetFootprints():
    ref = footprint.GetReference()
    if ref in mechanical['mounting_holes']:
        footprint.SetAttributes(footprint.GetAttributes() | pcb.FP_BOARD_ONLY | pcb.FP_EXCLUDE_FROM_BOM | pcb.FP_EXCLUDE_FROM_POS_FILES)
        continue
    part = parts[ref]
    fields = {field.GetName(): field for field in footprint.GetFields()}
    if 'LCSC' not in fields:
        field = pcb.PCB_FIELD(footprint, pcb.FIELD_T_USER, 'LCSC')
        footprint.Add(field)
        fields['LCSC'] = field
    fields['LCSC'].SetText(part['lcsc'])
    fields['LCSC'].SetVisible(False)
    fields['Datasheet'].SetText(part.get('datasheet', ''))
    for pad in footprint.Pads():
        key = (ref, pad.GetNumber())
        if key not in pad_nets:
            assert not pad.GetNetname(), key
            continue
        expected, no_connect = pad_nets[key]
        if pad.GetNumber() in part['pins']:
            assert pad.GetNetname() == expected == part['pins'][pad.GetNumber()], key
        else:
            assert no_connect and (not pad.GetNetname() or pad.GetNetname() == expected), key
            pad.SetNet(nets[expected])
board.BuildConnectivity()
pcb.SaveBoard(str(args.board), board)
print('Synchronized LCSC/datasheet fields, explicit NC nets and board-only mounting-hole metadata')
