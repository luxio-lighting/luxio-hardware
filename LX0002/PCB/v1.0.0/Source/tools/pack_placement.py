"""Pack unfrozen supporting components around the reviewed functional blocks.

This is placement assistance only. Native KiCad DRC is authoritative.
"""
from pathlib import Path
import argparse
import json
import math
import random

parser = argparse.ArgumentParser()
parser.add_argument('--seed', type=int, default=2511)
parser.add_argument('--steps', type=int, default=400000)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source = Path(__file__).resolve().parents[1]
geometry = json.loads((source / 'placement_geometry.json').read_text())
mechanical = json.loads((source / 'mechanical.json').read_text())
length, width, _ = mechanical['size_mm']
placement = json.loads((source / 'placement.json').read_text())
fixed = {'U1', 'U10', 'SW1', 'J1', 'J3', 'J4', 'H1', 'H2', 'C103'}
for name in ['rf_clock_layout.json', 'power_layout.json', 'usb_layout.json', 'power_distribution_layout.json', 'manual_layout.json']:
    if (source / name).exists():
        data = json.loads((source / name).read_text())
        fixed.update(data.get('placements', {}))
items = [item for item in geometry if item['side'] == 'Top']
for item in items:
    # The extracted graphical bounds include half of the courtyard stroke.
    # KiCad collision checks use the enclosed area rather than that stroke.
    item['box'] = [item['box'][0]+.025, item['box'][1]+.025, item['box'][2]-.025, item['box'][3]-.025]
antenna = mechanical['antenna_clearance']
obstacles = [{'ref': 'ANT_GUARD', 'x': 0, 'y': 0, 'box': [min(v[0] for v in antenna), min(v[1] for v in antenna), max(v[0] for v in antenna), max(v[1] for v in antenna)]}]
for name in ['rf_clock_layout.json', 'power_layout.json', 'usb_layout.json', 'power_distribution_layout.json', 'manual_layout.json']:
    if not (source / name).exists():
        continue
    data = json.loads((source / name).read_text())
    for route in data.get('routes', []):
        if route.get('layer', 'F.Cu') != 'F.Cu':
            continue
        radius = route.get('width_mm', route.get('width'))/2 + .15
        for a, b in zip(route['points'], route['points'][1:]):
            obstacles.append({'ref': 'ROUTE', 'x': 0, 'y': 0, 'box': [min(a[0], b[0])-radius, min(a[1], b[1])-radius, max(a[0], b[0])+radius, max(a[1], b[1])+radius]})
    for point in data.get('ground_vias_mm', []) + [v.get('at', v.get('xy')) for v in data.get('vias', []) + data.get('signal_vias', [])]:
        obstacles.append({'ref': 'ROUTE', 'x': point[0], 'y': point[1], 'box': [-.35, -.35, .35, .35]})
for item in items:
    item['tx'], item['ty'] = item['x'], item['y']
    if item['ref'].startswith('H'):
        item['circle'] = 2.45
move = [item for item in items if item['ref'] not in fixed]
random.seed(args.seed)

# One cost routine is shared by incremental moves and the final report.
def cost(item, detail=False):
    x0, y0, x1, y1 = [item['x'] + item['box'][0], item['y'] + item['box'][1], item['x'] + item['box'][2], item['y'] + item['box'][3]]
    penalty = 0
    conflicts = []
    if item['ref'] not in {'J1', 'H1', 'H2', 'J3', 'J4'}:
        penalty += 5000 * (max(0, .05-x0)**2 + max(0, .05-y0)**2 + max(0, x1-length+.05)**2 + max(0, y1-width+.05)**2)
    target_weight = 3.0 if item['ref'] in {'C100', 'C101', 'C102', 'C104', 'C105', 'C106', 'C107', 'C108', 'C109', 'C110', 'C111', 'R105'} else .15
    penalty += target_weight * ((item['x']-item['tx'])**2 + (item['y']-item['ty'])**2)
    for other in items + obstacles:
        if other is item or other['ref'] == 'ANT_GUARD' and item['ref'] in {'ANT1', 'L104'}:
            continue
        if other['ref'] == 'ROUTE' and item['ref'] in fixed:
            continue
        if other.get('circle'):
            distance = math.hypot(max(x0-other['x'], 0, other['x']-x1), max(y0-other['y'], 0, other['y']-y1))
            overlap = max(0, other['circle']-distance)
            if overlap:
                penalty += 10000*overlap
                conflicts.append(other['ref'])
            continue
        dx = min(x1, other['x']+other['box'][2])-max(x0, other['x']+other['box'][0])
        dy = min(y1, other['y']+other['box'][3])-max(y0, other['y']+other['box'][1])
        if dx > 0 and dy > 0:
            penalty += 5000*dx*dy + 2000*min(dx, dy)
            conflicts.append(other['ref'])
    return (penalty, conflicts) if detail else penalty

best_cost = float('inf')
best = None
for step in range(args.steps):
    item = random.choice(move)
    old = (item['x'], item['y'], item['rot'], item['box'][:])
    before = cost(item)
    fraction = (step % 100000) / 100000
    temperature = max(.05, 40*(1-fraction)**2)
    scale = .12 if step % 5 else 1.2
    if step % 20 == 0 and item['ref'][0] in 'RC':
        item['rot'] = (item['rot'] + 90) % 360
        x0, y0, x1, y1 = item['box']
        item['box'] = [y0, -x1, y1, -x0]
    else:
        item['x'] = round(item['x'] + random.gauss(0, scale), 2)
        item['y'] = round(item['y'] + random.gauss(0, scale), 2)
    after = cost(item)
    if after > before and random.random() > math.exp(min(0, (before-after)/temperature)):
        item['x'], item['y'], item['rot'], item['box'] = old
    if step % 10000 == 0 or step == args.steps-1:
        total = sum(cost(item) for item in items)
        if total < best_cost:
            best_cost = total
            best = [(item['x'], item['y'], item['rot'], item['box'][:]) for item in items]
        if step % 100000 == 0:
            print(step, round(total, 2), flush=True)
for item, saved in zip(items, best):
    item['x'], item['y'], item['rot'], item['box'] = saved
    if item['ref'] not in fixed:
        placement[item['ref']] = [round(item['x'], 3), round(item['y'], 3), item['rot'], 'Top']
conflicts = {item['ref']: cost(item, True)[1] for item in items if cost(item, True)[1]}
output = args.output or source / 'placement.json'
output.write_text(json.dumps(placement, indent=2)+'\n')
output.with_suffix('.packing.json').write_text(json.dumps({'seed': args.seed, 'cost': best_cost, 'courtyard_conflicts': conflicts}, indent=2)+'\n')
print('Saved', output, 'cost', round(best_cost, 2), 'conflicted items', len(conflicts), flush=True)
