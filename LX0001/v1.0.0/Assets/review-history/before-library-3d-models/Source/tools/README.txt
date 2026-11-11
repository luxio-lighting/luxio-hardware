Native LX0001.kicad_pcb is the final routed four-layer design.

Supported final checks/exports:
- generate.py without --board: rebuild schematic/parts/connections only.
- verify_design.py: independent connectivity and drill/paste checks.
- export_manufacturing.py: strict DRC/parity/ERC/geometry gates and exports.
- review_current_paths.py --include-usb: full-stack wired/USB copper DC
  estimate; run with NumPy and SciPy installed. KiCad Python extracts copper;
  current_stack_solve.py uses saved per-layer thickness and barrel lengths.
  validate_stack_solver.py checks analytical resistor cases and disconnection.
  current_path_solve.py retains the older outer-only method for historical
  comparisons; it cannot assess all return paths on the current board.
- add_silkscreen.py --apply and board_appearance.py: appearance edits; rerun
  checks and exports after any board save.

Other placement/fanout/router scripts are retained as development history.
They are not a one-command recipe for reconstructing the final manually
reviewed routing. In particular, generate.py --board replaces the PCB with
initial placement; old rf_fanout.py targets the superseded two-layer layout.
Always preserve the routed native board before using development recipes.

Full-stack local TVS return estimate (KiCad Python, then NumPy/SciPy Python):
  current_path_mesh.py Source/LX0001.kicad_pcb --full-stack --nets GND
    --ground-source-ref D3 --ground-sink-ref J2 --output /tmp/tvs-mesh.json
  current_stack_solve.py /tmp/tvs-mesh.json --current-a 1
    --report /tmp/tvs.txt --json-output /tmp/tvs.json
Commands above are shown across lines for readability. Copper resistance
estimates do not establish thermal ratings or transient performance.
