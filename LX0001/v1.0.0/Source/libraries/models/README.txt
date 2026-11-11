LX0001 connector models and local preview models

Selected connector STEP models (applied to both PCB and library footprints):
- HDGC_2060_452_C55251566.step: original model linked to C55251566,
  JLCEDA/EasyEDA Official Library. Housing 7.90 x 11.50 mm, total height
  4.50 mm. Offset (-0.0025, 2.8275, 2.30) mm centers the body and places
  solder terminals on the board surface. Scale 1; no rotation.
- USB_C_C37616412_library.step: original shared model linked to C37616412
  (GCT USB4215-03-A). Upstream title USB-C-SMD_GT-USB-7010B, not a
  manufacturer-authenticated GCT model. Body 8.94 x 6.50 x 3.16 mm and
  shell centers match the GCT drawing. Offset (0,0,1.58) mm; scale 1;
  no rotation. Model stake depth 0.90 mm is within drawing 0.80 +/-0.20 mm.

Source: JLCEDA/EasyEDA Official Library
https://lceda.cn/
https://easyeda.com/
Original metadata, models, hashes and dimensions are retained under
Assets/connectors/JLCEDA-C55251566 and JLCEDA-C37616412. Native STEP units
are millimetres. Manufacturer drawings and real parts govern enclosure fit.
Model alignment is recorded in Source/connector-model-update.json.

The older HDGC and GCT preview WRLs below are superseded, retained as history.
Other small custom parts still use the approximate preview models below.

LX0001 local APPROXIMATE 3D PREVIEW MODELS
Created 2026-11-11 for the intermediate KiCad 3D view.

These are simplified visual models, not manufacturer STEP files. Cosmetic
details, corner radii, lead bends, recesses, actuator profiles and metal
thicknesses are approximate. Do not use them to certify enclosure fit,
assembly tolerances, electrical clearance or connector mating geometry.
The PCB footprints and saved manufacturer drawings remain the authority.

Coordinates use KiCad WRL units: 1 model unit = 2.54 mm. The generated
coordinates are divided by 2.54, so footprint model scale is (1,1,1).
Footprint +Y maps to model -Y. Z=0 is the mounting surface. Native terminal
wire entry and USB mouth point toward footprint +Y. Bottom-side mounting
is handled by KiCad's footprint transformation, not by a separate model.

HDGC_2060_452_preview.wrl
  Main housing nominal envelope 7.90 x 11.50 x 4.50 mm from manufacturer
  drawing A0 2019-10-16. Rear metal tails project 1.60 mm beyond the body;
  terminal pitch 4.00 mm, metal tail width 1.20 mm. Housing is light gray.
  Wire openings and actuator details are cosmetic approximations. The dark
  opening faces are offset 0.0254 mm from the housing to avoid coplanar
  rendering artifacts; they do not define a mating or clearance surface.

USB_C_HDGC_TYPE_C_CQ_105PWB_preview.wrl (SUPERSEDED, reference only)
  Drawing A0 2016-03-12: body length 7.35 mm, overall shell-tab width
  11.44 mm, peg pitch 5.78 mm, peg diameter 0.50 mm and depth 0.75 mm.
  Peg centers match the footprint, native y=-2.605 mm.
  Outer shell width 8.94 mm and height 3.16 mm are INFERRED from the
  8.34 x 2.56 mm opening plus assumed 0.30 mm walls; those outer
  dimensions are not independently dimensioned on the saved drawing.
  Rectangular corners, shell walls, contact tongue and contacts are
  simplified cosmetic geometry. Actual connector has rounded corners.

Walsin_RFANT3216120A5T_preview.wrl
  Nominal ceramic body 3.20 x 1.60 x 1.20 mm, matching the footprint and
  Walsin antenna datasheet. End metallization and marking are approximate.

SW_TS_1088_AR02016_preview.wrl
  Nominal body 3.90 x 3.00 mm, overall height 2.00 mm. The metal lid,
  1.80 mm diameter black actuator and terminal shapes are approximate.
  This models the selected AR02016 height, not the taller library variant.

Fuse_SART_S1206_FA_preview.wrl
  SART JS-S1206-FA-00 Rev H page 2: nominal body 3.10 x 1.55 x 0.55 mm,
  with 0.50 mm end terminations. Marking and manufacturing detail omitted.

CMSA80P06A_DFN5x6_preview.wrl
  CMOS CA07N2 page 4 nominal body E x D x A = 5.85 x 5.05 x 1.00 mm.
  Overall lead span E1=6.15 mm, lead pitch 1.27 mm and lead width 0.30 mm.
  Body draft, pin-one marker and exposed-pad detail are approximated.

USB_C_GCT_USB4215_03_A_preview.wrl (selected release USB)
  Manufacturer Rev A 2024-04-26: nominal body 8.94 x 6.50 x 3.16 mm,
  four shell stakes 0.80 mm deep, no locating pegs. Mouth +Y in footprint.
  Corners, shell walls, tongue and contacts are approximate cosmetics.
