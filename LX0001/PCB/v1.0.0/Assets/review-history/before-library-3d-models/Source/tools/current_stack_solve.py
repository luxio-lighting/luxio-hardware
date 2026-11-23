"""Solve a full-stack copper mesh using NumPy/SciPy. Copper-only DC estimate."""
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.sparse.linalg import cg
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('mesh',type=Path)
parser.add_argument('--report',required=True,type=Path)
parser.add_argument('--json-output',required=True,type=Path)
parser.add_argument('--current-a',type=float,default=1.384)
parser.add_argument('--copper-um',type=float,nargs='+',default=[35])
args=parser.parse_args();mesh=json.loads(args.mesh.read_text());board=Path(mesh['board_path'])
assert hashlib.sha256(board.read_bytes()).hexdigest()==mesh['board_sha256']
shape=tuple(mesh['shape']);rho=1.724e-8;thickness=np.asarray(mesh['copper_thickness_um'])*1e-6;z=np.asarray(mesh['copper_z_mm'])*1e-3
assert shape[0]==len(thickness)==len(z)==4 and np.all(np.diff(z)>0)
assert args.copper_um==[35], 'This solver uses the saved stackup, not uniform copper substitutions'
out={'board_sha256':mesh['board_sha256'],'mesh_sha256':hashlib.sha256(args.mesh.read_bytes()).hexdigest(),'solver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'power_source':mesh.get('power_source'),'model_scope':'All four saved copper layers; actual stackup thicknesses and interlayer barrel lengths','copper_thickness_um':mesh['copper_thickness_um'],'copper_z_mm':mesh['copper_z_mm'],'current_a':args.current_a,'via_plating_um':20,'segments':{}}
lines=['LX0001 full-stack copper-only DC estimate',f"PCB SHA256: {mesh['board_sha256']}",f"Copper layers, um: {mesh['copper_thickness_um']}",'20 C resistivity; 20 um via plating; ideal equipotential component terminals.','Excludes connectors, solder, fuse elements, semiconductor resistance and heating.','Raster discretization is approximate. This is not thermal or surge qualification.',''];successful=True
for net,d in mesh['segments'].items():
 m=np.asarray(d['masks'],dtype=bool).reshape(shape);index=np.full(shape,-1,dtype=np.int32);index[m]=np.arange(m.sum(),dtype=np.int32);aa=[];bb=[];gg=[];via_edges=[]
 for layer,t in enumerate(thickness):
  good=m[layer,:,:-1]&m[layer,:,1:];a=index[layer,:,:-1][good];b=index[layer,:,1:][good];aa.append(a);bb.append(b);gg.append(np.full(a.size,t/rho))
  good=m[layer,:-1,:]&m[layer,1:,:];a=index[layer,:-1,:][good];b=index[layer,1:,:][good];aa.append(a);bb.append(b);gg.append(np.full(a.size,t/rho))
 for v in d['vias']:
  y,x=v['y'],v['x'];diameter=v['drill_mm']*1e-3;wall=20e-6
  if not(0<=y<shape[1] and 0<=x<shape[2]):continue
  for layer,length in enumerate(np.diff(z)):
   if not(m[layer,y,x] and m[layer+1,y,x]):continue
   a,b=index[layer,y,x],index[layer+1,y,x];g=math.pi*(diameter+wall)*wall/(rho*length)
   aa.append(np.asarray([a]));bb.append(np.asarray([b]));gg.append(np.asarray([g]));via_edges.append((v,int(a),int(b),g))
 a=np.concatenate(aa);b=np.concatenate(bb);g=np.concatenate(gg);n=int(m.sum())
 lap=sparse.coo_matrix((np.concatenate([g,g,-g,-g]),(np.concatenate([a,b,a,b]),np.concatenate([a,b,b,a]))),shape=(n,n)).tocsr()
 source=np.unique([index[tuple(q)] for q in d['source']]);sink=np.unique([index[tuple(q)] for q in d['sink']]);assert np.all(source>=0) and np.all(sink>=0) and not np.intersect1d(source,sink).size
 _,labels=csgraph.connected_components(lap,directed=False);common=np.intersect1d(labels[source],labels[sink])
 if not common.size:
  out['segments'][net]={'connected':False,'source_ref':d['source_ref'],'sink_ref':d['sink_ref']};successful=False;lines.append(f'UNRESOLVED MESH CONNECTIVITY: {net}');continue
 active=np.isin(labels,common);active[source]=False;active[sink]=False;free=np.flatnonzero(active);voltage=np.zeros(n);voltage[source]=1
 matrix=lap[free][:,free];rhs=-(lap@voltage)[free];iterations=[0]
 if free.size:
  solution,info=cg(matrix,rhs,rtol=1e-10,atol=0,maxiter=20000,M=sparse.diags(1/matrix.diagonal()),callback=lambda _:iterations.__setitem__(0,iterations[0]+1));voltage[free]=solution
  residual=float(np.linalg.norm(matrix@solution-rhs)/max(np.linalg.norm(rhs),1e-30))
 else:info=0;residual=0
 # Omit source-only islands from energy: they carry no through current.
 included=np.isin(labels,common);edge_active=included[a]&included[b]
 energy=float(np.sum(g[edge_active]*(voltage[a[edge_active]]-voltage[b[edge_active]])**2));injection=float((lap@voltage)[source[np.isin(labels[source],common)]].sum())
 valid=info==0 and residual<1e-8 and energy>0 and abs(injection-energy)<max(energy*1e-6,1e-10)
 if not valid:successful=False
 resistance=1/energy;currents={}
 for v,i,j,conductance in via_edges:
  if not(included[i] and included[j]):continue
  current=abs(voltage[i]-voltage[j])*conductance*args.current_a/energy;key=v.get('uuid',str((v['x'],v['y'])))
  if key not in currents or current>currents[key]['current_a']:currents[key]={**v,'current_a':float(current)}
 row={'copper_um':35,'resistance_mohm':resistance*1000,'drop_mv':resistance*1000*args.current_a,'loss_w':resistance*args.current_a**2,'iterations':iterations[0],'residual':residual,'converged':valid,'via_currents':list(currents.values())}
 out['segments'][net]={'connected':True,'source_ref':d['source_ref'],'sink_ref':d['sink_ref'],'results':[row]};line=f"{net}: {row['resistance_mohm']:.4f} mOhm; {row['drop_mv']:.3f} mV; {row['loss_w']:.5f} W at {args.current_a} A; residual {residual:.2g}";lines.append(line);print(line,flush=True)
out['totals']=[]
if successful:
 total=sum(s['results'][0]['resistance_mohm'] for s in out['segments'].values());out['totals']=[{'copper_um':35,'resistance_mohm':total,'drop_mv':total*args.current_a,'loss_w':total/1000*args.current_a**2}]
 lines.append(f"TOTAL: {total:.4f} mOhm; {total*args.current_a:.3f} mV; {total/1000*args.current_a**2:.5f} W")
out['successful']=successful;args.json_output.parent.mkdir(parents=True,exist_ok=True);args.json_output.write_text(json.dumps(out,indent=2)+'\n');args.report.write_text('\n'.join(lines)+'\n');raise SystemExit(0 if successful else 2)
