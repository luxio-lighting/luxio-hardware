"""Apply the managed pin and product labels without modifying copper."""
import argparse
import gc
import json
from pathlib import Path
import pcbnew as pcb

gc.disable()
source = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board', type=Path, default=source / 'LX0002.kicad_pcb')
args = parser.parse_args()
labels = json.loads((source / 'silkscreen_layout.json').read_text())
board = pcb.LoadBoard(str(args.board))
old = list(board.GetDrawings())
managed = {(entry['text'], pcb.F_SilkS if entry['layer'] == 'F.SilkS' else pcb.B_SilkS) for entry in labels}
for item in old:
    if isinstance(item, pcb.PCB_TEXT) and (item.GetText(), item.GetLayer()) in managed:
        board.Remove(item)
for entry in labels:
    text = pcb.PCB_TEXT(board)
    text.SetText(entry['text'])
    text.SetPosition(pcb.VECTOR2I(round(entry['at'][0] * 1e6), round(entry['at'][1] * 1e6)))
    text.SetTextSize(pcb.VECTOR2I(round(entry['size'] * 1e6), round(entry['size'] * 1e6)))
    text.SetTextThickness(round(entry['thickness'] * 1e6))
    text.SetTextAngle(pcb.EDA_ANGLE(entry.get('rotation', 0), pcb.DEGREES_T))
    text.SetLayer(pcb.F_SilkS if entry['layer'] == 'F.SilkS' else pcb.B_SilkS)
    text.SetMirrored(entry['layer'] == 'B.SilkS')
    board.Add(text)
pcb.SaveBoard(str(args.board), board)
print('Applied', len(labels), 'managed silkscreen labels')
