"""Minimize placement conflicts while keeping selected RF/power/mechanical anchors fixed.
Run after generating the initial board. Does not route traces or change circuitry.
"""
from pathlib import Path
import json,random,math
root=Path(__file__).resolve().parents[1]
a=json.loads((root/'placement_geometry.json').read_text())
fixed={'U1','SW1','J1','J2','J3','J4','H1','H2','ANT1','Y1','C114','C115','L102','L104','Q1','Q6','U6','U7','L1','L2','U10','L100','C102','L101','C103','C101','C104','C105','C106','C107','U5','Q3','C5','U3','C7','Q5','C8','C9','R22','R23','R24','C10','C11','C12','D2','C13','R14','R15','U8','U9','C14','C17','R3','R4'}
# The ESP32 and RF trace need an uninterrupted ground reference underneath.
obstacles=[{'ref':'RF_CLEAR','side':'Top','x':0,'y':0,'box':[0,0,6.0,6.0]}, {'ref':'RF_CLEAR','side':'Bottom','x':0,'y':0,'box':[0,0,6.0,6.0]}, {'ref':'MCU_GROUND','side':'Bottom','x':0,'y':0,'box':[18.3,5.7,26.7,14.0]}]
obstacles += [{'ref':'CLOCK_GROUND','side':'Bottom','x':0,'y':0,'box':[19,0.4,25,5.5]}]
for i in a:
 if i['ref'].startswith('H'):
  i['box']=[-2.4,-2.4,2.4,2.4];j=i.copy();j['side']='Bottom';obstacles.append(j)
for i in a:i['tx']=i['x'];i['ty']=i['y']
move=[i for i in a if i['ref'] not in fixed]
random.seed(20261111)
best=None;bestcost=1e20
# Per-item cost only checks its pairwise interactions, so proposed moves are cheap.
def cost(i):
 x0=i['x']+i['box'][0];y0=i['y']+i['box'][1];x1=i['x']+i['box'][2];y1=i['y']+i['box'][3]
 c=1800*(max(0,.3-x0)**2+max(0,.3-y0)**2+max(0,x1-59.7)**2+max(0,y1-19.7)**2)
 c+=.45*((i['x']-i['tx'])**2+(i['y']-i['ty'])**2)
 for j in a+obstacles:
  if j is i or j['side']!=i['side']:continue
  if j['ref']=='RF_CLEAR' and i['ref'] in ['ANT1','L104']:continue
  dx=min(x1+.04,j['x']+j['box'][2])-max(x0-.04,j['x']+j['box'][0])
  dy=min(y1+.04,j['y']+j['box'][3])-max(y0-.04,j['y']+j['box'][1])
  if dx>0 and dy>0:c+=2000*dx*dy+500*min(dx,dy)
 return c
for step in range(300000):
 i=random.choice(move);oldx,oldy=i['x'],i['y'];before=cost(i)
 temp=max(.02,10*(1-(step%75000)/75000)**2)
 scale=.12 if step%4 else 1.5
 i['x']=round(oldx+random.gauss(0,scale),2);i['y']=round(oldy+random.gauss(0,scale),2)
 after=cost(i)
 if after>before and random.random()>math.exp(min(0,(before-after)/temp)):i['x'],i['y']=oldx,oldy
 if step%50000==0:
  total=sum(cost(i) for i in a)
  print(step,round(total,2),flush=True)
  if total<bestcost:bestcost=total;best=[(i['x'],i['y']) for i in a]
for i,xy in zip(a,best):i['x'],i['y']=xy
out={i['ref']:[round(i['x'],2),round(i['y'],2),i['rot'],i['side']] for i in a if not i['ref'].startswith('H')}
(root/'placement.json').write_text(json.dumps(out,indent=2)+'\n')
print('Saved packed placement; KiCad DRC remains authoritative',bestcost)
