"""Estimate serial3V3 copper and the actual R106 jumper; no thermal/transient qualification.

Run with KiCad Python. Branches in parallel are deliberately not credited.
"""
import pcbnew as p,json,math,heapq,hashlib,argparse
from pathlib import Path
from collections import defaultdict
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board',type=Path,required=True)
parser.add_argument('--report',type=Path,required=True)
parser.add_argument('--via-plating-um',type=float,default=18,help='Barrel-wall sensitivity;18um is JLCPCB published average, not a guaranteed local minimum')
args=parser.parse_args()
assert args.via_plating_um > 0
path=str(args.board)
b=p.LoadBoard(path);ts=list(b.GetTracks());fps=list(b.GetFootprints());tracks=[];vias=[];pads=[];points=set();padkeys={}
for t in ts:
 if t.GetNetname() not in ['+3V3','+3V3_ANALOG']:continue
 if isinstance(t,p.PCB_VIA):
  at=(round(t.GetPosition().x/1e6,6),round(t.GetPosition().y/1e6,6));vias.append((at,t.GetDrillValue()/1e6))
  for l in [p.F_Cu,p.B_Cu]:points.add((l,*at))
 else:
  l=t.GetLayer();a=(round(t.GetStart().x/1e6,6),round(t.GetStart().y/1e6,6));z=(round(t.GetEnd().x/1e6,6),round(t.GetEnd().y/1e6,6));tracks.append((l,a,z,t.GetWidth()/1e6));points.add((l,*a));points.add((l,*z))
for f in fps:
 for q in f.Pads():
  if q.GetNetname() not in ['+3V3','+3V3_ANALOG']:continue
  at=(round(q.GetPosition().x/1e6,6),round(q.GetPosition().y/1e6,6))
  for layer in [p.F_Cu,p.B_Cu]:
   if q.IsOnLayer(layer):
    key=(layer,*at);padkeys[f.GetReference()+'.'+q.GetNumber()]=key;points.add(key);pads.append((key,q))
# The final CPU branch touches the wider trunk through a rounded copper end.
# Their centerlines do not intersect after valid dangling-tail cleanup.
# Verify that exact real overlap and use a narrower-than-actual throat for the
# local resistance estimate; never connect geometrically separated copper.
rounded_start=(p.F_Cu,16.4,5.8);rounded_end=(p.F_Cu,16.4,5.6)
branch=[t for t in ts if not isinstance(t,p.PCB_VIA) and t.GetNetname()=='+3V3' and t.GetLayer()==p.F_Cu and abs(p.ToMM(t.GetWidth())-.2)<1e-9 and any(abs(p.ToMM(v.x)-16.4)<1e-6 and abs(p.ToMM(v.y)-5.8)<1e-6 for v in [t.GetStart(),t.GetEnd()])]
trunk=[t for t in ts if not isinstance(t,p.PCB_VIA) and t.GetNetname()=='+3V3' and t.GetLayer()==p.F_Cu and abs(p.ToMM(t.GetWidth())-.3)<1e-9 and abs(p.ToMM(t.GetStart().y)-5.6)<1e-6 and abs(p.ToMM(t.GetEnd().y)-5.6)<1e-6 and min(p.ToMM(t.GetStart().x),p.ToMM(t.GetEnd().x))<16.4<max(p.ToMM(t.GetStart().x),p.ToMM(t.GetEnd().x))]
assert len(branch)==len(trunk)==1,'CPU rounded-contact geometry changed; review its real copper connection'
center_gap=.2;branch_radius=.1;trunk_half_width=.15
actual_throat=2*math.sqrt(branch_radius**2-(center_gap-trunk_half_width)**2)
modeled_throat=.127
assert actual_throat>=modeled_throat and center_gap<branch_radius+trunk_half_width
rounded_r=center_gap*1.724e-8/(modeled_throat*35e-6)
points.add(rounded_end)
g=defaultdict(dict)
for l,a,z,w in tracks:
 dx=z[0]-a[0];dy=z[1]-a[1];l2=dx*dx+dy*dy
 if l2<1e-12:continue
 hits=[]
 for key in points:
  if key[0]!=l:continue
  x,y=key[1:];u=((x-a[0])*dx+(y-a[1])*dy)/l2
  if not -1e-6<=u<=1.000001:continue
  d=math.hypot(x-a[0]-u*dx,y-a[1]-u*dy)
  if d<.0001:hits.append((max(0,min(1,u)),key))
 hits.sort()
 for (u,k),(v,h)in zip(hits,hits[1:]):
  r=(v-u)*math.sqrt(l2)*1.724e-8/(w*35e-6)
  if k!=h:g[k][h]=min(g[k].get(h,1e9),r);g[h][k]=g[k][h]
g[rounded_start][rounded_end]=rounded_r;g[rounded_end][rounded_start]=rounded_r
for at,d in vias:
 k=(0,*at);h=(p.B_Cu,*at);r=1.724e-8*.0016/(math.pi*d*.001*args.via_plating_um*1e-6);g[k][h]=r;g[h][k]=r
for key,q in pads:
 for h in points:
  if h[0]==key[0] and q.HitTest(p.VECTOR2I(p.FromMM(h[1]),p.FromMM(h[2]))):g[key][h]=0;g[h][key]=0
# R106 is a real fitted component, not a trace that shorts the two CAD nets.
parts={part['ref']:part for part in json.loads((Path(__file__).resolve().parents[1]/'parts.json').read_text())}
assert parts['R106']['value']=='0' and parts['R106']['lcsc']=='C17477'
jumper=next(f for f in fps if f.GetReference()=='R106');jp={pad.GetNumber():pad for pad in jumper.Pads()}
assert jp['1'].GetNetname()=='+3V3' and jp['2'].GetNetname()=='+3V3_ANALOG'
jumper_r=parts['R106']['resistance_max_ohm'];assert jumper_r==.05
jk,jh=padkeys['R106.1'],padkeys['R106.2'];g[jk][jh]=jumper_r;g[jh][jk]=jumper_r
start=padkeys['C11.1'];distance={start:0};prev={};heap=[(0,start)]
while heap:
 d,k=heapq.heappop(heap)
 if d!=distance[k]:continue
 for h,w in g[k].items():
  nd=d+w
  if nd<distance.get(h,1e9):distance[h]=nd;prev[h]=k;heapq.heappush(heap,(nd,h))
result={'board_sha256':hashlib.sha256(open(path,'rb').read()).hexdigest(),'method':'shortest serial path; ideal pad contacts, no parallel-path benefit,35um copper; actual R106 component modeled at50mOhm datasheet upper bound','via_plating_um':args.via_plating_um,'via_plating_note':'18um is JLCPCB published average; this is a sensitivity assumption, not a guaranteed local minimum','board_thickness_mm':1.6,'copper_um':35,'copper_temperature_c':20,'reviewer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'rounded_copper_contact':{'net':'+3V3','from_mm':list(rounded_start[1:]),'to_mm':list(rounded_end[1:]),'actual_overlap_mm':branch_radius+trunk_half_width-center_gap,'actual_throat_mm':actual_throat,'modeled_throat_mm':modeled_throat,'modeled_resistance_mohm':rounded_r*1000,'note':'Verified same-net copper overlap;0.127mm modeled throat is narrower than the actual0.173mm junction. This does not fabricate a connection across a copper gap.'},'jumper':{'ref':'R106','lcsc':'C17477','nominal_ohm':0,'modeled_upper_bound_ohm':jumper_r,'datasheet':'../Assets/core/C17477_0805_zero-ohm.pdf','datasheet_page':5,'rated_current_a':2},'paths':{}}
for ref in ['U1.20','U1.46','U1.55','U1.56','C100.1','C107.1']:
 end=padkeys[ref];r=distance.get(end)
 assert r is not None, 'Path graph incomplete: '+ref
 chain=[end]
 while chain[-1]!=start:chain.append(prev[chain[-1]])
 chain=chain[::-1]
 component_r=sum(jumper_r for a,z in zip(chain,chain[1:]) if {a,z}=={jk,jh})
 result['paths'][ref]={'resistance_mohm':1000*r,'copper_resistance_mohm':1000*(r-component_r),'jumper_resistance_bound_mohm':1000*component_r,'drop_at_500ma_mv':500*r,'loss_at_500ma_mw':250*r,'points':chain};print(ref,round(1000*r,3),'mOhm',round(500*r,3),'mV; component bound',round(component_r*1000,3),'mOhm')
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps(result,indent=2)+'\n')
