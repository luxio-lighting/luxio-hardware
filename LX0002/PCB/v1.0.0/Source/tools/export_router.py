"""Export a signal-routing DSN while keeping manual RF, USB and power copper fixed."""
from pathlib import Path
import argparse
import json
import re
import pcbnew as pcb

parser = argparse.ArgumentParser()
parser.add_argument('--board', type=Path)
parser.add_argument('--output', type=Path, default=Path('/tmp/lx0002.dsn'))
args = parser.parse_args()
source = Path(__file__).resolve().parents[1]
board = pcb.LoadBoard(str(args.board or source / 'LX0002.kicad_pcb'))
mechanical = json.loads((source / 'mechanical.json').read_text())
default = board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
default.SetViaDiameter(pcb.FromMM(.5))
default.SetViaDrill(pcb.FromMM(.3))
default.SetTrackWidth(pcb.FromMM(.15))
default.SetClearance(pcb.FromMM(.15))
# Temporary router-only via keepouts prevent uncapped routing drills in paste.
# The native board is never saved with these additional obstacles. Rectangle
# bounds conservatively cover rotated/rounded paste pads; final verification
# uses the actual aperture shapes and minimum 0.10mm drill-to-paste gap.
for footprint in board.GetFootprints():
    for pad in footprint.Pads():
        if not pad.IsOnLayer(pcb.F_Paste):
            continue
        margin = pad.GetSolderPasteMargin(pcb.F_Paste)
        clone = pcb.PAD(pad)
        size = pad.GetSize(pcb.F_Paste)
        clone.SetSize(pcb.F_Paste, pcb.VECTOR2I(size.x+2*margin.x, size.y+2*margin.y))
        shape = clone.GetEffectiveShape(pcb.F_Paste)
        bounds = shape.BBox()
        area = pcb.ZONE(board)
        area.SetIsRuleArea(True)
        area.SetLayer(pcb.F_Cu)
        area.SetDoNotAllowTracks(False)
        area.SetDoNotAllowVias(True)
        area.SetDoNotAllowPads(False)
        area.SetDoNotAllowZoneFills(False)
        area.SetDoNotAllowFootprints(False)
        area.SetZoneName('PASTE_VIA_' + footprint.GetReference() + '_' + pad.GetNumber())
        polygon = area.Outline()
        polygon.NewOutline()
        for x, y in [(bounds.GetLeft(), bounds.GetTop()), (bounds.GetRight(), bounds.GetTop()), (bounds.GetRight(), bounds.GetBottom()), (bounds.GetLeft(), bounds.GetBottom())]:
            polygon.Append(x, y)
        board.Add(area)
assert pcb.ExportSpecctraDSN(board, str(args.output))
text = args.output.read_text()
start = text.index('    (class kicad_default')
end = text.index('\n  )\n  (wiring', start)
nets = {net.GetNetname() for net in board.GetNetInfo().NetsByNetcode().values() if net.GetNetname()}
critical = {'GND', 'USB_5V', 'RF_CHIP', 'RF_50', 'ANT_TUNE', 'XTAL_P', 'XTAL_P_CRYSTAL', 'XTAL_N', 'BUCK_BST', 'BUCK_SW', 'BUCK_FB', 'BUCK_FB_LOW', 'USB_DM', 'USB_DP', 'USB_DM_CONN', 'USB_DP_CONN'} & nets
power = {'+3V3', 'VDD_SPI', 'VDD3P3_RF'} & nets
classes = []
via_name = re.search(r'\(via\s+"([^"]+)"', text).group(1)
for name, members, width in [('signals', nets-critical-power, 150), ('logic_power', power, 300), ('critical', critical, 150)]:
    classes.append('    (class ' + name + ' ' + ' '.join('"' + net + '"' for net in sorted(members)) + ' (circuit (use_via "' + via_name + '")) (rule (width ' + str(width) + ') (clearance 150)))')
text = text[:start] + '\n'.join(classes) + text[end:]
# KiCad DSN contains raw zone outlines, not resolved filled copper. They would
# incorrectly short/collapse islands in the router, so remove only those planes.
while '\n    (plane ' in text:
    start = text.index('\n    (plane ')
    end = start + 1
    depth = 0
    quoted = escaped = False
    while end < len(text):
        character = text[end]
        if quoted:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character == '(':
            depth += 1
        elif character == ')':
            depth -= 1
            if depth == 0:
                break
        end += 1
    text = text[:start] + text[end+1:]
length, width, _ = mechanical['size_mm']
lx, wy = round(length*1000), round(width*1000)
boundary = f'(path pcb 0  {lx} -{wy}  0 -{wy}  0 0  {lx} 0  {lx} -{wy})'
inset = f'(path pcb 0  {lx-150} -{wy-150}  150 -{wy-150}  150 -150  {lx-150} -150  {lx-150} -{wy-150})'
assert boundary in text, 'Review DSN boundary ordering before applying edge clearance'
text = text.replace(boundary, inset)
position = text.index('\n  )\n  (placement')
antenna = mechanical['antenna_clearance']
x0, x1 = min(v[0] for v in antenna)*1000, max(v[0] for v in antenna)*1000
y0, y1 = -max(v[1] for v in antenna)*1000, -min(v[1] for v in antenna)*1000
text = text[:position] + f'\n    (keepout LX0002_ANTENNA_ROUTER_ONLY (rect F.Cu {x0:g} {y0:g} {x1:g} {y1:g}))' + text[position:]
args.output.write_text(text)
print('Exported', len(nets), 'nets; ignore critical class when routing. Via:', via_name)
