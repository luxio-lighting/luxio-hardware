# LX0002 copper-path review scope

Run the prepared current-path tools only after routing and zone fill are complete. They read the saved PCB without changing it and reject stale hashes, electrical DRC failures, disconnected paths, unconverged solves and excessive grid sensitivity.

The model includes both specified 35µm copper layers, the direct USB5V route from J1 to J4, and the return from J3 to J1's ground contacts. It does not treat the USB shell as an ideal return terminal. Plated shell stakes still participate as interlayer PCB copper. Connector pads are ideal equipotential terminals; cable, contact and solder resistance are excluded.

The load case is 3A through the complete LED loop. This conservatively loads the LED-path copper because the 3A connector ceiling applies to controller and strip together. It does not model the regulator's heating or establish that a USB adapter permits 3A. There is no PD negotiation or onboard current clamp.

Final cases use fresh 0.10mm and 0.05mm meshes for both nets, with a further 0.025mm USB-positive mesh, at 25µm/20µm/18µm barrel-wall assumptions. Each net must change by no more than 5% between its two finest grids. The 25µm case is a nominal model assumption; 20µm and 18µm are sensitivities. [JLCPCB's capabilities](https://jlcpcb.com/capabilities/pcb-capabilities) currently list 18µm average hole plating. None of these values is a guaranteed local minimum. No copper result is reused after a layout or fill change.

The report includes resistance, voltage drop, planar and barrel Joule loss, individual input-bank via currents and conservative loss estimates for the short 0.33mm VBUS fanout branches. Two branches are not assumed to provide the sum of independently rated ampacities. Optional upper-only/lower-only USB contact cases assess asymmetric current entry. Short-neck loss is reported separately; it is not converted into an enclosure temperature using an isolated long-track chart.

This is PCB-only electrical loss analysis, not thermal qualification. First articles require measurements at the intended total input current: USB cable/connector voltage loss, LED output voltage, individual connector and narrow-route heating, regulator temperature, and closed-enclosure temperature. Verify transient LED loads and sustained USB data at the same time. Connector, solder, cable, USB source capability and PLA enclosure limits remain physical checks.

Run `current_path_mesh.py` using KiCad Python, then `current_path_solve_sparse.py` using the CAD environment with SciPy. The final aggregator is `review_current_paths_adaptive.py`; it requires the exact current-board hashes, fresh strict DRC and the prescribed convergence evidence. `review_3v3_paths.py` separately estimates serial MCU supply-path loss.
