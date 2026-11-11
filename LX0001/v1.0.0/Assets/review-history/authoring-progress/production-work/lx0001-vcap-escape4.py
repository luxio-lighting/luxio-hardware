import pcbnew as p,shutil
from pathlib import Path
src=Path('/tmp/lx0001-c104-closed.kicad_pcb');dst=Path('/tmp/lx0001-vcap-escape.kicad_pcb');b=p.LoadBoard(str(src));net=b.FindNet('DC_VCAP');pos=p.VECTOR2I(p.FromMM(16.08),p.FromMM(15.55));v=p.PCB_VIA(b);v.SetPosition(pos);v.SetWidth(p.FromMM(.45));v.SetDrill(p.FromMM(.2));v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetViaType(p.VIATYPE_THROUGH);v.SetNet(net);v.SetLocked(True);b.Add(v)
for layer,coords in [(p.F_Cu,[(16.725,15.2),(16.725,16.0)]),(p.B_Cu,[(16.6375,16.05),(16.725,16.0)])]:
 t=p.PCB_TRACK(b);t.SetStart(p.VECTOR2I(p.FromMM(coords[0][0]),p.FromMM(coords[0][1])));t.SetEnd(pos);t.SetWidth(p.FromMM(.2));t.SetLayer(layer);t.SetNet(net);t.SetLocked(True);b.Add(t)
p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(dst),b)
for ext in ['.kicad_pro','.kicad_dru']:shutil.copy2(src.with_suffix(ext),dst.with_suffix(ext))
