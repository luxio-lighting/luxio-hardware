"""Estimate DC copper resistance from current_path_mesh.py output, using NumPy.

Example:
  python3 Source/tools/current_path_solve.py /tmp/LX0001-current-mesh.json \
      --report Export/current-path-estimate.txt --json-output /tmp/current-results.json
This is a copper conductance model, not a thermal simulation or current rating.
"""
import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("mesh", type=Path)
parser.add_argument("--report", required=True, type=Path)
parser.add_argument("--json-output", type=Path)
parser.add_argument("--board", type=Path, help="Use this PCB for the required mesh hash check")
parser.add_argument("--copper-um", nargs="+", type=float, default=[35, 70])
parser.add_argument("--current-a", type=float, default=5.0)
parser.add_argument("--board-thickness-mm", type=float, default=1.6)
parser.add_argument("--via-plating-um", type=float, default=20.0)
parser.add_argument("--iterations", type=int, default=12000)
args = parser.parse_args()
assert all(t > 0 for t in args.copper_um) and args.current_a > 0
assert args.board_thickness_mm > 0 and args.via_plating_um > 0
mesh = json.loads(args.mesh.read_text())
board_path = args.board or Path(mesh["board_path"])
assert hashlib.sha256(board_path.read_bytes()).hexdigest() == mesh["board_sha256"], "Mesh is stale: PCB hash differs; extract again"
rho = 1.724e-8
shape = mesh["shape"]
step = mesh["resolution_mm"]
xmin, ymin = mesh["origin_mm"]
out = {"power_source": mesh.get("power_source", "wired"), "board_path": str(board_path.resolve()), "board_sha256": mesh["board_sha256"], "mesh_sha256": hashlib.sha256(args.mesh.read_bytes()).hexdigest(), "solver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "resolution_mm": step, "current_a": args.current_a, "copper_um": args.copper_um, "resistivity_ohm_m": rho, "board_thickness_mm": args.board_thickness_mm, "via_plating_um": args.via_plating_um, "segments": {}}
report = ["LX0001 copper-only DC estimate", "", f"Board: {board_path.resolve()}", f"SHA256: {mesh['board_sha256']}", f"Grid: {step}mm; copper resistivity: {rho}ohm-m at20°C", f"Via model: {args.board_thickness_mm}mm barrel, {args.via_plating_um}µm wall, actual drill diameter", "Saved filled polygons, tracks and pads; ideal equipotential terminal pads.", "Excludes connectors, solder, fuse element, MOSFET resistance and regulator losses.", "Grid discretization can miss narrow features. No thermal or current-rating claim.", ""]
failed = False
for net, data in mesh["segments"].items():
    m = np.array(data["masks"], dtype=bool).reshape(shape)
    source, sink = np.zeros_like(m), np.zeros_like(m)
    for point in data["source"]:
        source[tuple(point)] = True
    for point in data["sink"]:
        sink[tuple(point)] = True
    via_mask = np.zeros(shape[1:], dtype=bool)
    for item in data["vias"]:
        y, x = item["y"], item["x"]
        if 0 <= y < shape[1] and 0 <= x < shape[2] and m[0, y, x] and m[1, y, x]:
            via_mask[y, x] = True
    # Check connectivity before solving; an isolated terminal must not produce
    # an apparently finite resistance from numerical roundoff.
    reached = source.copy()
    queue = deque(tuple(point) for point in data["source"])
    while queue:
        layer, y, x = queue.popleft()
        neighbors = [(layer, y - 1, x), (layer, y + 1, x), (layer, y, x - 1), (layer, y, x + 1)]
        if via_mask[y, x]:
            neighbors.append((1 - layer, y, x))
        for nl, yy, xx in neighbors:
            if 0 <= yy < shape[1] and 0 <= xx < shape[2] and m[nl, yy, xx] and not reached[nl, yy, xx]:
                reached[nl, yy, xx] = True
                queue.append((nl, yy, xx))
    reached_sink = int(np.count_nonzero(reached & sink))
    if not reached_sink:
        out["segments"][net] = {"connected": False, "source_ref": data["source_ref"], "sink_ref": data["sink_ref"]}
        report.append(f"ERROR: {net} has no copper path from {data['source_ref']} to {data['sink_ref']}")
        failed = True
        continue
    active = m & ~(source | sink)
    h = (m[:, :, 1:] & m[:, :, :-1]).astype(float)
    v = (m[:, 1:, :] & m[:, :-1, :]).astype(float)
    rows = []
    for thickness in args.copper_um:
        r_sheet = rho / (thickness * 1e-6)
        via = np.zeros(shape[1:])
        used_vias = []
        for item in data["vias"]:
            y, x = item["y"], item["x"]
            if not (0 <= y < shape[1] and 0 <= x < shape[2] and via_mask[y, x]):
                continue
            wall = args.via_plating_um * 1e-6
            diameter = item["drill_mm"] * 1e-3
            resistance = rho * args.board_thickness_mm * 1e-3 / (math.pi * (diameter + wall) * wall)
            via[y, x] += r_sheet / resistance
            used_vias.append((item, resistance))
        diag = np.zeros(shape)
        diag[:, :, 1:] += h
        diag[:, :, :-1] += h
        diag[:, 1:, :] += v
        diag[:, :-1, :] += v
        diag[0] += via
        diag[1] += via
        fixed_source = source.astype(float)
        rhs = np.zeros(shape)
        rhs[:, :, 1:] += h * fixed_source[:, :, :-1]
        rhs[:, :, :-1] += h * fixed_source[:, :, 1:]
        rhs[:, 1:, :] += v * fixed_source[:, :-1, :]
        rhs[:, :-1, :] += v * fixed_source[:, 1:, :]
        rhs[0] += via * fixed_source[1]
        rhs[1] += via * fixed_source[0]
        rhs *= active
        potential = np.zeros(shape)
        residual_vector = rhs.copy()
        z = np.divide(residual_vector, diag, out=np.zeros_like(rhs), where=diag > 0)
        direction = z.copy()
        rz = np.sum(residual_vector * z)
        residual = float(np.linalg.norm(residual_vector))
        for iteration in range(args.iterations):
            ad = diag * direction
            ad[:, :, 1:] -= h * direction[:, :, :-1]
            ad[:, :, :-1] -= h * direction[:, :, 1:]
            ad[:, 1:, :] -= v * direction[:, :-1, :]
            ad[:, :-1, :] -= v * direction[:, 1:, :]
            ad[0] -= via * direction[1]
            ad[1] -= via * direction[0]
            ad *= active
            denominator = np.sum(direction * ad)
            if denominator <= 0 or residual < 1e-7:
                break
            alpha = rz / denominator
            potential += alpha * direction
            residual_vector -= alpha * ad
            residual = float(np.sqrt(np.sum(residual_vector * residual_vector)))
            if residual < 1e-7:
                break
            z = np.divide(residual_vector, diag, out=np.zeros_like(rhs), where=diag > 0)
            new_rz = np.sum(residual_vector * z)
            direction = z + (new_rz / rz) * direction
            rz = new_rz
        potential += fixed_source
        energy = np.sum(h * np.diff(potential, axis=2) ** 2) + np.sum(v * np.diff(potential, axis=1) ** 2) + np.sum(via * (potential[0] - potential[1]) ** 2)
        resistance = float(r_sheet / energy)
        via_currents = []
        for item, rv in used_vias:
            y, x = item["y"], item["x"]
            via_currents.append({"x_mm": item["x_mm"], "y_mm": item["y_mm"], "drill_mm": item["drill_mm"], "kind": item.get("kind", "routing_via"), "uuid": item.get("uuid"), "current_a": float(abs(potential[0, y, x] - potential[1, y, x]) * r_sheet / rv * args.current_a / energy)})
        row = {"copper_um": thickness, "resistance_mohm": resistance * 1000, "drop_mv": args.current_a * resistance * 1000, "loss_w": args.current_a ** 2 * resistance, "iterations": iteration + 1, "residual": residual, "converged": residual < 1e-7, "via_currents": via_currents}
        rows.append(row)
        failed |= not row["converged"]
        line = f"{net:9s} {thickness:5g}µm: {row['resistance_mohm']:8.4f}mΩ, {row['drop_mv']:8.3f}mV, {row['loss_w']:.5f}W at{args.current_a:g}A; residual{residual:.2g}"
        report.append(line)
        print(line, flush=True)
    out["segments"][net] = {"connected": True, "source_ref": data["source_ref"], "sink_ref": data["sink_ref"], "reached_sink_cells": reached_sink, "total_sink_cells": int(sink.sum()), "results": rows}
out["totals"] = []
if not failed:
    report.append("")
    for thickness in args.copper_um:
        resistance = sum(next(r["resistance_mohm"] for r in segment["results"] if r["copper_um"] == thickness) for segment in out["segments"].values())
        total = {"copper_um": thickness, "resistance_mohm": resistance, "drop_mv": resistance * args.current_a, "loss_w": resistance * args.current_a ** 2 / 1000}
        out["totals"].append(total)
        report.append(f"SUM {thickness:g}µm: {resistance:.4f}mΩ, {total['drop_mv']:.3f}mV, {total['loss_w']:.5f}W")
out["successful"] = not failed
if failed:
    report.append("ERROR: At least one path is disconnected or the solver did not converge; no aggregate result is accepted.")
report += ["", "Re-extract after any routing, footprint, via or zone-fill change.", "This report does not establish continuous current capability or safe fault behavior.", ""]
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text("\n".join(report))
if args.json_output:
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(out, indent=2) + "\n")
print(f"Saved {args.report}")
raise SystemExit(2 if failed else 0)
