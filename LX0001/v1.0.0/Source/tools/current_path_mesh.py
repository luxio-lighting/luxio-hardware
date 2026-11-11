"""Rasterize saved copper without modifying the PCB; run with KiCad's Python.

Example (from v1.0.0):
  <kicad-python> Source/tools/current_path_mesh.py Source/LX0001.kicad_pcb \
      --output /tmp/LX0001-current-mesh.json
Then run current_path_solve.py with a Python installation containing NumPy.
The PCB must already contain current filled-zone geometry.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import pcbnew as pcb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("board", type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--resolution", type=float, default=0.1, help="Grid pitch in mm")
parser.add_argument("--nets", nargs="+", choices=["DC_IN", "DC_FUSED", "USB_5V", "USB_LIMITED", "VSYS", "LED_VCC", "GND"])
parser.add_argument("--power-source", choices=["wired", "usb"], default="wired")
parser.add_argument("--ground-source-ref", help="Override GND injection component for a local return-path assessment")
parser.add_argument("--ground-sink-ref", help="Override GND return component")
args = parser.parse_args()
assert 0.02 <= args.resolution <= 0.5, "Use a resolution between0.02 and0.5mm"
board_path = args.board.resolve()
board_bytes = board_path.read_bytes()
board = pcb.LoadBoard(str(board_path))
assert board.GetCopperLayerCount() in [2,4]
# Conservative outer-copper-only model: ignore parallel internal ground paths.
# Through-barrel resistance uses the full board thickness.
box = board.GetBoardEdgesBoundingBox()
step = args.resolution
xmin = math.floor(pcb.ToMM(box.GetLeft()) / step) * step
ymin = math.floor(pcb.ToMM(box.GetTop()) / step) * step
xmax = math.ceil(pcb.ToMM(box.GetRight()) / step) * step
ymax = math.ceil(pcb.ToMM(box.GetBottom()) / step) * step
nx = int(round((xmax - xmin) / step))
ny = int(round((ymax - ymin) / step))
segments = {
    "DC_IN": ("J2", "F1"),
    "DC_FUSED": ("F1", "Q1"),
    "VSYS": ("Q1", "Q6"),
    "LED_VCC": ("Q6", "J4"),
    "GND": ("J3", "J2"),
}
if args.power_source == "usb":
    segments = {"USB_5V": ("J1", "U4"), "USB_LIMITED": ("U4", "Q3"), "VSYS": ("Q3", "Q6"), "LED_VCC": ("Q6", "J4"), "GND": ("J3", "J1")}
if args.ground_source_ref or args.ground_sink_ref:
    segments["GND"] = (args.ground_source_ref or segments["GND"][0], args.ground_sink_ref or segments["GND"][1])
result = {
    "schema_version": 1,
    "power_source": args.power_source,
    "board_path": str(board_path),
    "board_sha256": hashlib.sha256(board_bytes).hexdigest(),
    "rasterizer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "resolution_mm": step,
    "origin_mm": [xmin, ymin],
    "shape": [2, ny, nx],
    "layer_order": ["F.Cu", "B.Cu"],
    "actual_copper_layers": board.GetCopperLayerCount(),
    "model_scope": "Outer copper only; internal parallel paths excluded (conservative for retained 5A outer spines)",
    "geometry": "Saved filled zones plus existing tracks, vias and copper pads; no refill or PCB changes",
    "terminal_assumption": "All same-net pads of each named terminal component are equipotential; internal component resistance excluded",
    "segments": {},
}
for net, (source_ref, sink_ref) in segments.items():
    if args.nets and net not in args.nets:
        continue
    data = {"source_ref": source_ref, "sink_ref": sink_ref, "masks": [], "vias": [], "source": [], "sink": [], "zones": []}
    for layer_index, layer in enumerate([pcb.F_Cu, pcb.B_Cu]):
        zones = [z for z in board.Zones() if z.GetNetname() == net and z.IsOnLayer(layer)]
        for zone in zones:
            assert zone.IsFilled(), f"Unfilled zone on {net}; refill and save the PCB before analysis"
            data["zones"].append({
                "layer": result["layer_order"][layer_index],
                "filled_polygons": zone.GetFilledPolysList(layer).OutlineCount(),
                "pad_connection": int(zone.GetPadConnection()),
                "solid_pad_connection": zone.GetPadConnection() == pcb.ZONE_CONNECTION_FULL,
            })
        polys = [z.GetFilledPolysList(layer) for z in zones]
        shapes = [t.GetEffectiveShape(layer) for t in board.GetTracks() if t.GetNetname() == net and t.IsOnLayer(layer)]
        shapes += [pad.GetEffectiveShape(layer) for footprint in board.GetFootprints() for pad in footprint.Pads() if pad.GetNetname() == net and pad.IsOnLayer(layer)]
        bins = {}
        for shape in shapes:
            bounds = shape.BBox()
            for bx in range(math.floor(pcb.ToMM(bounds.GetLeft()) / 2) - 1, math.floor(pcb.ToMM(bounds.GetRight()) / 2) + 2):
                for by in range(math.floor(pcb.ToMM(bounds.GetTop()) / 2) - 1, math.floor(pcb.ToMM(bounds.GetBottom()) / 2) + 2):
                    bins.setdefault((bx, by), []).append(shape)
        terminals = {}
        for key, ref in [("source", source_ref), ("sink", sink_ref)]:
            terminals[key] = [pad.GetEffectiveShape(layer) for footprint in board.GetFootprints() if footprint.GetReference() == ref for pad in footprint.Pads() if pad.GetNetname() == net and pad.IsOnLayer(layer)]
        mask = []
        for y in range(ny):
            for x in range(nx):
                xmm, ymm = xmin + (x + 0.5) * step, ymin + (y + 0.5) * step
                point = pcb.VECTOR2I(pcb.FromMM(xmm), pcb.FromMM(ymm))
                point_segment = pcb.SEG(point, point)
                candidates = bins.get((math.floor(xmm / 2), math.floor(ymm / 2)), [])
                mask.append(int(any(poly.Contains(point) for poly in polys) or any(shape.Collide(point_segment, 0) for shape in candidates)))
                for key, pad_shapes in terminals.items():
                    if any(shape.Collide(point_segment, 0) for shape in pad_shapes):
                        data[key].append([layer_index, y, x])
        data["masks"].append(mask)
    for track in board.GetTracks():
        if isinstance(track, pcb.PCB_VIA) and track.GetNetname() == net:
            xmm, ymm = pcb.ToMM(track.GetPosition().x), pcb.ToMM(track.GetPosition().y)
            data["vias"].append({
                "y": int(math.floor((ymm - ymin) / step + 1e-6)),
                "x": int(math.floor((xmm - xmin) / step + 1e-6)),
                "x_mm": xmm,
                "y_mm": ymm,
                "drill_mm": pcb.ToMM(track.GetDrillValue()),
                "kind": "routing_via",
                "uuid": track.m_Uuid.AsString(),
            })
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            if pad.GetNetname() != net or pad.GetAttribute() != pcb.PAD_ATTRIB_PTH or not pad.IsOnLayer(pcb.F_Cu) or not pad.IsOnLayer(pcb.B_Cu):
                continue
            dx, dy = pcb.ToMM(pad.GetDrillSize().x), pcb.ToMM(pad.GetDrillSize().y)
            if not dx or not dy:
                continue
            xmm, ymm = pcb.ToMM(pad.GetPosition().x), pcb.ToMM(pad.GetPosition().y)
            # Match a slot's plated perimeter to the circular-barrel equation.
            # (pi*short + 2*(long-short))/pi is its equivalent diameter.
            effective_diameter = min(dx, dy) + 2 * abs(dx - dy) / math.pi
            data["vias"].append({"y": int(math.floor((ymm - ymin) / step + 1e-6)), "x": int(math.floor((xmm - xmin) / step + 1e-6)), "x_mm": xmm, "y_mm": ymm, "drill_mm": effective_diameter, "physical_drill_mm": [dx, dy], "kind": "plated_component_hole", "reference": footprint.GetReference(), "pad": pad.GetNumber(), "uuid": pad.m_Uuid.AsString()})
    assert data["source"] and data["sink"], f"Missing terminal copper on {net}: {source_ref}/{sink_ref}"
    result["segments"][net] = data
    print(f"{net}: {sum(map(sum, data['masks']))} copper cells, {len(data['vias'])} vias", flush=True)
assert hashlib.sha256(board_path.read_bytes()).hexdigest() == result["board_sha256"], "PCB changed during extraction; rerun on a stable snapshot"
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result) + "\n")
print(f"Saved {args.output}; PCB unchanged")
