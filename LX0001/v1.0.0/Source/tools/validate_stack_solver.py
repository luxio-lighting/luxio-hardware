import json,hashlib,subprocess,os,math,sys,tempfile
from pathlib import Path
temporary=tempfile.TemporaryDirectory(prefix='lx0001-solver-');r=Path(temporary.name);src=Path(__file__).resolve().parents[1];board=src/'LX0001.kicad_pcb';h=hashlib.sha256(board.read_bytes()).hexdigest();results=[]
for name,masks,source,sink,vias,expected in [
 ('one_outer_square',[[1,1],[0,0],[0,0],[0,0]],[[0,0,0]],[[0,0,1]],[],1.724e-8/35e-6),
 ('parallel_outer_inner',[[1,1],[1,1],[0,0],[0,0]],[[0,0,0],[1,0,0]],[[0,0,1],[1,0,1]],[],1.724e-8/(50.2e-6)),
 ('full_barrel',[[1,0],[1,0],[1,0],[1,0]],[[0,0,0]],[[3,0,0]],[{'x':0,'y':0,'x_mm':0,'y_mm':0,'drill_mm':.3,'uuid':'test-via'}],1.724e-8*.0015512/(math.pi*.00032*.00002)),
 ('disconnected_layers',[[1,0],[0,0],[0,0],[1,0]],[[0,0,0]],[[3,0,0]],[],None)]:
 m={'board_path':str(board),'board_sha256':h,'shape':[4,1,2],'copper_thickness_um':[35,15.2,15.2,35],'copper_z_mm':[.0175,.253,1.3332,1.5687],'segments':{'TEST':{'source_ref':'A','sink_ref':'B','masks':masks,'source':source,'sink':sink,'vias':vias}}};(r/(name+'.json')).write_text(json.dumps(m))
 a=subprocess.run([sys.executable,str(src/'tools/current_stack_solve.py'),str(r/(name+'.json')),'--report',str(r/(name+'.txt')),'--json-output',str(r/(name+'-result.json'))],capture_output=True,text=True)
 if a.returncode not in [0,2]:raise RuntimeError(a.stderr)
 out=json.loads((r/(name+'-result.json')).read_text())
 if expected is None:assert a.returncode==2 and not out['successful'];measured=None
 else:
  measured=out['totals'][0]['resistance_mohm']/1000;assert a.returncode==0 and out['successful'] and abs(measured/expected-1)<1e-8,(name,measured,expected)
 results.append({'case':name,'expected_ohm':expected,'measured_ohm':measured,'pass':True})
(src.parent/'Export/Validation/full-stack-solver-check.json').write_text(json.dumps({'solver_sha256':hashlib.sha256((src/'tools/current_stack_solve.py').read_bytes()).hexdigest(),'cases':results,'pass':True},indent=2)+'\n');print(json.dumps(results,indent=2))

temporary.cleanup()
