LX0001 v1.0.0 enclosure reference - 2026-11-23

Files:
- LX0001-assembled.step: populated board, AP214 solid assembly, 83 components.
- LX0001-assembled-mm.stl: same populated assembly as a binary mesh for SketchUp.
- LX0001-enclosure-plan.png: top and underside positions.
- LX0001-enclosure-heights.png: side profile and connector end faces.
- LX0001-enclosure-dimensions.pdf: both sheets as a vector PDF.
- LX0001-enclosure-reference-mm.dxf: 1:1 CAD reference outlines.
- component-coordinates.csv / enclosure-geometry.json: exact coordinate data.

All dimensions are millimetres. PCB layout source: e67b695.
PDF has two A3 landscape sheets. Main plan and side views are 4:1; end views 6:1.
PNG images are reference pictures; do not assume screen or print scale.
For SketchUp, import a plan image as an image and calibrate the 60.00mm PCB edge.
The dimension labels and coordinate table remain the authority after scaling.

DXF: nominal 1 drawing unit = 1mm. Choose millimetres if the importer asks.
Its origin is the top-left PCB corner; X increases right and CAD Y is negative
down the PCB. It includes board edges, both mounting holes, support envelopes,
button actuator, connector bodies and the two tall underside inductors on
separate layers. These are flat reference outlines, not a printable case.

CSV: all fitted-component centers, orientations and nominal bounding envelopes.
CSV/JSON Y increases down, as in the top-view dimensions. Bottom components
use the same top-view coordinates. The underside PNG flips around the long
axis, keeping the input on the left.

Sources (paths relative to LX0001/):
PCB/v1.0.0/Source/LX0001.kicad_pcb and PCB/v1.0.0/Source/mechanical.json: board outline, hole centers,
connector and component placement, 1.6mm PCB thickness.
PCB/v1.0.0/Assets/io/C2927038_USB-TYPE-C-018.pdf: actual DEALON USB body dimensions.
PCB/v1.0.0/Assets/connectors/HDGC_2060_452_C55251566.pdf: terminal body and tolerance.
PCB/v1.0.0/Assets/io/C720477_TS-1088-AR02016.pdf: switch body, actuator, height and travel.
KiCad library models: other component envelopes and underside height.

The USB library STEP is a shared HRO visualization; its dimensions were not
used for the DEALON body. HDGC body-to-pad longitudinal alignment is nominal,
as documented in PCB/v1.0.0/Source/connector_notes.txt. Wire-bore dimensions are not
specified; the end views show full body envelopes rather than exact bores.
The 3.0mm underside height is model-derived at L1/L2; no local manufacturer
tolerance drawing was available. USB/terminal body envelopes exclude solder,
assembly variation, PCB thickness tolerance and printing clearance. Confirm
connector and inductor dimensions on the received board before final printing.

3D ASSEMBLY EXPORTS
STEP is not a native SketchUp import format. SketchUp Desktop can import the
STL with File > Import > STL; choose millimetres and leave Swap YZ disabled.
The paid SketchUp web version also lists STL import; the free web version
lists only SKP/JPG/PNG imports. STEP requires an importer extension or another
CAD application. The STL is a reference assembly, not a printable enclosure.

STEP/STL XY origin is the top-left board corner, X right and Y negative down.
Z uses KiCad's native substrate-bottom datum, unlike the dimension sheet's
Z=0 top-face datum. The bare exported substrate is 1.5162mm thick, excluding
outer copper/surface layers; use the nominal finished PCB thickness of 1.6mm
for case grooves. KiCad adds component seating offsets: top +1.6012mm and
bottom -0.085mm. Exported whole assembly bounds are X=-1.175..60,
Y=-20..0, Z=-3.085..6.1012mm. These retain library and assembly assumptions.

ANT1/F1/SW1/U4 preview models were converted from their closed VRML meshes to
faceted STEP bodies so every fitted component is included. Source PCB and
schematic were not changed. The connector/model limitations above still
apply, especially the approximate USB-C model. Copper artwork is omitted.

SketchUp references (checked 2026-11-23):
https://help.sketchup.com/en/sketchup/importing-and-exporting-stl-files-3d-printing
https://help.sketchup.com/en/sketchup-web/file-management
