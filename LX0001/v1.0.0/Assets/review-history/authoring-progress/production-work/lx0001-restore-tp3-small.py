import pcbnew as p,shutil
from pathlib import Path
src=Path('/tmp/lx0001-gnd-no-tp3.kicad_pcb');dst=Path('/tmp/lx0001-c104-closed.kicad_pcb');b=p.LoadBoard(str(src));orig=p.LoadBoard('/Users/emile/Git/@luxio-lighting/luxio-hardware/LX0001/v1.0.0/Source/LX0001.kicad_pcb')
f=p.FOOTPRINT(next(f for f in orig.GetFootprints() if f.GetReference()=='TP3'));b.Add(f);f.SetPosition(p.VECTOR2I(p.FromMM(25.55),p.FromMM(4.65)))
for pad in f.Pads():pad.SetSize(p.VECTOR2I(p.FromMM(.5),p.FromMM(.5)))
for item in f.GraphicalItems():
 if item.GetLayer()==p.B_CrtYd:
  item.SetStart(f.GetPosition() + (item.GetStart()-f.GetPosition())/2)
  item.SetEnd(f.GetPosition() + (item.GetEnd()-f.GetPosition())/2)
p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(dst),b)
for ext in ['.kicad_pro','.kicad_dru']:shutil.copy2(src.with_suffix(ext),dst.with_suffix(ext))
