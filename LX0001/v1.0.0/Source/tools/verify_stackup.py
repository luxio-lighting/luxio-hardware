"""Check saved four-layer RF reference copper and manufacturing geometry; no edits."""
from pathlib import Path
import pcbnew as p
import json, math, hashlib
root=Path(__file__).resolve().parents[2];src=root/'Source';path=src/'LX0001.kicad_pcb';b=p.LoadBoard(str(path));assert b.GetCopperLayerCount()==4
layers=[p.F_Cu,p.In1_Cu,p.In2_Cu,p.B_Cu];pro=json.loads((src/'LX0001.kicad_pro').read_text());rfclass=next(c for c in pro['net_settings']['classes'] if c['name']=='RF50');assert rfclass['clearance']==.2 and rfclass['track_width']==.306
rf=[t for t in b.GetTracks() if t.GetNetname()=='RF_50'];assert rf and all(t.GetLayer()==p.F_Cu and t.GetWidth()==p.FromMM(.306) for t in rf)
polys=[z.GetFilledPolysList(p.In1_Cu) for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname()=='GND' and z.IsOnLayer(p.In1_Cu)]
samples=0;missing=[]
for t in rf:
 a,c=t.GetStart(),t.GetEnd();steps=max(1,math.ceil(t.GetLength()/p.FromMM(.1)))
 for i in range(steps+1):
  q=p.VECTOR2I(round(a.x+(c.x-a.x)*i/steps),round(a.y+(c.y-a.y)*i/steps))
  if q.y<p.FromMM(3.1):continue
  samples+=1
  if not any(poly.Contains(q) for poly in polys):missing.append([p.ToMM(q.x),p.ToMM(q.y)])
assert not missing,missing
front=[z.GetFilledPolysList(p.F_Cu) for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname()=='GND' and z.IsOnLayer(p.F_Cu)];gaps=[]
for sign in [-1,1]:
 for offset in range(154,700):
  q=p.VECTOR2I(p.FromMM(17.2+sign*offset/1000),p.FromMM(3.8))
  if any(poly.Contains(q) for poly in front):
   gap=offset/1000-.153;gaps.append(gap);break
assert len(gaps)==2 and all(.199<=g<=.202 for g in gaps),gaps
for layer in layers:
 for x,y in [(9.5,8),(42,3)]:
  assert any(z.GetIsRuleArea() and z.IsOnLayer(layer) and z.GetDoNotAllowTracks() and z.GetDoNotAllowVias() and z.GetDoNotAllowZoneFills() and all(z.Outline().Contains(p.VECTOR2I(p.FromMM(x+dx),p.FromMM(y+dy))) for dx,dy in [(0,0),(2.2,0),(-2.2,0),(0,2.2),(0,-2.2)]) for z in b.Zones()),(layer,x,y)
 if layer!=p.F_Cu:
  assert any(z.GetIsRuleArea() and z.IsOnLayer(layer) and z.GetDoNotAllowTracks() and z.GetDoNotAllowVias() and z.GetDoNotAllowZoneFills() and z.Outline().Contains(p.VECTOR2I(p.FromMM(14.5),p.FromMM(1.5))) for z in b.Zones()),layer
vias=[t for t in b.GetTracks() if isinstance(t,p.PCB_VIA)];assert all(t.IsTented(p.F_Cu) and t.IsTented(p.B_Cu) for t in vias)
assert vias and all(t.GetDrillValue()==p.FromMM(.3) for t in vias), 'Release requires 0.30 mm via drills throughout'
assert all(t.GetWidth(layer)-t.GetDrillValue()>=p.FromMM(.15) for t in vias for layer in layers), 'Via annulus below JLC preferred 0.075 mm'
assert pro['board']['design_settings']['rules']['min_through_hole_diameter']==.3
assert pro['board']['design_settings']['rules']['min_via_annular_width']==.075
e={'board_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'copper_layers':4,'stackup':'JLC04161H-7628','rf_trace_width_mm':.306,'rf_netclass_clearance_mm':.2,'sampled_straight_section_ground_gap_mm':gaps,'rf_centerline_L2_ground_samples':samples,'missing_reference_samples':missing,'antenna_and_screw_keepouts_all_layers':True,'tented_vias_both_sides':len(vias),'minimum_drill_mm':.3,'minimum_via_annulus_mm':.075,'scope':'Saved CAD geometry; uniform-line impedance calculation is not antenna/USB/RF measurement','pass':True};(root/'Export/Validation/four-layer-geometry.json').write_text(json.dumps(e,indent=2)+'\n');print(json.dumps(e,indent=2))
