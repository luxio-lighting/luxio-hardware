import pcbnew as p,shutil
from pathlib import Path
src=Path('/tmp/lx0001-c4-ground.kicad_pcb');dst=Path('/tmp/lx0001-r2-repair.kicad_pcb');b=p.LoadBoard(str(src));net=b.FindNet('GND');pos=p.VECTOR2I(p.FromMM(12.3),p.FromMM(7.85));v=p.PCB_VIA(b);v.SetPosition(pos);v.SetWidth(p.FromMM(.45));v.SetDrill(p.FromMM(.2));v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetViaType(p.VIATYPE_THROUGH);v.SetNet(net);v.SetLocked(True);b.Add(v)
pts=[(12.1,8.675),(12.3,7.85)]
for a,c in zip(pts,pts[1:]):
 t=p.PCB_TRACK(b);t.SetStart(p.VECTOR2I(p.FromMM(a[0]),p.FromMM(a[1])));t.SetEnd(p.VECTOR2I(p.FromMM(c[0]),p.FromMM(c[1])));t.SetWidth(p.FromMM(.15));t.SetLayer(p.B_Cu);t.SetNet(net);t.SetLocked(True);b.Add(t)
# Mask the small same-net via clearance in J2 paste with a split aperture.
for f in b.GetFootprints():
 if f.GetReference()=='J2':
  for a in list(f.Pads()):
   if a.GetNumber()=='1' and p.ToMM(a.GetPosition().x)>10:
    layers=a.GetLayerSet();layers.RemoveLayer(p.F_Paste);a.SetLayerSet(layers)
    for x,y,w,h in [(11.35,8,0.8,2.0),(13.3,8,1.1,2.0)]:
     q=p.PAD(f);q.SetNumber('');q.SetAttribute(p.PAD_ATTRIB_SMD);q.SetShape(p.PAD_SHAPE_RECT);q.SetPosition(p.VECTOR2I(p.FromMM(x),p.FromMM(y)));q.SetSize(p.VECTOR2I(p.FromMM(w),p.FromMM(h)));ls=p.LSET();ls.AddLayer(p.F_Paste);q.SetLayerSet(ls);f.Add(q)
p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(dst),b)
for ext in ['.kicad_pro','.kicad_dru']:shutil.copy2(src.with_suffix(ext),dst.with_suffix(ext))
