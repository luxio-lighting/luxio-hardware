LX0002 v1.0.0 — USB-only 5V controller

Upload LX0002-v1.0.0-Gerbers.zip, JLCPCB-BOM.csv and JLCPCB-CPL.csv together.
42 x 20mm, two copper layers, 1.6mm FR-4, black mask,
white silkscreen, 1oz copper on both sides, minimum 0.30mm via drill.
Select TOP-SIDE assembly only: 55 fitted components.
L104 is DNP; test pads and mounting holes are not assembled.

USB 5V connects directly to LED VCC. There is no external DC input, power-path
diode, source-selection circuit, USB PD or onboard input current limiter.
J1 is DEALON USB-TYPE-C-018/C2927038, rated 3A at 5V total including controller
and strip. Use a suitable regulated 5V adapter and cable. This rating is not
a current clamp or a measured continuous-current thermal qualification.
GPIO16 and GPIO17 have permanently enabled 5V AHCT data buffers.

Release checks require zero ERC/DRC/parity findings including exclusions,
zero open nets, matching BOM/CPL references, top-only assembly, and independent
0.10mm minimum routing-via drill-to-paste clearance. The four USB shell stakes
use their own normal top-side pin-in-paste apertures; they are component pins,
not routing-via exceptions. Both-side tenting is requested for routing vias.
The MCU exposed-pad mask opening exposes its thermal-via tops; these holes
clear the paste windows. Tenting flags do not override component mask openings.

Validate the first assembled boards electrically, thermally, over USB and over
Wi-Fi before a production run. CAD checks do not establish physical qualification.
The USB 3D model is a supplier visualization; manufacturer drawings govern fit.
