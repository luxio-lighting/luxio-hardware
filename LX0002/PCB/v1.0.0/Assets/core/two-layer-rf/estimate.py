"""Nominal2-layerRF cross-section estimate; not a fabrication impedance guarantee.

Run with NumPy/SciPy. Solves div(epsilon grad(V))=0 in a2D nonuniform
finite-volume mesh. Strip=1V; coplanar/bottom/remote boundaries=0V.
Capacitance uses stored field energy; solve again with air to extract
Z0=1/(c*sqrt(C*C_air)). Exact material integrals across layer boundaries.
Metal rectangular; infinitelywide coplanar ground; fixed grounded farbox.
No frequency-dependentdielectrics, etchtrapezoid, surfacefinish, bend or
componentlaunch. Compare the zero-thicknesscase with Qucs conformalmapping:
https://qucs.github.io/tech/node86.html
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
import json,time
from pathlib import Path
results=[]
for width,gap,er,t,mask,dx in [(0.8,0.20,4.5,.035,.01,.005),(0.8,0.20,4.5,.035,.01,.0025),(0.8,0.20,4.5,.035,.01,.00125),(0.8,0.20,4.5,0,0,.00125),(0.8,0.20,4.2,.035,.01,.0025),(0.8,0.20,4.8,.035,.01,.0025),(0.8,0.20,4.5,.035,.02,.0025)]:
 h=1.51;mask_er=4.4
 x=np.unique(np.r_[np.arange(-1.5,1.50001,dx),-np.geomspace(1.5,8,70),np.geomspace(1.5,8,70),[-width/2,width/2,-width/2-gap,width/2+gap]])
 y=np.unique(np.r_[-np.geomspace(.1,h,70),np.arange(-.1,.100001,dx),np.geomspace(.1,5,70),[0,t,t+mask]])
 x=np.round(x,8);y=np.round(y,8);x=np.unique(x);y=np.unique(y);ny=len(y);nx=len(x)
 xx,yy=np.meshgrid(x,y);delta_x=np.diff(x);delta_y=np.diff(y)
 span_x=np.r_[delta_x[0]/2,(delta_x[1:]+delta_x[:-1])/2,delta_x[-1]/2]
 span_y=np.r_[delta_y[0]/2,(delta_y[1:]+delta_y[:-1])/2,delta_y[-1]/2]
 wire=(abs(xx)<=width/2+1e-8)&(yy>=-1e-8)&(yy<=t+1e-8)
 ground=(abs(xx)>=width/2+gap-1e-8)&(yy>=-1e-8)&(yy<=t+1e-8)
 fixed=wire|ground;fixed[:,0]=True;fixed[:,-1]=True;fixed[0,:]=True;fixed[-1,:]=True
 ids=np.arange(nx*ny).reshape(ny,nx);unknown=~fixed.ravel();known_values=wire.astype(float).ravel()
 caps=[]
 for air in (False,True):
  lo=np.r_[y[0],(y[1:]+y[:-1])/2];hi=np.r_[(y[1:]+y[:-1])/2,y[-1]]
  sub=np.maximum(np.minimum(hi,0)-lo,0);coat=np.maximum(np.minimum(hi,t+mask)-np.maximum(lo,0),0);vac=hi-lo-sub-coat
  integral=span_y if air else er*sub+mask_er*coat+vac
  gx=np.broadcast_to(integral[:,None]/delta_x[None,:],(ny,nx-1))
  sub2=np.maximum(np.minimum(y[1:],0)-y[:-1],0);coat2=np.maximum(np.minimum(y[1:],t+mask)-np.maximum(y[:-1],0),0);vac2=delta_y-sub2-coat2
  inverse=delta_y if air else sub2/er+coat2/mask_er+vac2
  gy=np.broadcast_to(span_x[None,:]/inverse[:,None],(ny-1,nx))
  edge_a=np.r_[ids[:,:-1].ravel(),ids[:-1,:].ravel()];edge_b=np.r_[ids[:,1:].ravel(),ids[1:,:].ravel()];g=np.r_[gx.ravel(),gy.ravel()]
  row=np.r_[edge_a,edge_b,edge_a,edge_b];col=np.r_[edge_b,edge_a,edge_a,edge_b];data=np.r_[-g,-g,g,g]
  a=coo_matrix((data,(row,col)),shape=(nx*ny,nx*ny)).tocsr()
  b=-(a@known_values)[unknown]
  vv=known_values.copy();vv[unknown]=spsolve(a[unknown,:][:,unknown],b)
  cap=8.8541878128e-12*np.sum(g*(vv[edge_a]-vv[edge_b])**2)
  caps.append(cap)
 z=1/(299792458*np.sqrt(caps[0]*caps[1]));entry=dict(width_mm=width,gap_mm=gap,substrate_er=er,dielectric_height_mm=h,copper_thickness_mm=t,mask_thickness_above_copper_mm=mask,mask_er=mask_er,impedance_ohm=float(z),effective_er=float(caps[0]/caps[1]),mesh_nodes=nx*ny,mesh_min_pitch_mm=dx,mask_model='uniform mask fills gaps to copper top plus specified mask thickness',finite_box_mm=[float(x[0]),float(x[-1]),float(y[0]),float(y[-1])]);results.append(entry);print(json.dumps(entry),flush=True)
Path(__file__).with_name('field-solver-results.json').write_text(json.dumps(results,indent=2)+'\n')
