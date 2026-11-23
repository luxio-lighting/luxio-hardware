"""Export/reload the three native SketchUp models and refresh the hash audit.

Run after enclosure.py. Add --render to regenerate the three PNGs as well,
using this Python interpreter and the installed VTK/trimesh dependencies.
Compile export_sketchup.cpp first; its executable defaults to /tmp.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--case-dir", type=Path,
                    default=Path(__file__).resolve().parents[2] / "Export/Enclosure/Case")
parser.add_argument("--exporter", type=Path, default=Path("/tmp/lx0001-export-sketchup"))
parser.add_argument("--geometry-scale", type=float, default=1000.0)
parser.add_argument("--render", action="store_true")
parser.add_argument("--pcb-glb", type=Path, default=Path("/tmp/lx0001-full.glb"))
parser.add_argument("--expected-base-sha256")
parser.add_argument("--expected-lid-sha256")
args = parser.parse_args()
case = args.case_dir.resolve()
source = Path(__file__).resolve().parent
exporter = args.exporter.resolve()
inputs = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(case.glob("*.stl"))}
for name, expected in [("base.stl", args.expected_base_sha256),
                       ("lid.stl", args.expected_lid_sha256)]:
    if expected and inputs[name] != expected:
        raise RuntimeError(f"Unexpected input hash for {name}")
report = {
    "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source_stl_sha256": inputs,
    "geometry_scale": args.geometry_scale,
    "model_units": "millimetres",
    "coordinate_tolerance_mm": 0.0001,
    "exporter_source_sha256": hashlib.sha256((source / "export_sketchup.cpp").read_bytes()).hexdigest(),
    "wrapper_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "models": [],
}
for manifest, name in [("assembly.tsv", "LX0001-case.skp"),
                       ("exploded.tsv", "LX0001-case-exploded.skp"),
                       ("print-layout.tsv", "LX0001-case-print-layout.skp")]:
    manifest_hash = hashlib.sha256((case / manifest).read_bytes()).hexdigest()
    command = [str(exporter), str(case / manifest), str(case / name),
               str(args.geometry_scale)]
    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    result.check_returncode()
    if "PASS: saved and reopened" not in result.stdout:
        raise RuntimeError(f"Missing save/reopen verification for {name}")
    if hashlib.sha256((case / manifest).read_bytes()).hexdigest() != manifest_hash:
        raise RuntimeError(f"Manifest changed during export: {manifest}")
    topology = {}
    for part in ("Base", "Lid"):
        stats = re.search(
            rf"^{part}: (\d+) STL triangles, (\d+) shared vertices, (\d+) faces, "
            r"(\d+) edges, (\d+) coplanar edges hidden; (\d+) degenerate / "
            r"(\d+) duplicate triangles removed; (\d+) boundary / (\d+) nonmanifold edges$",
            result.stdout, re.MULTILINE)
        if not stats:
            raise RuntimeError(f"Missing {part} topology report in {name}")
        topology[part] = dict(zip(
            ["stl_triangles", "shared_vertices", "faces", "edges", "hidden_coplanar_edges",
             "degenerate_triangles_removed", "duplicate_triangles_removed",
             "boundary_edges", "nonmanifold_edges"], map(int, stats.groups())))
        if any(int(n) for n in stats.groups()[5:]):
            raise RuntimeError(f"Printable {part} mesh failed topology checks in {name}")
    report["models"].append({
        "file": name,
        "sha256": hashlib.sha256((case / name).read_bytes()).hexdigest(),
        "manifest": manifest,
        "manifest_sha256": manifest_hash,
        "saved_and_reloaded": True,
        "group_count": int(re.search(r"; (\d+) named groups", result.stdout).group(1)),
        "unchanged_face_edge_counts_and_bounds": True,
        "printable_group_topology": topology,
        "verification_log": result.stdout.splitlines(),
    })

if args.render:
    command = [sys.executable, str(source / "render_case.py"),
               "--case-dir", str(case), "--pcb-glb", str(args.pcb_glb)]
    subprocess.run(command, check=True)
    report["renders"] = {
        name: {"sha256": hashlib.sha256((case / name).read_bytes()).hexdigest(),
               "width_px": 1800, "height_px": 1200}
        for name in ("case-closed.png", "case-exploded.png", "case-inside.png")
    }
    report["render_source_sha256"] = hashlib.sha256((source / "render_case.py").read_bytes()).hexdigest()
    if args.pcb_glb.exists():
        report["pcb_color_reference_sha256"] = hashlib.sha256(args.pcb_glb.read_bytes()).hexdigest()
else:
    report["renders_note"] = "PNG renders were not regenerated or audited by this invocation."

for name, digest in inputs.items():
    if hashlib.sha256((case / name).read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"Source STL changed during export: {name}")
output = case / "sketchup-verification.json"
output.write_text(json.dumps(report, indent=2) + "\n")
print(output)
