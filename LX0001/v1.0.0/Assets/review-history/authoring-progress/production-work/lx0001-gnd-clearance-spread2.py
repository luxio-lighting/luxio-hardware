import pcbnew as p,shutil
from pathlib import Path
src=Path('/Users/emile/Git/@luxio-lighting/luxio-hardware/LX0001/v1.0.0/Source/LX0001.kicad_pcb');dst=Path('/tmp/lx0001-gnd-no-tp3.kicad_pcb');b=p.LoadBoard(str(src));net=b.FindNet('GND')
# Remove redundant EN test pad; EN remains accessible through its resistor/capacitor.
for f in list(b.GetFootprints()):
 if f.GetReference()=='TP3':b.Delete(f)
for t in b.GetTracks():
 if t.GetNetname() in ['+3V3','ESP_EN']:
  points=[t.GetPosition()] if isinstance(t,p.PCB_VIA) else [t.GetStart(),t.GetEnd()]
  for k,q in enumerate(points):
   if abs(p.ToMM(q.x)-25.5)<.001 and abs(p.ToMM(q.y)-5.8)<.001:
    q=p.VECTOR2I(q.x,p.FromMM(5.94))
    if isinstance(t,p.PCB_VIA):t.SetPosition(q)
    elif k==0:t.SetStart(q)
    else:t.SetEnd(q)
   if abs(p.ToMM(q.x)-25.5)<.001 and abs(p.ToMM(q.y)-4.85)<.001:
    q=p.VECTOR2I(q.x,p.FromMM(4.78))
    if isinstance(t,p.PCB_VIA):t.SetPosition(q)
    elif k==0:t.SetStart(q)
    else:t.SetEnd(q)
# Short C104 decoupler return above its ground land; no change to capacitor placement.
v=p.PCB_VIA(b);v.SetPosition(p.VECTOR2I(p.FromMM(25.36),p.FromMM(5.36)));v.SetWidth(p.FromMM(.45));v.SetDrill(p.FromMM(.2));v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetViaType(p.VIATYPE_THROUGH);v.SetNet(net);v.SetLocked(True);b.Add(v)
t=p.PCB_TRACK(b);t.SetStart(p.VECTOR2I(p.FromMM(24.88),p.FromMM(5.3)));t.SetEnd(v.GetPosition());t.SetWidth(p.FromMM(.2));t.SetLayer(p.F_Cu);t.SetNet(net);t.SetLocked(True);b.Add(t)
p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(dst),b)
for ext in ['.kicad_pro','.kicad_dru']:shutil.copy2(src.with_suffix(ext),dst.with_suffix(ext))
