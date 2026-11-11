LX0001 v1.0.0 — Luxio digital LED-strip controller

CURRENT STATUS: Four-layer fabrication data checked; first article not yet built.
Zero unrouted connections, zero schematic parity issues and zero ERC findings.
Four documented mechanical flags concern the recessed USB shell stakes.

Open Source/LX0001.kicad_pro in KiCad 10. The schematic and PCB are editable;
their symbol and footprint libraries are included in Source/libraries.
Custom connector/antenna 3D bodies are approximate preview models. Use the
manufacturer drawings, not the simplified bodies, for enclosure tolerances.

Design
60 x 20 mm, four copper layers, 1.6 mm FR-4, black mask and white silkscreen.
Bare ESP32-S3, 4 MB external flash, no PSRAM, ceramic 2.4 GHz edge antenna.
Two AHCT buffers translate GPIO16 and GPIO17 to 5 V data outputs.
The input terminal and underside USB-C share the end's y=10 mm centerline.
The two output terminals are centered as a pair at the opposite end.
The BOOT/GPIO18 button is centered at (30,10) mm. Two 2.2 mm M2 holes provide
case mounting; their centers are (9,17) and (42,3) mm from the top-left corner.

Connections, viewed from the top with the input at the left
Input, from antenna-side edge toward the opposite edge: GND, 5-24 V.
Output in the same direction: GND, GPIO16/5 V logic, GPIO17/5 V logic, VCC.
VCC follows the selected supply. It is not converted to the strip's voltage.
The design target is 5 A continuous from the wired supply, including 24 V/120 W.
An 8 A fuse provides fault protection; it is not a precise 5 A current limiter.

A powered wired input takes hardware priority over USB and enables strip power.
USB data stays connected. USB-only operation provides 5 V and has a shared
controller/strip current limit: approximately 0.44 A or 1.28 A, selected by
firmware only when the source permits it. USB strip power defaults OFF.
Firmware must enable it for a configured 5 V strip and enforce the remaining
current budget. A 12/24 V strip requires a suitable wired supply. The circuit
cannot identify a strip's rated voltage from its wires. No firmware is supplied.
See Source/firmware-interface.txt for the complete GPIO and startup contract.

Files
Source: native KiCad project, local libraries, connection table, design notes,
firmware interface and reproducible authoring/checking tools.
Assets: manufacturer datasheets, mechanical drawings, sourcing evidence and
the documented local routing-tool patch.
Export: schematic PDF, JLCPCB BOM/CPL, Gerber/drill archive, assembly drawings,
3D previews and verification reports. Manufacturing files are generated only
after the release checks in Source/tools/export_manufacturing.py pass.

Fabrication/assembly intent
Two-sided assembly, 1 oz outer / 0.5 oz inner copper, ENIG, 1.6 mm and black mask.
Order JLC04161H-7628 stackup; preserve the documented RF geometry.
Use JLCPCB standard two-side PCBA with assembler-designed panel rails/fiducials.
The GCT USB shell stakes are recessed inside the board. Four courtyard flags
refer to their annuli near the opposite-side terminal; top annuli are masked.
Prevent top-side solder protrusions and inspect this overlap on first articles.
See Source/fabrication-intent.txt and the exact connector drawing/notes.
Review the live JLCPCB placement preview and rotations before submitting an
order. No board order has been placed by this task.

Engineering status
The board has not been built or measured. CAD verification does not qualify
5 A thermal performance, antenna matching, USB behavior or assembly yield.
Build and test first articles using Source/first-article-validation.txt before
releasing the 100-board lot. Export/verification.json records the final CAD
checks when available; Source/current_path_review.txt separates copper modeling
from measured thermal performance. Initial RF matching requires measurement.

Cost snapshot, 2026-11-11
109 purchased placements, 52 unique purchased parts, one DNP tuning position
and 11 bare test pads. Components total approximately USD13.3690 per board or
USD1,336.90 per100, excluding PCB, assembly, setup, attrition, tax and shipping.
The dated component-price/stock evidence is not a reservation or a JLCPCB quote.

Editing/rebuilding
Native KiCad files are the primary editable deliverables. Running generate.py
without --board rebuilds only schematic/connection data. Running it with
--board REPLACES the PCB with initial placement and removes completed routing.
Do not run it on a manually revised routed board without preserving that work.
