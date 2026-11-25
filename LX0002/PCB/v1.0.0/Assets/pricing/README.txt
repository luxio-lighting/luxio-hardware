JLCPCB component prices, checked 2026-11-25, USD, 100 boards

Selected LX0002 design: ESP32-S3FH4R2/C3013940
  Processor: $2.3901 each, 4MB in-package Quad SPI flash + 2MB Quad SPI PSRAM.
  Board: 55 fitted components, 29 unique SKUs.
  Components per board: $4.6469; 100 boards: $464.69.

Compared with ESP32-S3FN8/C2913196:
  FN8 processor: $2.5392 each, 8MB in-package flash, no PSRAM.
  FH4R2 saves $0.1491 per board ($14.91 per 100) at the observed price.
  No external flash or PSRAM chip is needed for either part. FH4R2 has a
  larger 5.7mm exposed pad than FN8's 4mm; the custom footprint and routing
  account for it. The shared 7x7mm body does not imply footprint equivalence.

Historical original discrete ESP32-S3 + external 4MB flash design:
  ESP32-S3/C2913192 $2.0084; W25Q32JVSSIQ/C179173 $1.0239.
  Entire 59-component board $5.2629.
  FH4R2 design saves $0.6160 per board in components.

Historical module alternative, not implemented:
  ESP32-S3-MINI-1-N8/C2913206 $3.3452, 8MB flash, no PSRAM, PCB antenna.
  Module body 15.4x20.5x2.4mm; the module comparison used retained circuits
  from the original 59-part board and totaled $5.2960 in components.
  See comparison.json for that earlier scenario. It is not the current BOM.

L102 uses LQP03HQ2N7B02D/C7216765 at $0.0456: the older C98043
inductor had only four available units. The replacement adds $0.029 per
board and retains the 0201 footprint and nominal 2.7nH matching value.

Prices use aggregate quantity tiers per SKU across 100 boards. Attrition,
assembly, PCB fabrication, freight, tax and coupons are excluded. Feeder,
placement and X-ray fees must be taken from the actual JLCPCB quote; these
component totals are not assembled-board prices.

Sources:
https://jlcpcb.com/partdetail/ESP32-S3FH4R2/C3013940
https://jlcpcb.com/partdetail/EspressifSystems-ESP32_S3_FN8/C2913196
https://jlcpcb.com/partdetail/ESP32-S3-MINI-1-N8/C2913206
https://documentation.espressif.com/esp32_s3_datasheet_en.pdf

current-bom-price.json lists the selected design's references and exact tiers.
comparison.json preserves the earlier external-flash versus module scenario.
Per-SKU JSON files retain selected public API fields and observation times.
