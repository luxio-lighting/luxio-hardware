LX0002 v1.0.0 source

Open LX0002.kicad_pro using KiCad 10. The native schematic, routed board,
project settings, rules, custom libraries and supplier models are authoritative.
The design is two-layer with all 55 fitted components on top. It is not yet
qualified by assembled-board testing; see first-article-validation.md.

Data files
  parts.json / connections.csv: component and electrical connection inventory.
  core_parts.json, io_parts.json, power_parts.json: schematic-generator inputs.
  placement.json / mechanical.json: frozen placements and mechanical datums.
  *_layout.json: captured routing, reference areas and silkscreen.

Tools
  generate.py: regenerate schematic sheets and component inventory.
  build_board.py: rebuilds an UNROUTED board; use a scratch copy when rebuilding.
  author_routes.py: restores captured routing and ground/reference regions.
  sync_board_metadata.py: synchronizes fields and named no-connect nets.
  apply_silkscreen.py: applies the saved label positions.
  board_appearance.py: applies the intended stackup and black-mask appearance.
  verify_circuit.py / verify_design.py: independent topology and geometry checks.
  export_manufacturing.py: read-only source validation and staged manufacturing
    export; requires no ERC, DRC, schematic parity or unconnected findings.
  create_preview_step_models.py: converts the existing approximate antenna and
    switch VRML geometry into matching STEP solids.
  export_mechanical.py: native populated STEP/GLB and millimeter STL reference;
    verifies every fitted reference and preserves coordinate handedness.
  render_board.py: orthographic renders of the actual exported GLB.
  current_path_mesh.py / current_path_solve_sparse.py: two-layer copper model.
  review_current_paths_adaptive.py / review_3v3_paths.py: resistance reviews.

Use the KiCad bundled Python for tools importing pcbnew and the CadQuery
environment for mechanical export/render tools. The manufacturing exporter
uses the installed KiCad CLI and rsvg-convert. On this Mac:
  KiCad CLI: /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
  KiCad Python: /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
  CAD Python: /Users/emile/Git/@luxio-lighting/.tools/cadquery-venv/bin/python

Do not run build_board.py on the routed source merely to refresh exports.
Current routing tables were checked by rebuilding and comparing physical
tracks, vias, pads, keepouts and labels in a separate scratch directory.

Source drawings use KiCad X-right/Y-down. Native STEP uses X-right/Y-negative.
No PCB reflection is applied. The enclosure retains this handedness, and its
print orientation uses proper rotations. The native STEP substrate represents
the 1.51mm dielectric core; finished PCB thickness remains nominally 1.60mm.

Commercial price observations are in ../Assets/pricing. They are dated API
snapshots rather than order quotes. The historical comparison includes MINI-1-N8 and
ESP32-S3FN8 alternatives. This source implements ESP32-S3FH4R2 with 4MB in-package flash and 2MB PSRAM;
the MINI module and FN8 remain historical comparisons.
