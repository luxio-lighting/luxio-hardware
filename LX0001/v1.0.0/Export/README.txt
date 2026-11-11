LX0001 v1.0.0 — 60 x 20 mm four-layer fabrication package

Upload LX0001-v1.0.0-Gerbers.zip with JLCPCB-BOM.csv and JLCPCB-CPL.csv.
Use JLCPCB-order-settings.txt: JLC04161H-7628, 1.6 mm, 1 oz outer/0.5 oz
inner copper, black mask, ENIG, two-sided assembly, minimum via drill 0.30 mm.
Re-upload Gerbers AND CPL: the outline, origin and input placement changed.

109 fitted components; L104 is DNP. Bare test pads and mounting holes are
excluded from assembly. Review normal supplier placement orientations.
USB-C and two-wire input are side by side on TOP at the input edge.
The button is centered. H1 moved to (9.5,8) mm from the top-left corner;
H2 remains (42,3) mm. See mechanical.json for enclosure coordinates.
No special USB courtyard exception or fillet restriction remains.

CAD checks: zero DRC findings or exclusions, zero unconnected nets, zero
schematic parity differences and clean ERC. All 231 routing vias use 0.30 mm
drills, are tented, and meet the independent 0.10 mm drill/paste check.
Four USB shell pins intersect their own top-side PIP apertures as intended.

Hardware remains unbuilt. First-article electrical, 5 A thermal, RF, USB and
assembly validation is required before the 100-board lot. Firmware is not
included. No manufacturing order has been placed. Connector STEP models come from the JLCEDA/EasyEDA library. The USB model is
a shared library model; manufacturer drawings govern enclosure dimensions.

Source/LX0001.kicad_pcb is the editable board. Previous packages in
Assets/review-history are historical evidence, not manufacturing inputs.
