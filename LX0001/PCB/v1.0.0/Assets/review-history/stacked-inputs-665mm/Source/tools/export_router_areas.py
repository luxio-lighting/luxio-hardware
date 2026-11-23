"""Export a private routing DSN with locked traces represented as copper areas.

Usage: export_router_areas.py INPUT.kicad_pcb OUTPUT.dsn [--route-aux-power]
This changes only the DSN representation. Import its SES onto the ORIGINAL
KiCad board so all original locked traces/vias remain fabrication geometry.
EXPERIMENTAL: FreeRouting 2.2 treats imported planes as non-obstacles by default.
Use the audited patched JAR with -Dlx0001.areaObstacles=true. Always verify
original-copper preservation, refilled connectivity, and DRC on a private copy
before considering any result for the main board.
"""
from pathlib import Path
import json
import math
import re
import sys
import pcbnew as p

if len(sys.argv) not in [3,4] or (len(sys.argv) == 4 and sys.argv[3] != "--route-aux-power"):
    raise SystemExit("Usage: export_router_areas.py INPUT.kicad_pcb OUTPUT.dsn [--route-aux-power]")
source, target = map(Path, sys.argv[1:3])
route_aux_power = len(sys.argv) == 4
if source.resolve() == target.resolve():
    raise SystemExit("Input board and DSN output must be different files")
board = p.LoadBoard(str(source))
netclass = board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
netclass.SetViaDiameter(p.FromMM(.45))
netclass.SetViaDrill(p.FromMM(.2))
netclass.SetTrackWidth(p.FromMM(.15))
netclass.SetClearance(p.FromMM(.15))
assert p.ExportSpecctraDSN(board, str(target))
dsn = target.read_text()
assert "(unit um)" in dsn and "(resolution um 10)" in dsn

# Raw KiCad zone outlines overlap before priority/clearance processing. Remove
# them; the only area copper below will be the actual locked trace geometry.
removed_planes = 0
while "\n    (plane " in dsn:
    start = dsn.index("\n    (plane ")
    end = start + 1
    depth = 0
    quoted = escaped = False
    while end < len(dsn):
        character = dsn[end]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                break
        end += 1
    assert depth == 0
    dsn = dsn[:start] + dsn[end + 1:]
    removed_planes += 1

nets = {n.GetNetname() for n in board.GetNetInfo().NetsByNetcode().values() if n.GetNetname()}
heavy = {"GND", "DC_IN", "DC_FUSED", "VSYS", "LED_VCC"}
power = {"+3V3", "VDD_SPI", "VDD3P3_RF", "+5V_DATA"}
if route_aux_power:
    heavy -= {"DC_FUSED", "VSYS", "LED_VCC"}
    power |= {"DC_FUSED", "VSYS", "LED_VCC"}
usb_power = {"USB_5V", "USB_LIMITED"}
usb = {"USB_DM", "USB_DP", "USB_DM_CONN", "USB_DP_CONN"}
critical = {"RF_CHIP", "RF_50", "ANT_TUNE", "XTAL_P", "XTAL_P_CRYSTAL", "XTAL_N", "BUCK_BST", "BUCK_SW", "BOOST_SW"}
classes = []
for name, names, width in [("signals", nets-heavy-power-usb_power-usb-critical, 150),
                            ("power", power, 200), ("usb_power", usb_power, 350), ("usb", usb, 200),
                            ("heavy", heavy, 600), ("critical", critical, 150)]:
    classes.append("    (class " + name + " " + " ".join(json.dumps(n) for n in sorted(names & nets))
                   + ' (circuit (use_via "Via[0-1]_450:200_um"))'
                   + f" (rule (width {width}) (clearance 150)))")
start = dsn.index("    (class kicad_default")
end = dsn.index("\n  )\n  (wiring", start)
dsn = dsn[:start] + "\n".join(classes) + dsn[end:]

# Circumscribed 16-segment semicircles prevent polygon approximation from
# understating track copper. Maximum excess is <5um for the board's <=2mm
# tracks, including 0.1um coordinate rounding. Routing clearance is 150um;
# the fabrication DRC minimum remains 127um.
pattern = re.compile(r'\(wire\s+\(path\s+("[^"]+"|[^\s()]+)\s+([\d.eE+-]+)\s+([^)]*)\)\s*\(net\s+("[^"]+"|[^\s()]+)\)\s*\(type\s+fix\)\s*\)', re.S)
matches = list(pattern.finditer(dsn))
planes = []
unions = {}
counts = {}
capsule_count = 0
maximum_excess = 0.0
for match in matches:
    layer, width_string, coordinates, net = match.groups()
    layer = json.loads(layer) if layer.startswith('"') else layer
    net = json.loads(net) if net.startswith('"') else net
    width = float(width_string)
    values = [float(v) for v in coordinates.split()]
    assert len(values) >= 4 and len(values) % 2 == 0
    points = list(zip(values[::2], values[1::2]))
    radius = width / 2
    outer_radius = radius / math.cos(math.pi / 32) + .1
    maximum_excess = max(maximum_excess, outer_radius-radius)
    assert outer_radius-radius <= 5.0, "Increase arc resolution for wider tracks"
    for a, z in zip(points, points[1:]):
        if a == z:
            continue
        angle = math.atan2(z[1]-a[1], z[0]-a[0])
        polygon = []
        for center, first_angle in [(z, angle-math.pi/2), (a, angle+math.pi/2)]:
            for step in range(17):
                theta = first_angle + step*math.pi/16
                polygon.append((center[0]+outer_radius*math.cos(theta), center[1]+outer_radius*math.sin(theta)))
        shape = p.SHAPE_POLY_SET()
        shape.NewOutline()
        for x,y in polygon:
            shape.Append(round(x*1000), round(y*1000))
        key = (net, layer)
        if key not in unions:
            unions[key] = shape
        else:
            unions[key].BooleanAdd(shape)
        capsule_count += 1
        counts[net] = counts.get(net, 0) + 1
# A conductor area only recognizes a via when it contains the via center.
# Include its copper disk on each layer, retaining the original fixed via
# (and drill) in DSN. This also joins capsules that meet at the same via.
via_disks = 0
for via in board.GetTracks():
    if not isinstance(via, p.PCB_VIA) or not via.IsLocked():
        continue
    position = via.GetPosition()
    for layer_id, layer in [(p.F_Cu, "F.Cu"), (p.B_Cu, "B.Cu")]:
        if not via.IsOnLayer(layer_id):
            continue
        radius = via.GetWidth(layer_id)/2
        outer_radius = radius/math.cos(math.pi/32) + 100
        shape = p.SHAPE_POLY_SET()
        shape.NewOutline()
        for step in range(32):
            theta = step*math.pi/16
            shape.Append(round(position.x+outer_radius*math.cos(theta)),
                         round(-position.y+outer_radius*math.sin(theta)))
        key = (via.GetNetname(), layer)
        if key not in unions:
            unions[key] = shape
        else:
            unions[key].BooleanAdd(shape)
        via_disks += 1
hole_count = 0
for (net, layer), shape in unions.items():
    shape.Simplify()
    for index in range(shape.OutlineCount()):
        outline = shape.COutline(index)
        points_text = " ".join(f"{outline.CPoint(i).x/1000:.3f} {outline.CPoint(i).y/1000:.3f}"
                               for i in range(outline.PointCount()))
        plane = f"    (plane {json.dumps(net)} (polygon {layer} 0 {points_text})"
        for hole_index in range(shape.HoleCount(index)):
            hole = shape.CHole(index, hole_index)
            hole_text = " ".join(f"{hole.CPoint(i).x/1000:.3f} {hole.CPoint(i).y/1000:.3f}"
                                 for i in range(hole.PointCount()))
            plane += f" (window (polygon {layer} 0 {hole_text}))"
            hole_count += 1
        planes.append(plane+")")
for match in reversed(matches):
    dsn = dsn[:match.start()] + dsn[match.end():]
assert not pattern.search(dsn)
position = dsn.index("\n  )\n  (placement")
# The physical front rule area permits the intentionally authored antenna
# fingers. The router needs a stricter temporary obstacle to prevent other
# nets traversing that no-copper window; ignored critical copper is retained.
antenna_keepout = "    (keepout LX0001_ANTENNA_ROUTER_ONLY (rect F.Cu 10500 -3000 18500 0))"
dsn = dsn[:position] + "\n" + antenna_keepout + "\n" + "\n".join(planes) + dsn[position:]
dsn = dsn.replace("(path pcb 0  60000 -20000  0 -20000  0 0  60000 0  60000 -20000)",
                  "(path pcb 0  59850 -19850  150 -19850  150 -150  59850 -150  59850 -19850)")
target.write_text(dsn)
statistics = {"input_board":str(source), "dsn":str(target), "raw_zones_removed":removed_planes,
              "locked_wire_paths_converted":len(matches), "capsule_segments":capsule_count,
              "via_disks_in_unions":via_disks, "union_areas":len(planes), "union_holes":hole_count,
              "maximum_radial_excess_um":maximum_excess, "areas_by_net":counts,
              "front_antenna_router_keepout_mm":[10.5,0,18.5,3],
              "route_auxiliary_power_branches":route_aux_power,
              "fixed_vias_retained":len(re.findall(r'\(via [^\n]*\(type fix\)', dsn))}
target.with_suffix(".stats.json").write_text(json.dumps(statistics, indent=2)+"\n")
print(json.dumps(statistics, indent=2))
