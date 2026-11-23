"""Place user-facing silk labels after routing, using KiCad's bundled Python.

Without --apply this checks placement and prints a plan without saving.
With --apply it saves only if every label has a collision-free location.
Run again after moving components or changing exposed vias.
"""
from pathlib import Path
import argparse
import json
import math
import pcbnew as pcb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true', help='Save the checked silkscreen to the board')
parser.add_argument('--board', type=Path, default=Path(__file__).resolve().parents[1] / 'LX0001.kicad_pcb')
args = parser.parse_args()
board = pcb.LoadBoard(str(args.board))

# Coordinates are viewed from the top. Bottom silk is mirrored by KiCad.
# Net labels sit beside terminal rear lands, outside the plastic housings.
labels = [
    dict(text='LUXIO LX0001\nv1.0.0 5-24V', layer=pcb.B_SilkS, angle=0,
         preferred=(22.95, 1.55), region=(18.7, 0.3, 27.2, 2.75), sizes=[(0.8, 0.8)]),
    dict(text='GND', layer=pcb.F_SilkS, angle=0,
         preferred=(13.6, 11.45), region=(12.36, 10.8, 14.9, 11.9), sizes=[(0.8, 0.8)]),
    dict(text='V+', layer=pcb.F_SilkS, angle=0,
         preferred=(13.3, 15.45), region=(12.36, 14.5, 14.9, 15.8), sizes=[(0.8, 0.8)]),
    dict(text='GND', layer=pcb.F_SilkS, angle=0,
         preferred=(46.35, 2.0), region=(44.8, 1.3, 47.65, 2.5), sizes=[(0.8, 0.8)]),
    dict(text='D16', layer=pcb.F_SilkS, angle=0,
         preferred=(46.35, 6.0), region=(44.8, 5.3, 47.65, 6.5), sizes=[(0.8, 0.8)]),
    dict(text='D17', layer=pcb.F_SilkS, angle=0,
         preferred=(46.45, 10.55), region=(44.8, 9.8, 47.65, 11.0), sizes=[(0.8, 0.8)]),
    dict(text='V+', layer=pcb.F_SilkS, angle=0,
         preferred=(46.35, 14.5), region=(44.8, 13.8, 47.65, 15.0), sizes=[(0.8, 0.8)]),
    dict(text='BOOT', layer=pcb.F_SilkS, angle=0,
         preferred=(30.0, 7.6), region=(25.0, 6.9, 34.0, 8.3), sizes=[(0.8, 0.8)]),
    dict(text='IN', layer=pcb.F_SilkS, angle=0,
         preferred=(13.3, 10.8), region=(12.35, 8.5, 16.3, 16.0), sizes=[(0.8, 0.8)]),
    dict(text='OUT', layer=pcb.F_SilkS, angle=0,
         preferred=(54.0, 19.15), region=(45.5, 18.5, 59.7, 19.7), sizes=[(0.8, 0.8)]),
]
managed = {entry['text'] for entry in labels} | {
    'LUXIO LX0001\nv1.0.0\n5-24V IN', 'LUXIO LX0001\nv1.0.0', 'IN 5-24V',
    'FROM ANTENNA EDGE\nIN: GND/5-24V\nOUT: GND/D16/D17/V+',
    'LUXIO\nLX0001\nv1.0.0',
    'FROM SCREW EDGE\nIN: GND / 5-24V\nOUT: GND/D16/D17/V+',
    'TOP VIEW: FROM ANTENNA\nIN: GND / 5-24V\nOUT: GND/D16/D17/V+',
}
previous = [item for item in board.GetDrawings()
            if isinstance(item, pcb.PCB_TEXT)
            and item.GetLayer() in (pcb.F_SilkS, pcb.B_SilkS)
            and item.GetText() in managed]

# Obstacles use conservative rectangles. A courtyard excludes the whole
# assembled part, not just its copper, so silk cannot end up under its body.
obstacles = {pcb.F_SilkS: [], pcb.B_SilkS: []}
for silk in obstacles:
    obstacles[silk].append((10.35, 0.0, 18.65, 3.15, 'antenna edge clearance'))
for footprint in board.GetFootprints():
    side = pcb.F_SilkS if footprint.GetLayer() == pcb.F_Cu else pcb.B_SilkS
    courtyard = pcb.F_CrtYd if side == pcb.F_SilkS else pcb.B_CrtYd
    bounds = []
    for item in footprint.GraphicalItems():
        if item.GetLayer() == courtyard:
            box = item.GetBoundingBox()
            bounds.append((pcb.ToMM(box.GetLeft()), pcb.ToMM(box.GetTop()),
                           pcb.ToMM(box.GetRight()), pcb.ToMM(box.GetBottom())))
    if footprint.GetReference() in ('J2', 'J3', 'J4'):
        # Rear terminal lands extend beyond the plastic body. Permit readable
        # net labels there while still excluding the body plus every pad.
        x,y=pcb.ToMM(footprint.GetPosition().x),pcb.ToMM(footprint.GetPosition().y)
        bounds=[(x-5.75,y-3.95,x+5.75,y+3.95)]
    if not bounds:
        box = footprint.GetBoundingBox(False, False)
        bounds.append((pcb.ToMM(box.GetLeft()), pcb.ToMM(box.GetTop()),
                       pcb.ToMM(box.GetRight()), pcb.ToMM(box.GetBottom())))
    obstacles[side].append((min(b[0] for b in bounds) - 0.10,
                            min(b[1] for b in bounds) - 0.10,
                            max(b[2] for b in bounds) + 0.10,
                            max(b[3] for b in bounds) + 0.10,
                            footprint.GetReference() + ' courtyard'))
    for pad in footprint.Pads():
        box = pad.GetBoundingBox()
        for silk, mask in ((pcb.F_SilkS, pcb.F_Mask), (pcb.B_SilkS, pcb.B_Mask)):
            if pad.IsOnLayer(mask) or pad.GetDrillSize().x or pad.GetDrillSize().y:
                obstacles[silk].append((pcb.ToMM(box.GetLeft()) - 0.25,
                                         pcb.ToMM(box.GetTop()) - 0.25,
                                         pcb.ToMM(box.GetRight()) + 0.25,
                                         pcb.ToMM(box.GetBottom()) + 0.25,
                                         footprint.GetReference() + '/' + pad.GetNumber()))
    if footprint.GetReference().startswith('H'):
        x, y = pcb.ToMM(footprint.GetPosition().x), pcb.ToMM(footprint.GetPosition().y)
        for silk in obstacles:
            obstacles[silk].append((x - 2.45, y - 2.45, x + 2.45, y + 2.45, 'screw clearance'))
    for item in list(footprint.GraphicalItems()) + [footprint.Reference(), footprint.Value()]:
        if item.GetLayer() in obstacles and (not hasattr(item, 'IsVisible') or item.IsVisible()):
            box = item.GetBoundingBox()
            obstacles[item.GetLayer()].append((pcb.ToMM(box.GetLeft()) - 0.15,
                                               pcb.ToMM(box.GetTop()) - 0.15,
                                               pcb.ToMM(box.GetRight()) + 0.15,
                                               pcb.ToMM(box.GetBottom()) + 0.15, 'existing footprint silk'))
for item in board.GetDrawings():
    if item.GetLayer() not in obstacles:
        continue
    if isinstance(item, pcb.PCB_TEXT) and item.GetText() in managed:
        continue
    box = item.GetBoundingBox()
    obstacles[item.GetLayer()].append((pcb.ToMM(box.GetLeft()) - 0.15,
                                       pcb.ToMM(box.GetTop()) - 0.15,
                                       pcb.ToMM(box.GetRight()) + 0.15,
                                       pcb.ToMM(box.GetBottom()) + 0.15, 'existing board silk'))
for item in board.GetTracks():
    if not isinstance(item, pcb.PCB_VIA):
        continue
    box = item.GetBoundingBox()
    for silk in obstacles:
        if item.IsTented(pcb.F_Cu if silk == pcb.F_SilkS else pcb.B_Cu):
            continue
        obstacles[silk].append((pcb.ToMM(box.GetLeft()) - 0.20,
                                pcb.ToMM(box.GetTop()) - 0.20,
                                pcb.ToMM(box.GetRight()) + 0.20,
                                pcb.ToMM(box.GetBottom()) + 0.20, 'via'))

planned, failed, new_items = [], [], []
for entry in labels:
    x0, y0, x1, y1 = entry['region']
    candidates = [(entry['preferred'][0], entry['preferred'][1])]
    candidates += [(round(x0 + i * 0.20, 3), round(y0 + j * 0.20, 3))
                   for i in range(math.floor((x1 - x0) / 0.20) + 1)
                   for j in range(math.floor((y1 - y0) / 0.20) + 1)]
    candidates.sort(key=lambda xy: (xy[0] - entry['preferred'][0]) ** 2 + (xy[1] - entry['preferred'][1]) ** 2)
    text = pcb.PCB_TEXT(board)
    text.SetText(entry['text'])
    text.SetLayer(entry['layer'])
    text.SetMirrored(entry['layer'] == pcb.B_SilkS)
    text.SetTextAngle(pcb.EDA_ANGLE(entry['angle'], pcb.DEGREES_T))
    text.SetTextThickness(pcb.FromMM(0.15))
    text.SetHorizJustify(pcb.GR_TEXT_H_ALIGN_CENTER)
    text.SetVertJustify(pcb.GR_TEXT_V_ALIGN_CENTER)
    placed = False
    for width, height in entry['sizes']:
        text.SetTextSize(pcb.VECTOR2I(pcb.FromMM(width), pcb.FromMM(height)))
        for x, y in candidates:
            text.SetPosition(pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y)))
            # KiCad's text layout box includes large line-spacing margins.
            # Use the actual rendered strokes for safe, useful placement.
            box = text.GetEffectiveTextShape().BBox()
            rect = (pcb.ToMM(box.GetLeft()), pcb.ToMM(box.GetTop()),
                    pcb.ToMM(box.GetRight()), pcb.ToMM(box.GetBottom()))
            if rect[0] < max(0.3, x0) or rect[1] < max(0.3, y0) or rect[2] > min(59.7, x1) or rect[3] > min(19.7, y1):
                continue
            if any(rect[0] < obstacle[2] and rect[2] > obstacle[0]
                   and rect[1] < obstacle[3] and rect[3] > obstacle[1]
                   for obstacle in obstacles[entry['layer']]):
                continue
            obstacles[entry['layer']].append((rect[0] - 0.15, rect[1] - 0.15, rect[2] + 0.15, rect[3] + 0.15, 'new silk'))
            planned.append(dict(text=entry['text'], layer=board.GetLayerName(entry['layer']),
                                position=[x, y], angle=entry['angle'], size=[width, height], bounds=list(rect)))
            new_items.append(text)
            placed = True
            break
        if placed:
            break
    if not placed:
        failed.append(entry['text'])

print(json.dumps(dict(applied=bool(args.apply and not failed), planned=planned, failed=failed), indent=2))
if failed:
    raise SystemExit('No board saved: a required silkscreen label has no clear location. Review candidate regions after routing.')
if args.apply:
    for item in previous:
        board.Remove(item)
    for item in new_items:
        board.Add(item)
    pcb.SaveBoard(str(args.board), board)
