"""Synchronize routing tables and placement from the reviewed native PCB.

Run only after final native DRC, connectivity and independent geometry review.
Each net belongs to exactly one table, so rebuilding does not duplicate copper.
"""
import argparse
import hashlib
import json
from pathlib import Path
import pcbnew as pcb

source = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board', type=Path, default=source / 'LX0002.kicad_pcb')
args = parser.parse_args()
board = pcb.LoadBoard(str(args.board))
names = ['rf_clock_layout.json', 'power_layout.json', 'usb_layout.json',
         'power_distribution_layout.json', 'manual_layout.json']
old = {name: json.loads((source / name).read_text()) for name in names}
tables = {}
footprints = {footprint.GetReference(): footprint for footprint in board.GetFootprints()}
placements = {}
for ref, footprint in sorted(footprints.items()):
    if ref.startswith('H'):
        continue
    placements[ref] = [pcb.ToMM(footprint.GetPosition().x),
                       pcb.ToMM(footprint.GetPosition().y),
                       footprint.GetOrientationDegrees(),
                       'Bottom' if footprint.IsFlipped() else 'Top']
(source / 'placement.json').write_text(json.dumps(placements, indent=2) + '\n')
claimed = set()
for name in names:
    refs = set(old[name].get('placements', {})) & set(placements)
    if name == 'manual_layout.json':
        refs = set(placements) - claimed
    claimed.update(refs)
    tables[name] = {
        'status': 'Final native routing snapshot; validate with the current Export reports.',
        'coordinate_system': 'KiCad board millimeters: X right, Y down; KiCad rotation degrees.',
        'source_board_sha256': hashlib.sha256(args.board.read_bytes()).hexdigest(),
        'placements': {ref: placements[ref][:3] for ref in sorted(refs)},
        'routes': [], 'vias': [],
    }
for item in board.GetTracks():
    net = item.GetNetname()
    if net in {'RF_50', 'RF_CHIP', 'ANT_TUNE', 'VDD3P3_RF', 'XTAL_N', 'XTAL_P', 'XTAL_P_CRYSTAL'}:
        name = 'rf_clock_layout.json'
    elif net.startswith('BUCK_'):
        name = 'power_layout.json'
    elif net in {'CC1', 'CC2', 'USB_DM', 'USB_DM_CONN', 'USB_DP', 'USB_DP_CONN'}:
        name = 'usb_layout.json'
    elif net in {'GND', '+3V3', '+3V3_ANALOG', 'USB_5V'}:
        name = 'power_distribution_layout.json'
    else:
        name = 'manual_layout.json'
    if isinstance(item, pcb.PCB_VIA):
        assert item.GetDrillValue() >= 300000
        assert item.GetViaType() == pcb.VIATYPE_THROUGH
        tables[name]['vias'].append({
            'net': net,
            'at': [pcb.ToMM(item.GetPosition().x), pcb.ToMM(item.GetPosition().y)],
            'diameter': pcb.ToMM(item.GetWidth(pcb.F_Cu)),
            'drill': pcb.ToMM(item.GetDrillValue()),
        })
    else:
        assert isinstance(item, pcb.PCB_TRACK) and not isinstance(item, pcb.PCB_ARC)
        tables[name]['routes'].append({
            'net': net, 'layer': board.GetLayerName(item.GetLayer()),
            'width_mm': pcb.ToMM(item.GetWidth()),
            'points': [[pcb.ToMM(item.GetStart().x), pcb.ToMM(item.GetStart().y)],
                       [pcb.ToMM(item.GetEnd().x), pcb.ToMM(item.GetEnd().y)]],
        })
rf = tables['rf_clock_layout.json']
rf['antenna_all_layer_copper_keepout_mm'] = old['rf_clock_layout.json']['antenna_all_layer_copper_keepout_mm']
rf['bottom_reference_regions_mm'] = []
for area in sorted((zone for zone in board.Zones() if zone.GetIsRuleArea() and zone.GetZoneName().startswith('RF ground reference ')), key=lambda zone: zone.GetZoneName()):
    outline = area.Outline().Outline(0)
    rf['bottom_reference_regions_mm'].append([[pcb.ToMM(outline.CPoint(index).x), pcb.ToMM(outline.CPoint(index).y)] for index in range(outline.PointCount())])
rf['rf_nominal'] = old['rf_clock_layout.json']['rf_nominal']
for area in board.Zones():
    if area.GetIsRuleArea() and area.GetZoneName() == 'EP outer rim: BOOT only':
        outline = area.Outline().Outline(0)
        rf['ep_outer_rim_boot_allowance_mm'] = [[pcb.ToMM(outline.CPoint(index).x), pcb.ToMM(outline.CPoint(index).y)] for index in range(outline.PointCount())]
rf['ep_corner_rounding_allowances_mm'] = []
for area in sorted((zone for zone in board.Zones() if zone.GetIsRuleArea() and zone.GetZoneName().startswith('EP pour corner rounding ')), key=lambda zone: zone.GetZoneName()):
    outline = area.Outline().Outline(0)
    rf['ep_corner_rounding_allowances_mm'].append([[pcb.ToMM(outline.CPoint(index).x), pcb.ToMM(outline.CPoint(index).y)] for index in range(outline.PointCount())])
rf['notes'] = [
    'RF and crystal signals stay on F.Cu without signal vias. B.Cu remains GND in the three protected regions.',
    'The antenna window excludes copper pours on both layers. Only its manufacturer land pattern and feed transition occupy the top window.',
    'RF_50 uniform sections use 0.80mm width and 0.20mm coplanar gap; component launches are nonuniform.',
    'Nine direct exposed-pad GND vias form a 3x3 grid at offsets -1.4/0/+1.4mm inside the FH4R2 5.7mm exposed pad. Each uses a 0.45mm land and 0.30mm drill, clear of the 16 paste windows.',
    'The exposed-pad solder-mask opening exposes the tops of these nine thermal vias despite their tenting flags. They are not specified as filled or capped.',
    'Static BOOT routing may occupy the outer-right 0.28mm EP rim, with two bottom-corner pour-rounding chamfers bounded to 0.05mm. The full top exposed pad remains GND; the continuous bottom core and nine vias remain protected. Exact whole-EP ground coverage must be at least 95%, with no missing ground outside those explicit bounds.',
    'This bounded EP-rim route is a documented compact two-layer deviation from Espressif complete-chip-ground guidance. Validate boot reliability and radio/power performance on assembled first articles.',
    'All GND and common supply copper is captured in power_distribution_layout.json.',
    'RF calculations and filled-reference sampling do not replace antenna matching and radio validation on assembled first articles.',
]
tables['power_layout.json']['notes'] = [
    'Only BUCK_BST, BUCK_FB, BUCK_FB_LOW and BUCK_SW copper is in this table; common supply and GND copper is in power_distribution_layout.json.',
    'Retain the short top switch-node route and the local input-capacitor return. The feedback divider uses the final lower-left placement.',
]
tables['usb_layout.json']['notes'] = [
    'Two passive 5.1k CC resistors identify a 5V sink. No USB PD controller is fitted.',
    'The USB data routes support the ESP32-S3 full-speed interface. They are not a controlled 90ohm high-speed differential pair.',
    'The ESD branches are approximately 12mm; validate USB enumeration, sustained transfer and ESD immunity on first articles.',
    'The external USB data runs use paired 0.15mm tracks where space permits; the local MCU escapes and connector ESD branches are nonuniform.',
    'J1 has plated shell stakes and uses pin-in-paste assembly; its native footprint attribute is through-hole and the assembly exporter explicitly retains it.',
    'USB_5V and connector GND copper is in power_distribution_layout.json.',
]
tables['power_distribution_layout.json']['notes'] = [
    'This table owns all USB_5V, +3V3, +3V3_ANALOG and GND tracks/vias, including RF stitching and exposed-pad returns.',
    'R106 is a 0ohm top-layer bridge across the crystal traces; its downstream +3V3_ANALOG net supplies U1 pins55/56 and C105 without cutting the bottom ground reference.',
    'USB_5V connects directly from the connector to strip VCC with no power-path diode or firmware switch.',
    'The 3V3 supply crosses congested signal corridors through short top-layer bridges. Some local necks are 0.20mm; this is a documented compact-layout compromise.',
    'Separate measured DC-drop estimates, native DRC and current-path analysis from unperformed transient and thermal qualification.',
]
tables['manual_layout.json']['notes'] = [
    'This table owns the remaining digital signals, VDD_SPI decoupling and both level-shifted LED outputs. FH4R2 flash/PSRAM connections remain internal to the package.',
    'The BOOT/GPIO18 button isolation diodes remain. Optional UART testpads TP11/TP12 are omitted; native USB programming remains.',
    'R30 is 10k in 0402, C25744. Its value is unchanged.',
    'The EN 10k/1uF network sits below USB; validate repeated cold starts, USB hotplug and Wi-Fi transmit with LED load.',
]
for name, table in tables.items():
    table['routes'].sort(key=lambda item: (item['net'], item['layer'], item['points']))
    table['vias'].sort(key=lambda item: (item['net'], item['at']))
    (source / name).write_text(json.dumps(table, indent=2) + '\n')
    print(name, len(table['routes']), 'segments,', len(table['vias']), 'vias')
