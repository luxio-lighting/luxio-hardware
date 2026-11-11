import pcbnew as p,shutil
from pathlib import Path
src=Path('/tmp/lx0001-vcap-escape.kicad_pcb');dst=Path('/tmp/lx0001-c4-ground.kicad_pcb');b=p.LoadBoard(str(src));net=b.FindNet('GND');pos=p.VECTOR2I(p.FromMM(22.865),p.FromMM(10.665));v=p.PCB_VIA(b);v.SetPosition(pos);v.SetWidth(p.FromMM(.45));v.SetDrill(p.FromMM(.2));v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetViaType(p.VIATYPE_THROUGH);v.SetNet(net);v.SetLocked(True);b.Add(v)
t=p.PCB_TRACK(b);t.SetStart(p.VECTOR2I(p.FromMM(22.175),p.FromMM(10.3)));t.SetEnd(pos);t.SetWidth(p.FromMM(.2));t.SetLayer(p.B_Cu);t.SetNet(net);t.SetLocked(True);b.Add(t)
p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(dst),b)
for ext in ['.kicad_pro','.kicad_dru']:shutil.copy2(src.with_suffix(ext),dst.with_suffix(ext))
