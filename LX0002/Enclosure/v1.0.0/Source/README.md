# LX0002 enclosure source

Two PLA parts for the 42×20×1.6mm LX0002 PCB. Nominal assembled envelope 45.45×25.60×7.90mm. The lid is flush with the 4.5mm terminal tops. Four case latches close the enclosure; one locating pin and four edge capture pads retain the PCB without screws.

Parameters are in `parameters.json`; PCB length, locating-hole position and connector/button anchors are read from `PCB/v1.0.0/Source/mechanical.json`. Construction uses the PCB drawing's X-right/Y-down coordinates with PCB top at Z=0. Both case solids are converted exactly once to physical `(X,-Y,Z)` before export. The original KiCad STEP/STL is never reflected. Assembled exports shift Z+3.4mm to put the base on the ground. Printable files use translations and a 180° lid rotation only.

The USB opening is 9.54×3.76mm with R1.30mm corners. DEALON specifies the 8.94×3.16mm body; its 1.0mm nominal corner radius is inferred from the supplier model. The output roof opening leaves all four wire-release actuators accessible. The long outside walls remain flat.

The 15×18mm elliptical button diaphragm is 0.4mm thick with an integral plunger and 0.6mm nominal switch gap. A first-order latch estimate is recorded in `verification.json`; physical insertion force, button force, fatigue and printer tolerances remain untested.

Use PLA, a 0.4mm nozzle and 0.1mm layers. The base prints floor-down and the lid exterior-down. Both supplied STL files are already oriented. Reference slicing uses the local Bambu Studio CLI with supports disabled; it does not connect to a printer.

## Build and validate

Use the CadQuery environment listed in `requirements.txt`. From the repository root:

```sh
python LX0002/Enclosure/v1.0.0/Source/enclosure.py
python LX0002/Enclosure/v1.0.0/Source/verify_mechanical.py
python LX0002/Enclosure/v1.0.0/Source/slice_check.py
python LX0002/Enclosure/v1.0.0/Source/export_print_3mf.py
python LX0002/Enclosure/v1.0.0/Source/export_sketchup_models.py --render --pcb-glb LX0002/PCB/v1.0.0/Export/LX0002-assembled.glb
python LX0002/Enclosure/v1.0.0/Source/package_case.py
```

`enclosure.py --output /tmp/lx0002-case-draft --skip-pcb-reference` constructs preliminary geometry without importing an obsolete PCB model. The normal build rejects stale PCB provenance. Final validation and packaging require the original completed `Assets/LX0002-assembled.step`, matching millimeter STL, and `assembled-export-verification.json` recording the PCB hash and populated references. The exact-solid checker tests every component seated and raised by the 0.20mm PCB capture allowance. It also checks locating-pin alignment, connector access, flat sides, print transforms and positive mesh volume.

After geometry changes, regenerate all exports and validation reports together. Reports apply only to their recorded hashes. These checks do not establish physical fit, thermal suitability, RF performance or latch durability.

## SketchUp SDK

Compile the standalone exporter with the locally installed official SketchUp SDK:

```sh
clang++ -std=c++17 -arch arm64 \
  -F /Users/emile/Library/Developer/SDKs/SketchUp-2027 \
  -framework SketchUpAPI \
  -Wl,-rpath,/Users/emile/Library/Developer/SDKs/SketchUp-2027 \
  LX0002/Enclosure/v1.0.0/Source/export_sketchup.cpp \
  -o /tmp/lx0002-export-sketchup
```

The wrapper saves and reopens each model to check topology, groups, bounds and millimeter units. Printable case meshes must retain every face. The combined PCB visualization may merge up to 100 microscopic facets only when the total surface-area difference remains below 0.01mm²; the exact STEP, original reference STL and solid collision checks remain unchanged. SketchUp files contain editable meshes; STEP files contain CAD solids. Preserve SketchUp group transforms when editing. SDK binaries are not distributed here. Saving SketchUp models and rendering with VTK require access to the normal macOS graphics session.

The assembly STEP contains only the two case solids. The original populated PCB STEP stays unchanged in Assets; translate it Z+1.7988mm to align it with the case assembly. The full populated SketchUp models use the original PCB reference mesh. Re-exporting the supplier USB model through CadQuery changed its sampled geometry, so that model is deliberately not reserialized into the case STEP.
