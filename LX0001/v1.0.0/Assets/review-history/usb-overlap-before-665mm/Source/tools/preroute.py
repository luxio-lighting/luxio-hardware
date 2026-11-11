"""Author the power polygons, RF/clock traces and local regulator loops before routing signals."""
from pathlib import Path
import pcbnew as p
import math
root=Path(__file__).resolve().parents[1];io=p.PCB_IO_KICAD_SEXPR();b=io.LoadBoard(str(root/'LX0001.kicad_pcb'),None)
nets={n.GetNetname():n for n in b.GetNetInfo().NetsByNetcode().values()};fps={f.GetReference():f for f in b.GetFootprints()}
def xy(a):return p.VECTOR2I(p.FromMM(a[0]),p.FromMM(a[1]))
def wire(net,layer,width,points):
 for a,c in zip(points,points[1:]):
  if a==c:continue
  t=p.PCB_TRACK(b);t.SetStart(xy(a));t.SetEnd(xy(c));t.SetWidth(p.FromMM(width));t.SetLayer(layer);t.SetNet(nets[net]);t.SetLocked(True);b.Add(t)
def via(net,x,y,diam=.6,drill=.3):
 v=p.PCB_VIA(b);v.SetPosition(xy((x,y)));v.SetWidth(p.FromMM(diam));v.SetDrill(p.FromMM(drill));v.SetViaType(p.VIATYPE_THROUGH);v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetNet(nets[net]);v.SetLocked(True);b.Add(v)
def zone(net,layer,points,priority=1):
 z=p.ZONE(b);z.SetLayer(layer);z.SetNet(nets[net]);z.SetLocalClearance(p.FromMM(.15));z.SetMinThickness(p.FromMM(.15));z.SetPadConnection(p.ZONE_CONNECTION_FULL);z.SetAssignedPriority(priority);z.SetThermalReliefGap(p.FromMM(.25));z.SetThermalReliefSpokeWidth(p.FromMM(.4));poly=z.Outline();poly.NewOutline()
 for x,y in points:poly.Append(p.FromMM(x),p.FromMM(y))
 b.Add(z)
F=p.F_Cu;B=p.B_Cu
# High-current paths: connector copper, fuse and source/drain lands are solid-connected.
wire('DC_IN',F,1.8,[(3.35,12),(12.6,12),(14,13.4),(14,17),(15.4,18.4),(15.94,18.4)])
wire('DC_FUSED',F,.8,[(19.14,18.4),(19.14,16.53),(20.56,16.53)])
wire('DC_FUSED',F,.4,[(20.56,16.53),(20.56,17.83)])
# Fixed spines preserve the load-current corridor when signal routes cut the pours.
wire('VSYS',F,1.8,[(22.385,17.5),(23.385,18.5),(31.8,18.5)])
wire('VSYS',F,1.3,[(31.8,18.5),(32.75,18.5),(34.7,16.55),(35.2,16.55)])
wire('VSYS',F,.6,[(35.2,14.395),(35.2,16.935)])
wire('VSYS',B,.6,[(23.8,19.15),(33.9,19.15)])
wire('LED_VCC',F,1.2,[(38.7,16.3),(40.8,16.3),(41.25,15.85),(46.5,15.85),(47.4,16.25)])
wire('LED_VCC',F,2.0,[(47.4,16.25),(56.65,16.25)])
zone('DC_FUSED',F,[(18.2,15.9),(20.7,15.9),(20.7,18.12),(19.8,18.12),(19.8,19.6),(18.2,19.6)],2)
zone('VSYS',F,[(21.4,15.8),(24,15.8),(24,17.35),(29.4,17.35),(29.4,16.7),(34.3,16.7),(34.3,13.9),(35.78,13.9),(35.78,17.4),(34.4,17.4),(34.4,19.6),(21.4,19.6)],2)
zone('VSYS',B,[(23.7,18.8),(34.8,18.8),(34.8,19.6),(23.7,19.6)],2)
zone('LED_VCC',F,[(36.9,13.8),(41.55,13.8),(41.55,14.2),(59.65,14.2),(59.65,19.6),(36.9,19.6)],2)
# Two copper layers share the central supply rail through distributed via banks.
for x in [23.8,24.5,25.2,31.1,31.8,32.5,33.2,33.9]:via('VSYS',x,19.25 if x in [31.1,31.8,32.5] else 19.15)
# Connector ground returns join both planes; no signal/current relies on terminal internals.
wire('GND',F,1.8,[(3.35,8),(12.6,8),(13.6,8)])
wire('GND',F,1.2,[(13.85,4.2),(13.85,8)])
wire('GND',F,2.0,[(56.65,3.75),(47.4,3.75)])
wire('GND',F,1.5,[(47.4,3.75),(45.2,3.75)])
for y in [4.2,4.9,5.6,6.3]:via('GND',13.85,y)
for y in [2.8,3.5,4.2,4.9]:via('GND',45.2,y)
# RF routing is authored separately by rf_fanout.py for the edge antenna.
wire('VDD3P3_RF',F,.2,[(18.75,7.8),(18.25,7.8),(18.25,8.2),(18.75,8.2)])
wire('VDD3P3_RF',F,.2,[(18.25,8.2),(17.25,8.2),(17.25,8.62)])
wire('VDD3P3_RF',F,.3,[(17.25,8.62),(16.185,8.62),(16.185,8.7)])
wire('GND',F,.3,[(17.25,9.58),(17.25,10.2)]);via('GND',17.25,10.2,.45,.2)
# Escape EN before freezing the adjacent RF supply route.
wire('ESP_EN',F,.15,[(18.75,8.6),(18,8.6),(18,8.7)]);via('ESP_EN',18,8.7,.45,.2)
# The crystal and its series harmonic-control inductor remain on the MCU side.
wire('XTAL_P',F,.15,[(20.4,6.55),(20.4,5.7),(19.915,5.215),(19.915,5)])
wire('XTAL_P_CRYSTAL',F,.15,[(20.885,5),(20.885,4.3),(20.7,4.115),(20.7,3.25)])
wire('XTAL_N',F,.15,[(20.8,6.55),(20.8,5.9),(23.25,5.9),(23.25,4.35),(23.95,4.35),(23.95,2.6),(22.9,1.55)])
# Exposed-pad ground vias outside the paste aperture, avoiding open via-in-pad.
for dx,dy in [(-2.55,-1.4),(-2.55,0),(-2.55,1.4),(2.55,-1.4),(2.55,0),(2.55,1.4),(0,-2.55),(0,2.55)]:
 x,y=22.2+dx,10+dy;via('GND',x,y,.45,.2);wire('GND',F,.45,[(22.2+max(-1.8,min(1.8,dx)),10+max(-1.8,min(1.8,dy))),(x,y)])
# Local supply decoupling.
wire('+3V3',F,.2,[(21.6,13.45),(21.6,14.8)])
wire('+3V3',F,.2,[(23.6,6.55),(23.6,6.0),(23.92,5.68),(23.92,5.3)])
wire('+3V3',F,.2,[(19.6,6.55),(20.0,6.55)])
wire('+3V3',F,.2,[(19.6,6.55),(19.6,6.02),(18.88,5.3)])
# Buck hot loop / bootstrap / output capacitor path, all bottom.
wire('VSYS',B,.6,[(32.475,3.25),(32.475,5.8875),(32.1375,6.225),(32.1375,6.5)])
wire('VSYS',B,.4,[(32.1375,5.55),(32.475,5.55)])
wire('BUCK_BST',B,.2,[(29.8625,7.45),(30.725,8.3125),(30.725,9.2)])
wire('BUCK_SW',B,.5,[(32.1375,7.45),(32.1375,9.2),(33.2,10),(34,10)])
wire('BUCK_SW',B,.4,[(32.1375,9.2),(32.275,9.2)])
wire('+3V3',B,.8,[(37,10),(39.35,10),(39.8,10.45),(39.8,12.15)])
wire('GND',B,.4,[(29.8625,6.5),(28.85,6.5)]);via('GND',28.85,6.5)
wire('GND',B,.6,[(29.525,3.25),(28,3.25)]);via('GND',28,3.25)
wire('GND',B,.5,[(39.8,8.55),(39.8,7.6)]);via('GND',39.8,7.6)
wire('GND',B,.5,[(39.8,14.05),(39.1,13.35),(39.1,13.3)]);via('GND',39.1,13.3)
# Small 5 V boost powers only AHCT logic. Keep SW copper local and separate from FB.
wire('+3V3',B,.8,[(51.5,12),(53.85,12),(54.05,11.8)])
wire('BOOST_SW',B,.5,[(46.6375,14.55),(47.5,14.55),(48.5,13.55),(48.5,12)])
wire('BOOST_SW',B,.6,[(47.5,14.55),(48.95,16),(49.25,16)])
wire('+5V_DATA',B,.6,[(53.25,16),(54,16),(54.5,16.5),(54.5,18),(56,18),(56,17.95)])
wire('GND',B,.2,[(46.6375,15.5),(45.6,15.5),(45.6,13.8)]);via('GND',45.6,13.8)
wire('GND',B,.4,[(55.95,11.8),(55.6,12.15),(55.6,14)]);via('GND',55.6,14)
wire('GND',B,.4,[(56,16.05),(56.6,15.45),(56.6,14)]);via('GND',56.6,14)
# Ground planes are low-priority and excluded only in the antenna/mounting areas.
for layer in [F,B]:zone('GND',layer,[(.3,.3),(59.7,.3),(59.7,19.7),(.3,19.7)],0)
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());io.SaveBoard(str(root/'LX0001.kicad_pcb'),b)
print('Authored manual critical routes and copper zones')
