"""Verify exported connectivity and independent drill/paste geometry without changing CAD.

The geometric check tests physical drill shapes against F.Paste/B.Paste
apertures irrespective of net. It therefore catches same-net via-in-pad and
paste-only exposed-pad windows. No via-in-paste exceptions are permitted.
"""
import argparse
from pathlib import Path
import datetime
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import pcbnew as p

root = Path(__file__).resolve().parents[2]
src = root / 'Source'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board', type=Path, default=src / 'LX0002.kicad_pcb')
parser.add_argument('--reports-dir', type=Path, default=root / 'Export')
parser.add_argument('--geometry-only', action='store_true')
parser.add_argument('--netlist', type=Path, default=root / 'Export/netlist.xml')
parser.add_argument('--minimum-via-paste-clearance-mm', type=float, default=0.10)
args = parser.parse_args()
assert args.minimum_via_paste_clearance_mm >= 0
out = args.reports_dir
out.mkdir(parents=True, exist_ok=True)
board_bytes = args.board.read_bytes()
mechanical = json.loads((src / 'mechanical.json').read_text())
length, width, thickness = mechanical['size_mm']
usb_x, usb_y = mechanical['usb']['center']
assert mechanical['usb']['rotation_deg'] == -90
b = p.LoadBoard(str(args.board))
geometry_errors = []
apertures = []
keep = []
for footprint in b.GetFootprints():
    for pad in footprint.Pads():
        for layer in [p.F_Paste, p.B_Paste]:
            if not pad.IsOnLayer(layer):
                continue
            margin = pad.GetSolderPasteMargin(layer)
            clone = p.PAD(pad)
            keep.append(clone)
            shape_type = pad.GetShape(layer)
            old_size = pad.GetSize(layer)
            new_size = p.VECTOR2I(old_size.x + 2 * margin.x, old_size.y + 2 * margin.y)
            if new_size.x <= 0 or new_size.y <= 0:
                continue
            # Follow the published KiCad 10 paste-size rules on a detached pad.
            # Do not mistake GetEffectiveShape(F.Paste) for an expanded aperture:
            # that API alone returns the unadjusted pad geometry.
            if margin.x or margin.y:
                if shape_type in [p.PAD_SHAPE_CIRCLE, p.PAD_SHAPE_OVAL, p.PAD_SHAPE_RECT, p.PAD_SHAPE_ROUNDRECT]:
                    radius = pad.GetRoundRectCornerRadius(layer) if shape_type == p.PAD_SHAPE_ROUNDRECT else 0
                    ratio = pad.GetRoundRectRadiusRatio(layer) if shape_type == p.PAD_SHAPE_ROUNDRECT else 0
                    clone.SetSize(layer, new_size)
                    if shape_type == p.PAD_SHAPE_RECT and margin.x > 0:
                        clone.SetShape(layer, p.PAD_SHAPE_ROUNDRECT)
                        clone.SetRoundRectCornerRadius(layer, margin.x)
                    elif shape_type == p.PAD_SHAPE_ROUNDRECT:
                        if margin.x == margin.y:
                            clone.SetRoundRectCornerRadius(layer, max(0, radius + margin.x))
                        else:
                            clone.SetRoundRectRadiusRatio(layer, ratio)
                else:
                    geometry_errors.append({'type': 'unsupported_paste_margin_geometry', 'reference': footprint.GetReference(), 'pad': pad.GetNumber(), 'pad_uuid': pad.m_Uuid.AsString(), 'layer': p.LayerName(layer), 'shape': int(shape_type), 'margin_mm': [p.ToMM(margin.x), p.ToMM(margin.y)]})
                    continue
            shape = clone.GetEffectiveShape(layer)
            keep.append(shape)
            apertures.append({'shape': shape, 'uuid': pad.m_Uuid.AsString(), 'reference': footprint.GetReference(), 'number': pad.GetNumber(), 'net': pad.GetNetname(), 'layer': layer, 'attribute': int(pad.GetAttribute()), 'margin_mm': [p.ToMM(margin.x), p.ToMM(margin.y)]})
    for drawing in footprint.GraphicalItems():
        if drawing.GetLayer() in [p.F_Paste, p.B_Paste]:
            if not isinstance(drawing, p.PCB_SHAPE):
                geometry_errors.append({'type': 'unsupported_paste_graphic', 'uuid': drawing.m_Uuid.AsString(), 'reference': footprint.GetReference()})
                continue
            shape = drawing.GetEffectiveShape()
            keep.append(shape)
            apertures.append({'shape': shape, 'uuid': drawing.m_Uuid.AsString(), 'reference': footprint.GetReference(), 'number': '', 'net': '', 'layer': drawing.GetLayer(), 'attribute': None, 'margin_mm': [0, 0]})
for drawing in b.GetDrawings():
    if drawing.GetLayer() in [p.F_Paste, p.B_Paste]:
        if not isinstance(drawing, p.PCB_SHAPE):
            geometry_errors.append({'type': 'unsupported_paste_graphic', 'uuid': drawing.m_Uuid.AsString(), 'reference': ''})
            continue
        shape = drawing.GetEffectiveShape()
        keep.append(shape)
        apertures.append({'shape': shape, 'uuid': drawing.m_Uuid.AsString(), 'reference': '', 'number': '', 'net': '', 'layer': drawing.GetLayer(), 'attribute': None, 'margin_mm': [0, 0]})
for zone in b.Zones():
    if zone.IsOnLayer(p.F_Paste) or zone.IsOnLayer(p.B_Paste):
        geometry_errors.append({'type': 'unsupported_paste_zone', 'uuid': zone.m_Uuid.AsString()})
holes = []
for track in b.GetTracks():
    if isinstance(track, p.PCB_VIA):
        holes.append({'item': track, 'kind': 'via', 'reference': '', 'number': '', 'hole_mm': [p.ToMM(track.GetDrillValue()), p.ToMM(track.GetDrillValue())]})
for footprint in b.GetFootprints():
    for pad in footprint.Pads():
        if pad.GetDrillSize().x > 0:
            holes.append({'item': pad, 'kind': 'plated_pad_hole' if pad.GetAttribute() == p.PAD_ATTRIB_PTH else 'unplated_pad_hole', 'reference': footprint.GetReference(), 'number': pad.GetNumber(), 'footprint_value': footprint.GetValue(), 'footprint_name': footprint.GetFPID().GetLibItemName(), 'hole_mm': [p.ToMM(pad.GetDrillSize().x), p.ToMM(pad.GetDrillSize().y)]})
reviewed_pin_in_paste = []
comparisons = 0
for hole in holes:
    item = hole['item']
    hole_shape = item.GetEffectiveHoleShape()
    for aperture in apertures:
        # This project uses through drills. Check the actual
        # drilled item's copper-layer span before comparing the opposite paste.
        copper_layer = p.F_Cu if aperture['layer'] == p.F_Paste else p.B_Cu
        if hole['kind'] == 'via' and not item.IsOnLayer(copper_layer):
            continue
        comparisons += 1
        clearance_iu = max(0, p.FromMM(args.minimum_via_paste_clearance_mm) - 1) if hole['kind'] == 'via' else 0
        if not hole_shape.Collide(aperture['shape'], clearance_iu):
            continue
        gap_iu = 0
        if clearance_iu and not hole_shape.Collide(aperture['shape'], 0):
            low_iu, high_iu = 0, clearance_iu
            while high_iu - low_iu > 1:
                middle_iu = (low_iu + high_iu) // 2
                if hole_shape.Collide(aperture['shape'], middle_iu):
                    high_iu = middle_iu
                else:
                    low_iu = middle_iu
            gap_iu = high_iu
        point = [p.ToMM(item.GetPosition().x), p.ToMM(item.GetPosition().y)]
        detail = {'type': 'via_paste_clearance_below_minimum' if hole['kind'] == 'via' and clearance_iu else 'drill_overlaps_paste_aperture', 'required_clearance_mm': args.minimum_via_paste_clearance_mm if hole['kind'] == 'via' else 0, 'measured_gap_mm': p.ToMM(gap_iu), 'drill_kind': hole['kind'], 'drill_uuid': item.m_Uuid.AsString(), 'drill_net': item.GetNetname(), 'drill_reference': hole['reference'], 'drill_pad': hole['number'], 'drill_position_mm': point, 'drill_size_mm': hole['hole_mm'], 'aperture_uuid': aperture['uuid'], 'aperture_reference': aperture['reference'], 'aperture_pad': aperture['number'], 'aperture_net': aperture['net'], 'paste_layer': p.LayerName(aperture['layer']), 'same_net': bool(item.GetNetname()) and item.GetNetname() == aperture['net']}
        # The four connector stakes are plated slotted component pins, not vias.
        # Their own F.Paste openings implement the documented DEALON pin-in-paste
        # mounting. This cannot waive a via or a hole crossing another aperture.
        expected_slots = {(round(usb_x - 1.075, 5), round(usb_y - 4.325, 5)): [0.8, 1.4], (round(usb_x - 1.075, 5), round(usb_y + 4.325, 5)): [0.8, 1.4], (round(usb_x + 3.125, 5), round(usb_y - 4.325, 5)): [0.8, 1.6], (round(usb_x + 3.125, 5), round(usb_y + 4.325, 5)): [0.8, 1.6]}
        own_connector_pip = hole['kind'] == 'plated_pad_hole' and hole['reference'] == 'J1' and hole['number'] == 'SH' and aperture['uuid'] == item.m_Uuid.AsString() and aperture['layer'] == p.F_Paste
        if own_connector_pip:
            position_key = tuple(round(value, 5) for value in point)
            if hole['footprint_value'] == 'USB-TYPE-C-018' and hole['footprint_name'] == 'USB_C_DEALON_USB_TYPE_C_018' and b.GetDesignSettings().GetBoardThickness() == p.FromMM(1.6) and position_key in expected_slots and hole['hole_mm'] == expected_slots[position_key] and not item.IsOnLayer(p.B_Paste) and item.IsOnLayer(p.F_Mask) and item.IsOnLayer(p.B_Mask) and item.GetNetname() == 'GND':
                detail['type'] = 'reviewed_component_pin_in_paste'
                detail['source'] = 'Assets/io/C2927038_footprint_notes.txt; DEALON manufacturer drawing Rev A'
                reviewed_pin_in_paste.append(detail)
                continue
        geometry_errors.append(detail)
if len(reviewed_pin_in_paste) != 4:
    geometry_errors.append({'type': 'unexpected_J1_pin_in_paste_geometry', 'expected': 4, 'observed': len(reviewed_pin_in_paste)})
assert hashlib.sha256(args.board.read_bytes()).hexdigest() == hashlib.sha256(board_bytes).hexdigest(), 'PCB changed during verification; rerun on a stable snapshot'
evidence = {'schema_version': 1, 'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'board': str(args.board.resolve()), 'board_sha256': hashlib.sha256(board_bytes).hexdigest(), 'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'kicad_version': p.GetBuildVersion(), 'method': 'Independent geometric intersection of each physical drill shape with each actual paste aperture, including pad rotation, inherited/local paste margins, paste-only aperture pads, both board faces and all net combinations. No CAD edits or DRC result reuse.', 'geometry_policy': 'Routing-via drills must clear paste by the configured minimum; a1nm numerical allowance accepts the nominal boundary. Other component holes are checked for overlap. Unsupported expanded custom/trapezoid/chamfered pads fail explicitly.', 'minimum_via_paste_clearance_mm': args.minimum_via_paste_clearance_mm, 'numerical_clearance_tolerance_mm': 0.000001, 'via_in_paste_allowlist': [], 'holes_checked': len(holes), 'vias_checked': sum(h['kind'] == 'via' for h in holes), 'paste_apertures_checked': len(apertures), 'pair_comparisons': comparisons, 'reviewed_component_pin_in_paste_features': reviewed_pin_in_paste, 'violations': geometry_errors, 'pass': not geometry_errors, 'primary_references': ['https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/plot_board_layers.cpp', 'https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#working-with-pads', 'https://jlcpcb.com/partdetail/C2927038']}
(out / 'manufacturing-geometry-check.json').write_text(json.dumps(evidence, indent=2) + '\n')
lines = [('PASS' if not geometry_errors else 'FAIL') + ': independent drill / solder-paste geometry check.', f'Board: {args.board.resolve()}', f'SHA256: {evidence["board_sha256"]}', f'{len(holes)} drilled items ({evidence["vias_checked"]} vias), {len(apertures)} paste apertures, {comparisons} comparisons.', 'Via-in-paste allowlist: empty. Net equality does not suppress any intersection.', f'Minimum routing-via drill/paste clearance: {args.minimum_via_paste_clearance_mm:.3f} mm (1nm numerical allowance).', f'Reviewed connector pin-in-paste slots: {len(reviewed_pin_in_paste)}. These are J1 component stakes, not routing vias.', f'Violations: {len(geometry_errors)}.']
for violation in geometry_errors:
    lines.append(json.dumps(violation, sort_keys=True))
(out / 'manufacturing-geometry-check.txt').write_text('\n'.join(lines) + '\n')
print('\n'.join(lines))
if not args.geometry_only:
    if not args.netlist.exists():
        raise SystemExit('Connectivity check needs a freshly exported schematic netlist: ' + str(args.netlist))
    parts = json.loads((src / 'parts.json').read_text())
    byref = {part['ref']: part for part in parts}
    tree = ET.parse(args.netlist)
    netlist = {}
    no_connect_nets = {}
    for net in tree.findall('.//nets/net'):
        for node in net.findall('node'):
            netlist[node.get('ref'), node.get('pin')] = net.get('name')
            if 'no_connect' in node.get('pintype', '').split('+'):
                assert net.get('name').startswith('unconnected-('), 'Unexpected no-connect net naming'
                no_connect_nets[node.get('ref'), node.get('pin')] = net.get('name')
    fps = {footprint.GetReference(): footprint for footprint in b.GetFootprints()}
    errors = []
    count = 0
    populated = {part['ref'] for part in parts if part['lcsc'] and not part.get('dnp', False)}
    for part in parts:
        ref = part['ref']
        footprint = fps.get(ref)
        if footprint is None:
            errors.append(ref + ' missing footprint')
            continue
        if footprint.GetValue() != part['value']:
            errors.append(ref + ' value mismatch')
        if str(footprint.GetFPID().GetLibNickname()) + ':' + str(footprint.GetFPID().GetLibItemName()) != part['footprint']:
            errors.append(ref + ' footprint mismatch')
        if ref in populated and footprint.GetLayer() != p.F_Cu:
            errors.append(ref + ' populated on bottom; assembly must be top only')
        if bool(footprint.GetAttributes() & p.FP_DNP) != bool(part.get('dnp', False)):
            errors.append(ref + ' DNP flag mismatch')
        for pad in footprint.Pads():
            if pad.GetNumber() not in part['pins']:
                expected_nc = no_connect_nets.get((ref, pad.GetNumber()), '')
                if pad.GetNetname() != expected_nc:
                    errors.append(f'{ref}.{pad.GetNumber()} PCB net {pad.GetNetname()}, expected exact schematic no-connect net {expected_nc}')
        for pin, expected in part['pins'].items():
            count += 1
            if netlist.get((ref, pin)) != expected:
                errors.append(f'{ref}.{pin} schematic {netlist.get((ref, pin))}, expected {expected}')
            pads = [pad for pad in footprint.Pads() if pad.GetNumber() == pin]
            if not pads:
                errors.append(f'{ref}.{pin} missing pad')
            for pad in pads:
                if pad.GetNetname() != expected:
                    errors.append(f'{ref}.{pin} PCB {pad.GetNetname()}, expected {expected}')
    assert set(fps) == set(byref) | set(mechanical['mounting_holes']), 'Unexpected or missing PCB footprint'
    assert b.GetCopperLayerCount() == 2, 'LX0002 requires two copper layers'
    assert width == 20 and thickness == 1.6
    assert b.GetDesignSettings().GetBoardThickness() == p.FromMM(thickness)
    origin = b.GetDesignSettings().GetAuxOrigin()
    assert origin.x == 0 and origin.y == p.FromMM(width)
    outline = b.GetBoardEdgesBoundingBox()
    assert abs(p.ToMM(outline.GetWidth()) - length) <= 0.1
    assert abs(p.ToMM(outline.GetHeight()) - width) <= 0.1
    assert (p.ToMM(fps['J1'].GetPosition().x), p.ToMM(fps['J1'].GetPosition().y)) == (usb_x, usb_y)
    assert usb_y == width / 2 and fps['J1'].GetOrientationDegrees() % 360 == 270
    assert (p.ToMM(fps['SW1'].GetPosition().x), p.ToMM(fps['SW1'].GetPosition().y)) == (length / 2, width / 2)
    assert mechanical['button_center'] == [length / 2, width / 2]
    assert byref['J3']['pins'] == {'1': 'DATA16_OUT', '2': 'GND'}
    assert byref['J4']['pins'] == {'1': 'USB_5V', '2': 'DATA17_OUT'}
    for usb_pin in ['A4', 'A9', 'B4', 'B9']:
        assert byref['J1']['pins'][usb_pin] == byref['J4']['pins']['1'] == 'USB_5V', 'USB VBUS must connect directly to LED VCC'
    assert not ({'J2', 'D1', 'D2', 'D3', 'Q1', 'Q2', 'Q3', 'U3', 'U4', 'U5', 'U7', 'F1'} & set(byref)), 'Obsolete power path parts present'
    assert byref['U1']['value'] == 'ESP32-S3FH4R2' and byref['U1']['lcsc'] == 'C3013940'
    assert byref['U1']['footprint'] == 'Core:ESP32_S3FH4R2_QFN56_7x7_EP5p7'
    ep_pads = [pad for pad in fps['U1'].Pads() if pad.GetNumber() == '57']
    assert len(ep_pads) == 1, 'FH4R2 must have one native EP57 copper pad'
    ep = ep_pads[0]
    assert ep.GetSize(p.F_Cu).x == ep.GetSize(p.F_Cu).y == p.FromMM(5.7), 'Stale MCU footprint: FH4R2 requires a 5.7x5.7mm exposed pad'
    assert ep.GetPosition() == fps['U1'].GetPosition() and ep.GetNetname() == 'GND'
    assert ep.IsOnLayer(p.F_Cu) and not ep.IsOnLayer(p.F_Paste), 'EP paste must use independent segmented apertures'
    memory_pins = ['28', '30', '31', '32', '33', '34', '35']
    assert byref['U1']['memory']['reserved_package_pins'] == memory_pins
    for pin in memory_pins:
        pads = [pad for pad in fps['U1'].Pads() if pad.GetNumber() == pin]
        assert len(pads) == 1 and (expected_nc := no_connect_nets.get(('U1', pin))), 'Reserved memory pad must be explicit schematic NC'
        assert pads[0].GetNetname() == expected_nc
        assert not any(track.GetNetname() == expected_nc for track in b.GetTracks()), 'Reserved in-package memory pad has external track/via'
        assert not any(zone.GetNetname() == expected_nc for zone in b.Zones()), 'Reserved in-package memory pad has external copper zone'
    assert byref['R106']['value'] == '0' and byref['R106']['lcsc'] == 'C17477'
    assert byref['R106']['pins'] == {'1': '+3V3', '2': '+3V3_ANALOG'}
    assert byref['U1']['pins']['55'] == byref['U1']['pins']['56'] == byref['C105']['pins']['1'] == '+3V3_ANALOG'
    assert byref['C106']['pins']['1'] == '+3V3'
    assert not {'U10', 'R105', 'R110', 'C110', 'R102'} & set(byref)
    assert not any(str(pin) in byref['U1']['pins'] for pin in [28, 30, 31, 32, 33, 34, 35, 51])
    assert not any(part['libname'].split(':', 1)[0] in {'Memory_Flash', 'Memory_RAM'} for part in parts), 'No off-package memory components'
    for ref, position in mechanical['mounting_holes'].items():
        footprint = fps[ref]
        assert [p.ToMM(footprint.GetPosition().x), p.ToMM(footprint.GetPosition().y)] == position
        pads = list(footprint.Pads())
        assert len(pads) == 1 and pads[0].GetAttribute() == p.PAD_ATTRIB_NPTH
        assert pads[0].GetDrillSize().x == pads[0].GetDrillSize().y == p.FromMM(mechanical['mounting_drill_mm'])
    vias = [track for track in b.GetTracks() if isinstance(track, p.PCB_VIA)]
    assert all(via.GetDrillValue() >= p.FromMM(0.3) for via in vias), 'Routing via drill below 0.30mm'
    assert all(via.GetWidth(layer) - via.GetDrillValue() >= p.FromMM(0.15) for via in vias for layer in [p.F_Cu, p.B_Cu]), 'Routing via annulus below 0.075mm'
    assert all(via.IsTented(p.F_Cu) and via.IsTented(p.B_Cu) for via in vias), 'Routing vias must request tenting on both sides; mask overlap is reviewed separately'
    assert not any(aperture['layer'] == p.B_Paste for aperture in apertures), 'Bottom paste is incompatible with top-only assembly'
    project = json.loads((src / 'LX0002.kicad_pro').read_text())
    rules = project['board']['design_settings']['rules']
    assert rules['min_through_hole_diameter'] >= 0.3
    assert rules['min_via_annular_width'] >= 0.075
    assert not project['board']['design_settings'].get('drc_exclusions'), 'DRC exclusions are not permitted'
    assert not project.get('erc', {}).get('erc_exclusions'), 'ERC exclusions are not permitted'
    for name, severity in project['board']['design_settings'].get('rule_severities', {}).items():
        assert severity not in ['ignore', 'none'], 'Disabled DRC rule: ' + name
    for name, severity in project.get('erc', {}).get('rule_severities', {}).items():
        assert severity not in ['ignore', 'none'], 'Disabled ERC rule: ' + name
    board_text = board_bytes.decode()
    stackup_start = board_text.find('(stackup')
    assert stackup_start >= 0, 'Final PCB needs an explicit manufacturing stackup'
    depth = 0
    for stackup_end in range(stackup_start, len(board_text)):
        if board_text[stackup_end] == '(':
            depth += 1
        elif board_text[stackup_end] == ')':
            depth -= 1
            if depth == 0:
                break
    stackup = board_text[stackup_start:stackup_end + 1]
    for layer in ['F.Mask', 'B.Mask']:
        assert re.search(r'\(layer\s+"' + re.escape(layer) + r'"\s+\(type\s+"[^"]+"\)\s+\(color\s+"Black"\)', stackup), layer + ' must specify black soldermask'
    for layer in ['F.Cu', 'B.Cu']:
        match = re.search(r'\(layer\s+"' + re.escape(layer) + r'"\s+\(type\s+"copper"\)\s+\(thickness\s+([0-9.]+)\)', stackup)
        assert match and abs(float(match.group(1)) - 0.035) < 1e-6, layer + ' must specify 35um nominal copper (1oz)'
    assert 'In1.Cu' not in stackup and 'In2.Cu' not in stackup
    assert hashlib.sha256(args.board.read_bytes()).hexdigest() == hashlib.sha256(board_bytes).hexdigest(), 'PCB changed during verification'
    report = {
        'pass': not errors and not geometry_errors,
        'board_sha256': hashlib.sha256(board_bytes).hexdigest(),
        'netlist_sha256': hashlib.sha256(args.netlist.read_bytes()).hexdigest(),
        'electrical_footprints': len(parts),
        'populated_top_components': len(populated),
        'mounting_holes': len(mechanical['mounting_holes']),
        'mapped_pins_checked': count,
        'board_mm': mechanical['size_mm'],
        'copper_layers': 2,
        'outer_copper_oz': 1,
        'mask': 'black',
        'via_count': len(vias),
        'minimum_via_drill_mm': min((p.ToMM(via.GetDrillValue()) for via in vias), default=None),
        'via_tenting_flags': 'Both sides requested; overlapping mask openings are reviewed separately',
        'mcu_exposed_pad_mm': [5.7, 5.7],
        'reserved_memory_pads': memory_pins,
        'direct_usb_to_led_vcc': True,
        'errors': errors,
        'scope': 'Saved CAD, schematic-netlist agreement and fabrication geometry; RF, USB and assembled thermal qualification remain separate',
    }
    (out / 'connection-check.json').write_text(json.dumps(report, indent=2) + '\n')
    summary = f"{len(parts)} electrical footprints; {len(populated)} populated top components; {count} mapped pins checked.\n"
    summary += 'PASS: schematic netlist, PCB and parts table agree.\n' if not errors else '\n'.join(errors) + '\n'
    summary += 'Two layers, 20mm width, centered USB/button, direct USB 5V output, black mask, 1oz copper, via drills >=0.30mm with both-side tenting flags. Mask-overlap coverage is separate.\n'
    (out / 'connection-check.txt').write_text(summary)
    print(summary)
    assert not errors, errors

raise SystemExit(1 if geometry_errors else 0)
