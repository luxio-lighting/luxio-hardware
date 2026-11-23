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
import xml.etree.ElementTree as ET
import pcbnew as p

root = Path(__file__).resolve().parents[2]
src = root / 'Source'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board', type=Path, default=src / 'LX0001.kicad_pcb')
parser.add_argument('--reports-dir', type=Path, default=root / 'Export')
parser.add_argument('--geometry-only', action='store_true')
parser.add_argument('--minimum-via-paste-clearance-mm', type=float, default=0.10)
args = parser.parse_args()
assert args.minimum_via_paste_clearance_mm >= 0
out = args.reports_dir
out.mkdir(parents=True, exist_ok=True)
board_bytes = args.board.read_bytes()
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
        # Their own B.Paste openings implement the documented GCT pin-in-paste
        # mounting. This cannot waive a via or a hole crossing another aperture.
        expected_slots = {(1.6, 5.68): [0.6, 1.8], (1.6, 14.32): [0.6, 1.8], (5.6, 5.68): [0.6, 1.4], (5.6, 14.32): [0.6, 1.4]}
        own_connector_pip = hole['kind'] == 'plated_pad_hole' and hole['reference'] == 'J1' and hole['number'] == 'SH' and aperture['uuid'] == item.m_Uuid.AsString() and aperture['layer'] == p.B_Paste
        if own_connector_pip:
            position_key = tuple(round(value, 5) for value in point)
            if hole['footprint_value'] == 'USB4215-03-A' and hole['footprint_name'] == 'USB_C_GCT_USB4215_03_A' and b.GetDesignSettings().GetBoardThickness() == p.FromMM(1.6) and position_key in expected_slots and hole['hole_mm'] == expected_slots[position_key] and not item.IsOnLayer(p.F_Paste) and not item.IsOnLayer(p.F_Mask) and item.IsOnLayer(p.B_Mask) and item.GetNetname() == 'GND':
                detail['type'] = 'reviewed_component_pin_in_paste'
                detail['source'] = 'Assets/io/C37616412_footprint_notes.txt; manufacturer USB4215 drawing Rev A, 2024-04-26'
                reviewed_pin_in_paste.append(detail)
                continue
        geometry_errors.append(detail)
if len(reviewed_pin_in_paste) != 4:
    geometry_errors.append({'type': 'unexpected_J1_pin_in_paste_geometry', 'expected': 4, 'observed': len(reviewed_pin_in_paste)})
assert hashlib.sha256(args.board.read_bytes()).hexdigest() == hashlib.sha256(board_bytes).hexdigest(), 'PCB changed during verification; rerun on a stable snapshot'
evidence = {'schema_version': 1, 'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'board': str(args.board.resolve()), 'board_sha256': hashlib.sha256(board_bytes).hexdigest(), 'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'kicad_version': p.GetBuildVersion(), 'method': 'Independent geometric intersection of each physical drill shape with each actual paste aperture, including pad rotation, inherited/local paste margins, paste-only aperture pads, both board faces and all net combinations. No CAD edits or DRC result reuse.', 'geometry_policy': 'Routing-via drills must clear paste by the configured minimum; a1nm numerical allowance accepts the nominal boundary. Other component holes are checked for overlap. Unsupported expanded custom/trapezoid/chamfered pads fail explicitly.', 'minimum_via_paste_clearance_mm': args.minimum_via_paste_clearance_mm, 'numerical_clearance_tolerance_mm': 0.000001, 'via_in_paste_allowlist': [], 'holes_checked': len(holes), 'vias_checked': sum(h['kind'] == 'via' for h in holes), 'paste_apertures_checked': len(apertures), 'pair_comparisons': comparisons, 'reviewed_component_pin_in_paste_features': reviewed_pin_in_paste, 'violations': geometry_errors, 'pass': not geometry_errors, 'primary_references': ['https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/plot_board_layers.cpp', 'https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#working-with-pads', 'https://gct.co/connector/usb4215']}
(out / 'manufacturing-geometry-check.json').write_text(json.dumps(evidence, indent=2) + '\n')
lines = [('PASS' if not geometry_errors else 'FAIL') + ': independent drill / solder-paste geometry check.', f'Board: {args.board.resolve()}', f'SHA256: {evidence["board_sha256"]}', f'{len(holes)} drilled items ({evidence["vias_checked"]} vias), {len(apertures)} paste apertures, {comparisons} comparisons.', 'Via-in-paste allowlist: empty. Net equality does not suppress any intersection.', f'Minimum routing-via drill/paste clearance: {args.minimum_via_paste_clearance_mm:.3f} mm (1nm numerical allowance).', f'Reviewed connector pin-in-paste slots: {len(reviewed_pin_in_paste)}. These are J1 component stakes, not routing vias.', f'Violations: {len(geometry_errors)}.']
for violation in geometry_errors:
    lines.append(json.dumps(violation, sort_keys=True))
(out / 'manufacturing-geometry-check.txt').write_text('\n'.join(lines) + '\n')
print('\n'.join(lines))
if not args.geometry_only:
    netlist_path = root / 'Export' / 'netlist.xml'
    if not netlist_path.exists():
        message = 'NOT RUN: connectivity verification requires Export/netlist.xml from the schematic export. Independent geometry evidence was written separately.\n'
        (out / 'connection-check.txt').write_text(message)
        print(message)
        raise SystemExit(1)
    parts=json.loads((src/'parts.json').read_text());tree=ET.parse(netlist_path);netlist={}
    for n in tree.findall('.//nets/net'):
     for node in n.findall('node'):netlist[node.get('ref'),node.get('pin')]=n.get('name')
    fps={f.GetReference():f for f in b.GetFootprints()};errors=[];count=0
    for part in parts:
     ref=part['ref'];f=fps.get(ref)
     if f is None:errors.append(ref+' missing footprint');continue
     if f.GetValue()!=part['value']:errors.append(ref+' value mismatch')
     for pin,net in part['pins'].items():
      count+=1
      if netlist.get((ref,pin))!=net:errors.append(f'{ref}.{pin} schematic {netlist.get((ref,pin))}, expected {net}')
      pads=[a for a in f.Pads() if a.GetNumber()==pin]
      if not pads:errors.append(f'{ref}.{pin} missing pad')
      for a in pads:
       if a.GetNetname()!=net:errors.append(f'{ref}.{pin} PCB {a.GetNetname()}, expected {net}')
    byref={v['ref']:v for v in parts};u=byref['U1']['pins']
    for pin,net in {'5':'BOOT','22':'GPIO16','23':'GPIO17','24':'GPIO18_BUTTON','25':'USB_DM','26':'USB_DP','27':'DATA_ENABLE','10':'USB_STRIP_EN','11':'USB_HIGH_CURRENT','29':'VDD_SPI','57':'GND'}.items():
     if u.get(pin)!=net:errors.append('ESP32 physical pin mapping incorrect '+pin)
    assert byref['U10']['value']=='W25Q32JVSSIQ' and byref['U1']['value']=='ESP32-S3'
    assert byref['D4']['pins']=={'1':'BOOT','2':'GPIO18_BUTTON','3':'BUTTON_COMMON'}
    assert byref['J2']['pins']=={'1':'GND','2':'DC_IN'}
    assert byref['J3']['pins']=={'1':'DATA16_OUT','2':'GND'}
    assert byref['J4']['pins']=={'1':'LED_VCC','2':'DATA17_OUT'}
    assert byref['U8']['pins']['5']=='+5V_DATA' and byref['U9']['pins']['5']=='+5V_DATA'
    assert not any('PSRAM' in q['value'].upper() for q in parts)
    assert b.GetCopperLayerCount()==4
    assert fps['J1'].GetLayer()==p.B_Cu
    assert (p.ToMM(fps['SW1'].GetPosition().x),p.ToMM(fps['SW1'].GetPosition().y))==(30.0,10.0)
    assert set(fps)==set(byref)|{'H1','H2'}
    for ref,pos in json.loads((src/'mechanical.json').read_text())['mounting_holes'].items():
     pos=tuple(pos)
     f=fps[ref];assert (p.ToMM(f.GetPosition().x),p.ToMM(f.GetPosition().y))==pos
     a=list(f.Pads());assert len(a)==1 and a[0].GetAttribute()==p.PAD_ATTRIB_NPTH and a[0].GetDrillSize().x==p.FromMM(2.2)
    r=f'{len(parts)} electrical footprints; 2 mounting holes; {count} mapped pins checked.\n'
    r+='PASS: schematic netlist, PCB and connection table agree.\n' if not errors else '\n'.join(errors)+'\n'
    r+='Pin-specific checks: ESP32-S3/no PSRAM/4MB flash, two 5V outputs, isolated dual-pin button, wired/USB terminals.\n'
    (out/'connection-check.txt').write_text(r);print(r);assert not errors

raise SystemExit(1 if geometry_errors else 0)
