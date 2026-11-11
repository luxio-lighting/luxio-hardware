LX0001 v1.0.0 — automatic hardware revision

Upload the new Gerber ZIP, JLCPCB-BOM.csv and JLCPCB-CPL.csv together.
This revision changes the electrical design and BOM. Do not mix older files.
60 x 20 mm,4 layers,1.6 mm,black,ENIG,0.30 mm vias,both-side assembly.
83 fitted parts:39 top,44 bottom. L104 DNP; test pads and holes not assembled.
USB and wired inputs remain side by side on top; button and case dimensions unchanged.

USB alone automatically supplies5 V to controller and strip. Wired5–24 V input
has hardware priority. No firmware power/current/data-enable GPIO is required.
No onboard USB current limit, no PD and no adapter-current negotiation. Use a
suitable5 V adapter/cable;3 A total USB connector design ceiling is not a clamp.
Wired LED target remains5 A, pending assembled thermal qualification.
Both data outputs are always-enabled5 V AHCT buffers on GPIO16/17.

Release gates: clean ERC/DRC/parity, no open nets, no waived DRC findings,
independent0.10 mm drill/paste clearance,all vias0.30 mm. USB shell stakes use
their own normal top-side PIP apertures. No special mounting exception.

Hardware has not been built or qualified. Validate first articles before100 boards.
Refer to first-article-validation.txt and firmware-interface.txt. No order placed.
Connector models: JLCEDA/EasyEDA; USB is a shared model. New U4 body is an
approximate TI package-envelope preview. Drawings govern manufacturing dimensions.
