"""Rebuild fabrication outputs only after connectivity and electrical-rule release checks pass."""
from pathlib import Path
import subprocess,json,csv,collections,re,hashlib,zipfile,shutil,tempfile,datetime
root=Path(__file__).resolve().parents[2];src=root/'Source';out=root/'Export'
cli='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli';py='/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3'
board=str(src/'LX0001.kicad_pcb');sch=str(src/'LX0001.kicad_sch')
for cmd in [
 [cli,'pcb','drc','--schematic-parity','--all-track-errors','--format','json','-o',str(out/'drc.json'),board],
 [cli,'pcb','drc','--schematic-parity','--all-track-errors','-o',str(out/'drc.txt'),board],
 [cli,'sch','erc','--format','json','-o',str(out/'erc.json'),sch],
 [cli,'sch','export','netlist','--format','kicadxml','-o',str(out/'netlist.xml'),sch],
 [py,str(src/'tools/verify_design.py')],
 [py,str(src/'tools/verify_stackup.py')]]:subprocess.run(cmd,check=True)
drc=json.loads((out/'drc.json').read_text());erc=json.loads((out/'erc.json').read_text())
assert not drc['unconnected_items'],'Unrouted connections block fabrication export'
assert not drc.get('schematic_parity'),'Schematic/PCB mismatch blocks export'
assert not drc['violations'], 'Any DRC error, warning or exclusion blocks fabrication export'
assert all(not s.get('violations') for s in erc.get('sheets',[])), 'ERC findings block export'
ger=Path(tempfile.mkdtemp(prefix='.gerbers-staging-',dir=out))
for cmd in [
 [cli,'pcb','export','gerbers','--layers','F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts','--use-drill-file-origin','-o',str(ger)+'/',board],
 [cli,'pcb','export','drill','--drill-origin','plot','--excellon-separate-th','--excellon-units','mm','-o',str(ger)+'/',board],
 [cli,'pcb','export','pos','--side','both','--format','csv','--units','mm','--use-drill-file-origin','--smd-only','--exclude-dnp','-o',str(out/'kicad-positions.csv'),board],
 [cli,'sch','export','pdf','-o',str(out/'schematic.pdf'),sch]]:subprocess.run(cmd,check=True)
parts=json.loads((src/'parts.json').read_text());groups=collections.defaultdict(list);wanted=set()
for v in parts:
 if v['lcsc'] and not v.get('dnp'):
  groups[v['value'],v['footprint'],v['lcsc']].append(v['ref']);wanted.add(v['ref'])
with (out/'JLCPCB-BOM.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['Comment','Designator','Footprint','LCSC Part #','Quantity'])
 for (value,fp,lcsc),refs in sorted(groups.items(),key=lambda x:x[0][2]):w.writerow([value,','.join(sorted(refs)),fp,lcsc,len(refs)])
positions=list(csv.DictReader((out/'kicad-positions.csv').open()));assert {r['Ref'] for r in positions}==wanted
with (out/'JLCPCB-CPL.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['Designator','Mid X','Mid Y','Layer','Rotation'])
 for r in positions:w.writerow([r['Ref'],r['PosX'],r['PosY'],r['Side'].title(),r['Rot']])
with zipfile.ZipFile(out/'LX0001-v1.0.0-Gerbers.zip','w',zipfile.ZIP_DEFLATED) as z:
 for f in sorted(ger.iterdir()):z.write(f,f.name)
if (out/'Gerbers').exists():
 history=root/'Assets'/'review-history'/'previous-exports';history.mkdir(parents=True,exist_ok=True)
 (out/'Gerbers').rename(history/('Gerbers-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
ger.rename(out/'Gerbers')
for name,layers,mirror in [('assembly-top','F.Fab,F.SilkS,Edge.Cuts',False),('assembly-bottom','B.Fab,B.SilkS,Edge.Cuts',True),('copper-top','F.Cu,F.Mask,F.SilkS,Edge.Cuts',False),('copper-bottom','B.Cu,B.Mask,B.SilkS,Edge.Cuts',True)]:
 cmd=[cli,'pcb','export','svg','--layers',layers,'--mode-single','--page-size-mode','2','--exclude-drawing-sheet','-o',str(out/(name+'.svg')),board]
 if mirror:cmd.insert(-1,'--mirror')
 subprocess.run(cmd,check=True)
 subprocess.run(['/opt/homebrew/bin/rsvg-convert','-w','2400','-o',str(out/(name+'.png')),str(out/(name+'.svg'))],check=True)
files=sorted(src.glob('*.kicad_*'))+[src/'parts.json',src/'connections.csv']
status={'date':'2026-11-11','status':'FABRICATION DATA CHECKED; UNBUILT FIRST ARTICLE; NOT PRODUCTION-QUALIFIED','board_mm':[66.5,20,1.6],'copper_layers':4,'soldermask':'black','assembled_parts':len(wanted),'bom_lines':len(groups),'open_connections':0,'electrical_drc_errors':0,'erc_findings':0,'documented_mechanical_flags':0,'source_sha256':{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.suffix!='.kicad_prl'}}
(out/'verification.json').write_text(json.dumps(status,indent=2)+'\n')
print('Fabrication files generated; prototype electrical, thermal, RF and USB validation remains required')
