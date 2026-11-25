"""Check the two-layer DC solver against analytic resistor networks, not a PCB."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--report',type=Path,default=Path(__file__).resolve().parents[2]/'Export/Validation/current-solver-check.json')
parser.add_argument('--solver',type=Path,default=Path(__file__).with_name('current_path_solve.py'))
args=parser.parse_args()
solver=args.solver
rho=1.724e-8
sheet=rho/35e-6
barrel=rho*.0016/(math.pi*(.0003+.000025)*.000025)
checks=[]
with tempfile.TemporaryDirectory(prefix='lx0002-current-model-') as temporary:
    work=Path(temporary)
    board=work/'analytic-network-fixture.bin';board.write_bytes(b'Analytic resistor network; this is not a PCB.')
    for name,source,sink,vias,expected in [
        ('four_squares_plus_one_barrel',[[0,0,0]],[[1,0,4]],[{'x':4,'y':0,'x_mm':4.5,'y_mm':.5,'drill_mm':.3,'kind':'routing_via'}],4*sheet+barrel),
        ('two_four_square_layers_parallel',[[0,0,0],[1,0,0]],[[0,0,4],[1,0,4]],[],2*sheet),
        ('disconnected_layers',[[0,0,0]],[[1,0,4]],[],None),
    ]:
        mesh={'board_path':str(board),'board_sha256':hashlib.sha256(board.read_bytes()).hexdigest(),'power_source':'analytic_test','shape':[2,1,5],'resolution_mm':1,'origin_mm':[0,0],'copper_thickness_um':[35.0,35.0],'segments':{'USB_5V':{'source_ref':'SOURCE','sink_ref':'SINK','masks':[[1]*5,[1]*5],'source':source,'sink':sink,'vias':vias}}}
        path=work/(name+'.json');path.write_text(json.dumps(mesh));out=work/(name+'-results.json')
        result=subprocess.run([sys.executable,str(solver),str(path),'--report',str(work/(name+'.txt')),'--json-output',str(out)],capture_output=True,text=True)
        data=json.loads(out.read_text())
        if expected is None:
            assert result.returncode==2 and not data['successful'] and not data['totals'], 'Disconnected path accepted'
            checks.append({'case':name,'passed':True,'expected':'disconnected rejected'})
        else:
            assert result.returncode==0 and data['successful'],result.stderr+result.stdout
            actual=data['totals'][0]['resistance_mohm']/1000
            relative=abs(actual-expected)/expected
            assert relative<1e-7,(name,actual,expected,relative)
            checks.append({'case':name,'passed':True,'expected_ohm':expected,'actual_ohm':actual,'relative_error':relative})
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'result':'PASS','scope':'Analytic resistor-network numerical checks only; no LX0002 board analysis','solver_sha256':hashlib.sha256(solver.read_bytes()).hexdigest(),'checks':checks},indent=2)+'\n')
print('PASS: series barrel, parallel layers, and disconnected-network checks')
