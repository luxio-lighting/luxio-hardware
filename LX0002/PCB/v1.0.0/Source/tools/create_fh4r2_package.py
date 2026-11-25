"""Create the FH4R2-specific land pattern and nominal mechanical model.

Run in the CadQuery environment. Espressif ESP32-S3 datasheet v2.2 Figure 7-2
specifies a 5.7mm exposed pad for FH4R2, unlike the 4mm FN8 exposed pad.
The perimeter land pattern is retained from KiCad's 0.4mm-pitch QFN library.
The stencil windows leave space for nine 0.30mm ground drills; routing owns vias.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import cadquery as cq

source = Path(__file__).resolve().parents[1]
name = 'ESP32_S3FH4R2_QFN56_7x7_EP5p7'
original = source / 'libraries/Package_DFN_QFN.pretty/QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm.kicad_mod'
target = source / 'libraries/Core.pretty' / (name + '.kicad_mod')
text = original.read_text().replace('QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm', name)
text = re.sub(r'\(descr "[^"]*"\)', '(descr "ESP32-S3FH4R2; QFN56 7x7mm pitch0.4mm EP5.7mm; Espressif ESP32-S3 datasheet v2.2 Figure7-2 https://documentation.espressif.com/esp32_s3_datasheet_en.pdf")', text, count=1)
text = re.sub(r'\t\(pad "" smd roundrect\n.*?\n\t\)\n', '', text, flags=re.S)
assert '(size 4 4)' in text
text = text.replace('(size 4 4)', '(size 5.7 5.7)')
windows = []
for x in [-2.1, -.7, .7, 2.1]:
    for y in [-2.1, -.7, .7, 2.1]:
        windows.append(f'\t(pad "" smd roundrect (at {x:g} {y:g}) (size 1.02 1.02) (layers "F.Paste") (roundrect_rratio {0.1/1.02:.9f}))\n')
text = text.replace('\t(pad "1" smd roundrect', ''.join(windows) + '\t(pad "1" smd roundrect', 1)
text = text.replace('${KICAD10_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/' + name + '.step', '${KIPRJMOD}/libraries/models/' + name + '.step')
target.write_text(text)

assembly = cq.Assembly(name=name)
body = cq.Workplane('XY').box(7, 7, .65).translate((0, 0, .525))
mark = cq.Workplane('XY').workplane(offset=.845).center(-2.9, 2.9).circle(.15).extrude(.005)
assembly.add(body.cut(mark), name='mold', color=cq.Color(.075, .075, .075))
assembly.add(mark, name='pin1_mark', color=cq.Color(.28, .28, .28))
assembly.add(cq.Workplane('XY').box(5.7, 5.7, .203).translate((0, 0, .1015)), name='EP57', color=cq.Color(.68, .68, .70))
for index in range(14):
    along = -2.6 + .4*index
    for pin, x, y, dx, dy in [
        (1+index, -3.3, -along, .4, .2),
        (15+index, along, -3.3, .2, .4),
        (29+index, 3.3, along, .4, .2),
        (43+index, -along, 3.3, .2, .4),
    ]:
        assembly.add(cq.Workplane('XY').box(dx, dy, .203).translate((x, y, .1015)), name='pin' + str(pin), color=cq.Color(.68, .68, .70))
model = source / 'libraries/models' / (name + '.step')
assembly.export(str(model))
loaded = cq.importers.importStep(str(model)).val()
assert len(loaded.Solids()) == 59 and all(solid.isValid() for solid in loaded.Solids())
box = loaded.BoundingBox()
assert abs(box.xlen-7) < .001 and abs(box.ylen-7) < .001 and abs(box.zlen-.85) < .001
paste_area = 16*(1.02**2-(4-math.pi)*.1**2)
record = {
    'source': 'Espressif ESP32-S3 datasheet v2.2 Figure7-2, page78',
    'source_url': 'https://documentation.espressif.com/esp32_s3_datasheet_en.pdf',
    'scope': 'Nominal package model and project land pattern; not a supplier STEP or an assembly-process qualification',
    'package_mm': [7, 7, .85], 'package_height_range_mm': [.8, .9],
    'exposed_pad_mm': [5.7, 5.7], 'exposed_pad_range_mm': [5.6, 5.8],
    'pitch_mm': .4, 'lead_mm': [.4, .2],
    'perimeter_land_mm': [.8, .2], 'perimeter_pad_center_offset_mm': 3.45,
    'ep_to_perimeter_land_gap_mm': .2,
    'paste_windows': {'count': 16, 'size_mm': [1.02, 1.02], 'radius_mm': .1, 'centers_each_axis_mm': [-2.1, -.7, .7, 2.1]},
    'ep_paste_coverage_percent': 100*paste_area/5.7**2,
    'ground_via_grid_offsets_mm': [-1.4, 0, 1.4],
    'via_diameter_mm': .45, 'via_drill_mm': .3,
    'bounding_rectangle_min_drill_to_paste_mm': math.sqrt(2)*(.7-.51)-.15,
    'model_solids': len(loaded.Solids()),
    'sha256': {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [target, model]},
}
(source / 'libraries/models/FH4R2-package-verification.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
