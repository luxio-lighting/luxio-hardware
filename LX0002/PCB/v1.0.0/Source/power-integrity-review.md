# LX0002 power-distribution review

Reviewed PCB SHA256: `d0a10279869ecc5148c814a8ca6f9e71f7244219f3bc38fed5c267d3aabd6448`.

The final 42×20mm FH4R2 board uses two 35µm copper layers. The LMR51410 buck supplies nominal 3.3V; USB5V feeds the strip and data buffers directly. Fresh native DRC, schematic parity and connectivity checks report zero findings. These calculations estimate electrical loss; assembled temperature, transient margins and continuous operating current still require the first-article measurements below.

## USB power path

Fresh 0.10mm/0.05mm meshes were generated for USB5V and GND, with a further 0.025mm USB5V mesh. USB-positive resistance changed by at most 0.323% between its two finest grids; GND changed by at most 1.615%. Both pass the preset 5% convergence criterion. No earlier-board conductance results were reused.

| Via-wall assumption | PCB loop resistance | Drop at 3A | Copper/barrel loss at 3A |
| --- | ---: | ---: | ---: |
| 25µm nominal model | 20.642mΩ | 61.93mV | 0.1858W |
| 20µm sensitivity | 20.927mΩ | 62.78mV | 0.1884W |
| 18µm sensitivity | 21.085mΩ | 63.25mV | 0.1898W |

The 18µm case reflects JLCPCB's published average hole plating; none of these assumptions is a guaranteed local minimum. Uniform 60°C copper would raise the 18µm-case result to 73.20mV and 0.2196W. That is a material-resistivity sensitivity, not a predicted operating temperature. [JLCPCB capabilities](https://jlcpcb.com/capabilities/pcb-capabilities).

The two 0.33mm USB VBUS necks carry approximately 1.418A and 1.582A in the 18µm model. Their respective trace-loss bounds are 4.86mW and 8.14mW, with two 0.30mm-drill vias per bank. The largest individual VBUS barrel current is 1.078A at the output bank. Current sharing assumes equipotential USB VBUS contacts; a faulty contact can change the distribution. Do not add separate nominal trace/via ampacities to infer a higher board rating.

The 3A connector ceiling includes controller and strip current. Assigning all 3A to the strip loop conservatively bounds that PCB path, while actual controller current reduces the available strip budget. Cable, connector-contact, solder, regulator and component losses are excluded. Detailed per-bank currents, mesh provenance and solver convergence are in [current_path_review.txt](current_path_review.txt) and [current-path-model](../Export/current-path-model).

## 3.3V distribution

The serial-path estimate uses copper resistivity 1.724e-8Ωm at 20°C, 35µm copper, 1.6mm board thickness and 18µm via-wall sensitivity. Each path is evaluated with the entire 500mA MCU supply budget; actual current divides among the supply pins and bypass capacitors. Ground-return resistance, regulator load regulation, inductor DCR, capacitor ESR and transient inductance are excluded.

| Serial path from C11 output | Approximate resistance | Drop at 500mA |
| --- | ---: | ---: |
| MCU RTC supply pin 20 | 29.58mΩ | 14.79mV |
| MCU CPU supply pin 46 | 32.64mΩ | 16.32mV |
| MCU analog supply pin 55 | 86.92mΩ | 43.46mV |
| MCU analog supply pin 56 | 85.45mΩ | 42.72mV |
| Left bulk capacitor C100 | 34.77mΩ | 17.39mV |
| Left bulk capacitor C107 | 30.83mΩ | 15.42mV |

The calculation credits no parallel-path benefit and treats pad contacts as ideal. Analog pins 55/56 include the actual fitted R106 jumper at its 50mΩ datasheet upper bound, separately reported from copper resistance. At 500mA the jumper contributes at most 25mV and 12.5mW; actual analog current is below the entire MCU budget. It is modeled as a component, not a fabricated trace joining the two CAD nets.

The CPU-supply branch has a verified rounded-copper junction: its 0.20mm trace overlaps the 0.30mm trunk by 0.05mm, producing an approximately 0.173mm throat. The reviewer uses a narrower 0.127mm throat over the full 0.20mm centerline offset, giving a conservative local 0.776mΩ contribution. Native connectivity and fabrication-clearance checks pass; the reviewer explicitly models this real contact rather than treating nonintersecting centerlines as an open circuit. Reproduce the path results with `tools/review_3v3_paths.py`; its exact board/script provenance is in [3v3-path-review.json](../Export/current-path-model/3v3-path-review.json).

## Exposed-pad ground and layout qualification

Espressif recommends a supply capable of at least 500mA, wide power routing and at least nine exposed-pad ground vias. This compact two-layer board uses narrower local power branches and has a documented deviation from the recommendation for complete ground beneath the chip. [Schematic guidance](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html), [PCB layout guidance](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/pcb-layout-design.html).

The exact native-polygon audit measures 30.955072mm² of contiguous bottom ground within the 32.49mm² full exposed-pad projection: **95.2756919258% coverage**. Static BOOT routing occupies the outer-right 0.28mm rim, with two bottom-corner fill-rounding bounds of 0.05mm each. No missing ground lies outside those documented bounds. The full 5.7×5.7mm front ground pad remains connected, and all nine central ground vias are retained. The RF and crystal reference sampling reports 100% coverage in the protected regions; that geometric audit is not an RF field solution or certification. See [rf-reference-check.json](../Export/rf-reference-check.json).

The nine 0.45mm-diameter/0.30mm-drill exposed-pad vias lie at every combination of X13.6/15.0/16.4mm and Y8.6/10.0/11.4mm. Their holes sit between the sixteen paste windows and pass the independent 0.10mm drill-to-paste clearance check. The exposed pad's full front solder-mask opening leaves thermal-via tops exposed despite individual via-tenting flags; do not infer complete front-side mask coverage from those flags. The dedicated package footprint, paste pattern and connected return core reduce risk but do not establish full Espressif layout conformity or assembled thermal/RF performance.

## Reset and in-package memory supplies

R100/C111 remain 10kΩ/1µF, a nominal 10ms RC constant, near the input area. Their complete EN connection passes connectivity checks. Hot-plug, cold-start, repeated-reset and simultaneous Wi-Fi/LED-load measurements remain required on assembled boards.

VDD_SPI pin 29 retains C108 100nF and C109 1µF for the ESP32-S3FH4R2's in-package 4MB flash and 2MB PSRAM. Package pins 28 and 30–35 have no external traces. Factory eFuses fix VDD_SPI at 3.3V; its internal feed comes from VDD3P3_RTC through a typical 14Ω path. Keep every MCU supply domain powered and check the RTC and memory rails during activity. R102 is omitted because GPIO45 no longer selects this voltage; pad 51 is unconnected. [Espressif memory/power guidance](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html).

## First-article checks

Follow [first-article-validation.md](first-article-validation.md): measure every MCU rail, including C105 after R106, during Wi-Fi transmission and LED load changes; verify startup, BOOT/button behavior, native USB programming/data and both LED outputs. Confirm 4MB flash and 2MB usable PSRAM. Measure controller, buck, USB connector and input-neck temperatures in the closed PLA enclosure. Check RF matching and antenna performance in that enclosure. Use a suitable 5V adapter/cable for the total load; there is no USB PD negotiation or onboard current limiter.
