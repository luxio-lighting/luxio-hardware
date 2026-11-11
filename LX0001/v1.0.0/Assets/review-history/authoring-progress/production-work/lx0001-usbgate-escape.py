import pcbnew as p,shutil
from pathlib import Path
src=Path('/tmp/lx0001-r2-repair.kicad_pcb');dst=Path('/tmp/lx0001-usbgate-escape.kicad_pcb');b=p.LoadBoard(str(src));net=b.FindNet('USB_GATE');pos=p.VECTOR2I(p.FromMM(18.0),p.FromMM(17.0));v=p.PCB_VIA(b);v.SetPosition(pos);v.SetWidth(p.FromMM(.45));v.SetDrill(p.FromMM(.2));v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetViaType(p.VIATYPE_THROUGH);v.SetNet(net);v.SetLocked(True);b.Add(v)
t=p.PCB_TRACK(b);t.SetStart(p.VECTOR2I(p.FromMM(18.8625),p.FromMM(17.0)));t.SetEnd(pos);t.SetWidth(p.FromMM(.15));t.SetLayer(p.B_Cu);t.SetNet(net);t.SetLocked(True);b.Add(t)
p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(dst),b)
for ext in ['.kicad_pro','.kicad_dru']:shutil.copy2(src.with_suffix(ext),dst.with_suffix(ext))
