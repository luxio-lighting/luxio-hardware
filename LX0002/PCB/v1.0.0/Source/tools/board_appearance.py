"""Record the nominal two-layer stackup and requested black solder mask."""
from pathlib import Path
import json

source = Path(__file__).resolve().parents[1]
project_path = source / 'LX0002.kicad_pro'
project = json.loads(project_path.read_text())
project['net_settings']['classes'] = [entry for entry in project['net_settings']['classes'] if entry['name'] != 'RF50']
project['net_settings']['classes'].append({'name': 'RF50', 'priority': 0, 'clearance': .2, 'track_width': .8, 'via_diameter': .6, 'via_drill': .3, 'diff_pair_width': .3, 'diff_pair_gap': .15, 'diff_pair_via_gap': .25})
project['net_settings']['netclass_patterns'] = [{'netclass': 'RF50', 'pattern': 'RF_50'}]
project_path.write_text(json.dumps(project, indent=2)+'\n')
path = source / 'LX0002.kicad_pcb'
text = path.read_text()
if '(stackup' in text:
    start = text.index('(stackup')
    depth = 0
    for end in range(start, len(text)):
        if text[end] == '(':
            depth += 1
        elif text[end] == ')':
            depth -= 1
            if depth == 0:
                break
    text = text[:start] + text[end+1:]
text = text.replace('\t(setup\n', '''\t(setup
        (stackup
            (layer "F.SilkS" (type "Top Silk Screen") (color "White"))
            (layer "F.Paste" (type "Top Solder Paste"))
            (layer "F.Mask" (type "Top Solder Mask") (color "Black") (thickness 0.01))
            (layer "F.Cu" (type "copper") (thickness 0.035))
            (layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
            (layer "B.Cu" (type "copper") (thickness 0.035))
            (layer "B.Mask" (type "Bottom Solder Mask") (color "Black") (thickness 0.01))
            (layer "B.Paste" (type "Bottom Solder Paste"))
            (layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))
            (copper_finish "OSP")
            (dielectric_constraints yes)
        )
''', 1)
path.write_text(text)
print('Applied nominal1.6mm two-layer stackup,1oz copper, black mask and white silk')
