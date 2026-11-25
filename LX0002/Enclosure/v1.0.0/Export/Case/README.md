# LX0002 enclosure

CAD fit checked against the final populated 42×20mm PCB: no component interference, with the full 0.20mm board capture allowance. The original PCB handedness is preserved. Physical fit and latch/button force have not been tested.

Two parts, no screws: a base and lid with four latches. Nominal size 45.45×25.60×7.90mm. The board uses one locating pin and edge capture pads. The roof aligns with the terminal tops, leaving all four release buttons accessible.

Print **base.stl** floor-down and **lid.stl** exterior-down, as supplied. Use **PLA, 0.4mm nozzle, 0.1mm layers, supports off**. The portable 3MF contains both parts in their print orientations, without G-code or a printer preset. Select the actual printer and filament before slicing.

Place the PCB over the base pin, lower it onto the support pads, and close the lid evenly. The centered mark identifies the integrated BOOT button. Lift gently at the skirt recesses to release the lid; repeated PLA flexing has not been qualified.

The USB-C profile includes 0.3mm nominal side clearance. Its corner radius is inferred from the supplier model. Physical fit, button force and latch durability still require testing.

- [Base STL](base.stl) · [Lid STL](lid.stl)
- [Print layout 3MF](LX0002-case-print-layout.3mf)
- [Base STEP](base.step) · [Lid STEP](lid.step) · [Case assembly STEP](LX0002-case-assembly.step)
- [SketchUp assembly](LX0002-case.skp) · [Exploded SketchUp](LX0002-case-exploded.skp) · [Print layout SketchUp](LX0002-case-print-layout.skp)

The assembly STEP contains the two case solids. The SketchUp assembly includes the populated PCB reference. For the original populated PCB STEP, use the PCB export; align it by translating Z+1.7988mm only, without mirroring.
