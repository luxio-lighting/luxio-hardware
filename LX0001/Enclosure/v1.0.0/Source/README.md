# Enclosure source

The case is generated from `parameters.json`, the exported PCB geometry and the existing mounting-hole/connector coordinate data. PCB design and manufacturing files are not modified.

Construction parameters use mm: PCB top at Z=0, X along the board, and the 2D drawing's Y-down coordinates. Before export, the constructed case solids are converted to physical CAD coordinates `(x, -y, z)`. The original PCB STEP/STL is translated in Z only, never reflected. Physical assembly coordinates match KiCad's native STEP axes: X right, Y negative down the top view, Z toward the top components. The assembled exports shift Z by +6.8mm to put the base on the ground. Print exports use translations and a 180° lid rotation only.

Checks compare the exported case against the unreflected source PCB and verify the asymmetric mounting-hole positions. All printable and editable exports must be regenerated together after geometry changes. The version remains v1.0.0.

The current lid top is Z=4.5mm, nominally flush with the terminals. Its usual inner ceiling is Z=2.9mm, with a local USB ceiling at Z=3.60mm. Some PCB-specific coordinates, port extents and reliefs are deliberately fixed in `enclosure.py`; not every parameter combination is a valid case.

In construction coordinates, the base end walls span Y=-0.7..20.7mm. The matching lid cuts span Y=-0.95..20.95mm, leaving 0.25mm lateral fit clearance and 1mm front corner returns. The lid carries the full outer corners so the long side faces remain flat and continuous; stepped joints appear only on the end faces.

Terminal roof openings use the same construction Y bounds as the end ports: input 10.8..19.7mm, output 1.3..18.7mm. These Y values are negated in physical CAD exports. The cuts extend beyond the case ends before applying R0.8 corners, placing the outboard curves outside the case. This gives each opening flat side faces all the way to the end, with rounded inboard corners only.

## Rebuild

Use Python with `requirements.txt`, then run from the repository root:

```sh
python LX0001/Enclosure/v1.0.0/Source/enclosure.py
python LX0001/Enclosure/v1.0.0/Source/verify_mechanical.py
python LX0001/Enclosure/v1.0.0/Source/export_print_3mf.py
python LX0001/Enclosure/v1.0.0/Source/render_case.py
python LX0001/Enclosure/v1.0.0/Source/slice_check.py
```

The build reads these reference files, relative to `LX0001/`:

- `Enclosure/v1.0.0/Assets/enclosure-geometry.json`
- `Enclosure/v1.0.0/Assets/LX0001-assembled-mm.stl`
- `PCB/v1.0.0/Source/LX0001.kicad_pcb`, for its provenance hash

Outputs go to `Enclosure/v1.0.0/Export/Case`. `enclosure.py` checks CAD validity, base/lid overlap and print-mesh integrity. `verify_mechanical.py` checks the populated PCB STEP assembly in seated and raised positions, the case joint and corner clearances, and records the current hashes. Changing geometry requires a new collision review; saved reports are evidence for their recorded hashes only.

`render_case.py` uses the exact PCB reference mesh. Optional `--pcb-glb /path/to/board.glb` restores original KiCad component colors. The colored render used the original KiCad GLB with the same geometry and a bounds check. Without a GLB, the PCB is rendered in one color. VTK rendering on macOS requires access to the normal graphics session.

`render_orientation_check.py` shows the original PCB top and the corrected base interior at the same scale and orientation, identifying the USB opening and the two asymmetric mounting holes. It is a visual check in addition to the original-STEP geometry checks in `verify_mechanical.py`.

`slice_check.py` uses the locally installed Bambu Studio CLI, with isolated temporary settings and no printer connection. It accepts `--bambu` and `--profiles` for other installations. It audits actual layer paths and writes reports/previews; any generated G-code stays in a temporary directory and is not a print release. The recorded X1 Carbon settings are validation references, not the user's selected printer.

## Native SketchUp export

The standalone exporter uses the official SketchUp C SDK. SDK binaries are not bundled in this repository. It was built on Apple Silicon with SDK 2027 at the following local location:

```sh
clang++ -std=c++17 -arch arm64 \
  -F /Users/emile/Library/Developer/SDKs/SketchUp-2027 \
  -framework SketchUpAPI \
  -Wl,-rpath,/Users/emile/Library/Developer/SDKs/SketchUp-2027 \
  LX0001/Enclosure/v1.0.0/Source/export_sketchup.cpp \
  -o /tmp/lx0001-export-sketchup

/tmp/lx0001-export-sketchup \
  LX0001/Enclosure/v1.0.0/Export/Case/assembly.tsv \
  LX0001/Enclosure/v1.0.0/Export/Case/LX0001-case.skp
/tmp/lx0001-export-sketchup \
  LX0001/Enclosure/v1.0.0/Export/Case/exploded.tsv \
  LX0001/Enclosure/v1.0.0/Export/Case/LX0001-case-exploded.skp
/tmp/lx0001-export-sketchup \
  LX0001/Enclosure/v1.0.0/Export/Case/print-layout.tsv \
  LX0001/Enclosure/v1.0.0/Export/Case/LX0001-case-print-layout.skp
```

To regenerate all three SketchUp files, renders and their hash report together after compiling the exporter, run:

```sh
python LX0001/Enclosure/v1.0.0/Source/export_sketchup_models.py --render
```

This wrapper accepts `--exporter`, `--case-dir` and `--pcb-glb` for other local paths. The individual exporter commands above perform save/reload checks but do not refresh the combined `sketchup-verification.json` report.

After refreshing all geometry, validation and renders, run `python LX0001/Enclosure/v1.0.0/Source/package_case.py`. It rejects mismatched report/file hashes, refreshes `LX0001-case.zip` and its checksum manifest using the canonical filenames.

Each manifest lists group name, STL path, color and translation. The exporter removes duplicate/degenerate triangles, preserves tiny faces using enlarged group-definition geometry with inverse instance scaling, and saves/reopens every model to verify group counts, face/edge counts, bounds and mm units. World-space dimensions remain 1:1. Preserve group transforms when editing the SketchUp files. These are editable meshes, not SketchUp parametric solids.

The optional PCB group contains the source assembly's shared/nonmanifold boundaries and is for reference only. The two printable case meshes have no boundary or nonmanifold edges.

Print and assembly instructions: `../Export/Case/README.md`.
