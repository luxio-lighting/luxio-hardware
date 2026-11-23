Native LX0001.kicad_pcb is the final routed four-layer design.

Supported final checks/exports:
- generate.py without --board: rebuild schematic/parts/connections only.
- verify_design.py: independent connectivity and drill/paste checks.
- export_manufacturing.py: strict DRC/parity/ERC/geometry gates and exports.
- review_current_paths.py: conservative outer-copper DC estimate.
- add_silkscreen.py --apply and board_appearance.py: appearance edits; rerun
  checks and exports after any board save.

Other placement/fanout/router scripts are retained as development history.
They are not a one-command recipe for reconstructing the final manually
reviewed routing. In particular, generate.py --board replaces the PCB with
initial placement; old rf_fanout.py targets the superseded two-layer layout.
Always preserve the routed native board before using development recipes.
