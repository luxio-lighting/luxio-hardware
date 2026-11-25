"""Extract actual footprint courtyard extents for placement review."""
from pathlib import Path
import json
import pcbnew as pcb

source = Path(__file__).resolve().parents[1]
board = pcb.LoadBoard(str(source / 'LX0002.kicad_pcb'))
geometry = []
for footprint in board.GetFootprints():
    points = []
    for graphic in footprint.GraphicalItems():
        if graphic.GetLayer() in [pcb.F_CrtYd, pcb.B_CrtYd]:
            bounds = graphic.GetBoundingBox()
            points += [(pcb.ToMM(bounds.GetLeft()), pcb.ToMM(bounds.GetTop())), (pcb.ToMM(bounds.GetRight()), pcb.ToMM(bounds.GetBottom()))]
    if not points:
        bounds = footprint.GetBoundingBox(False, False)
        points = [(pcb.ToMM(bounds.GetLeft()), pcb.ToMM(bounds.GetTop())), (pcb.ToMM(bounds.GetRight()), pcb.ToMM(bounds.GetBottom()))]
    x, y = pcb.ToMM(footprint.GetPosition().x), pcb.ToMM(footprint.GetPosition().y)
    pads = [{'number': pad.GetNumber(), 'net': pad.GetNetname(), 'x': pcb.ToMM(pad.GetPosition().x)-x, 'y': pcb.ToMM(pad.GetPosition().y)-y} for pad in footprint.Pads()]
    geometry.append({'ref': footprint.GetReference(), 'x': x, 'y': y, 'rot': footprint.GetOrientationDegrees(), 'side': 'Top' if footprint.GetLayer() == pcb.F_Cu else 'Bottom', 'box': [min(p[0] for p in points)-x, min(p[1] for p in points)-y, max(p[0] for p in points)-x, max(p[1] for p in points)-y], 'pads': pads})
(source / 'placement_geometry.json').write_text(json.dumps(geometry, indent=2)+'\n')
print('Extracted courtyard geometry for', len(geometry), 'footprints')
