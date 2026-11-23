from pathlib import Path
import json
import pcbnew as p
root=Path(__file__).resolve().parents[1]
b=p.LoadBoard(str(root/'LX0001.kicad_pcb'))
items=[]
for f in b.GetFootprints():
 pts=[]
 for s in f.GraphicalItems():
  if s.GetLayer() in [p.F_CrtYd,p.B_CrtYd]:
   r=s.GetBoundingBox();pts.extend([(p.ToMM(r.GetLeft()),p.ToMM(r.GetTop())),(p.ToMM(r.GetRight()),p.ToMM(r.GetBottom()))])
 if not pts:
  r=f.GetBoundingBox(False,False);pts=[(p.ToMM(r.GetLeft()),p.ToMM(r.GetTop())),(p.ToMM(r.GetRight()),p.ToMM(r.GetBottom()))]
 x,y=p.ToMM(f.GetPosition().x),p.ToMM(f.GetPosition().y)
 items.append(dict(ref=f.GetReference(),x=x,y=y,rot=f.GetOrientationDegrees(),side='Top' if f.GetLayer()==p.F_Cu else 'Bottom',box=[min(a for a,c in pts)-x,min(c for a,c in pts)-y,max(a for a,c in pts)-x,max(c for a,c in pts)-y]))
(root/'placement_geometry.json').write_text(json.dumps(items,indent=2)+'\n')
