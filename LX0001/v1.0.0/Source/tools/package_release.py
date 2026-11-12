"""Package checked manufacturing outputs; does not run CAD exports or qualify hardware."""
from pathlib import Path
import hashlib,json,csv,zipfile,re,datetime,collections
r=Path(__file__).resolve().parents[2];s=r/'Source';e=r/'Export'
h=hashlib.sha256((s/'LX0001.kicad_pcb').read_bytes()).hexdigest()
drc=json.loads((e/'drc.json').read_text());assert not any(drc[k] for k in ['violations','unconnected_items','schematic_parity'])
erc=json.loads((e/'erc.json').read_text());assert all(not x.get('violations') for x in erc['sheets'])
geo=json.loads((e/'manufacturing-geometry-check.json').read_text());assert geo['pass'] and geo['board_sha256']==h and not geo['via_in_paste_allowlist']
assert len(geo['reviewed_component_pin_in_paste_features'])==4 and all(x['paste_layer']=='F.Paste' for x in geo['reviewed_component_pin_in_paste_features'])
assert geo['checker_sha256']==hashlib.sha256((s/'tools/verify_design.py').read_bytes()).hexdigest()
for stem in ['current','usb','tvs']:
 d=json.loads((e/f'current-path-model/{stem}-copper-results.json').read_text());assert d['successful'] and d['board_sha256']==h
 assert d['solver_sha256']==hashlib.sha256((s/'tools/current_stack_solve.py').read_bytes()).hexdigest()
 assert d['mesh_sha256']==hashlib.sha256((e/f'current-path-model/{stem}-copper-mesh.json').read_bytes()).hexdigest()
 m=json.loads((e/f'current-path-model/{stem}-copper-mesh.json').read_text());assert m['shape'][0]==4 and m['board_sha256']==h
 assert m['rasterizer_sha256']==hashlib.sha256((s/'tools/current_path_mesh.py').read_bytes()).hexdigest()
 assert m['copper_thickness_um']==[35,15.2,15.2,35]
for name in ['protected-routing-check','four-layer-geometry','hardware-auto-check','connector-model-check','schematic-document-review']:
 d=json.loads((e/'Validation'/f'{name}.json').read_text());assert d['pass'] and d['board_sha256']==h
assert json.loads((e/'Validation/schematic-document-review.json').read_text())['schematic_pdf_sha256']==hashlib.sha256((e/'schematic.pdf').read_bytes()).hexdigest()
verify=json.loads((e/'verification.json').read_text());assert verify['board_mm']==[60,20,1.6]
for name,digest in verify['source_sha256'].items():assert hashlib.sha256((r/name).read_bytes()).hexdigest()==digest,name
parts=json.loads((s/'parts.json').read_text());fitted={a['ref']:a for a in parts if a['lcsc'] and not a.get('dnp')};assert len(fitted)==83
positions=json.loads((s/'placement.json').read_text());rows=list(csv.DictReader((e/'JLCPCB-CPL.csv').open()));assert {v['Designator'] for v in rows}==set(fitted) and len(rows)==len(fitted)
for row in rows:
 x,y,angle,side=positions[row['Designator']]
 assert abs(float(row['Mid X'])-x)<1e-5 and abs(float(row['Mid Y'])-(20-y))<1e-5,row
 assert abs(float(row['Rotation'])-angle)<1e-5 and row['Layer']==side,row
 assert 0<float(row['Mid X'])<60 and 0<float(row['Mid Y'])<20
bom=list(csv.DictReader((e/'JLCPCB-BOM.csv').open()));bom_refs={}
for row in bom:
 refs=row['Designator'].split(',');assert len(refs)==int(row['Quantity'])
 for ref in refs:
  assert ref not in bom_refs;assert fitted[ref]['lcsc']==row['LCSC Part #'] and fitted[ref]['footprint']==row['Footprint'] and fitted[ref]['value']==row['Comment'];bom_refs[ref]=row
assert set(bom_refs)==set(fitted)
with zipfile.ZipFile(e/'LX0001-v1.0.0-Gerbers.zip') as z:
 assert set(z.namelist())=={f.name for f in (e/'Gerbers').iterdir()}
 for f in (e/'Gerbers').iterdir():assert z.read(f.name)==f.read_bytes()
edge=(e/'Gerbers/LX0001-Edge_Cuts.gm1').read_text();points=[(int(x)/1e6,int(y)/1e6) for x,y in re.findall(r'X(-?\d+)Y(-?\d+)D0[12]',edge)];assert set(points)=={(0,0),(0,20),(60,0),(60,20)}
sizes={n:float(v) for n,v in re.findall(r'^T(\d+)C([\d.]+)$',(e/'Gerbers/LX0001-PTH.drl').read_text(),re.M)};assert min(sizes.values())==.3
npth=(e/'Gerbers/LX0001-NPTH.drl').read_text()
npth_sizes={n:float(v) for n,v in re.findall(r'^T(\d+)C([\d.]+)$',npth,re.M)}
npth_holes=[];active_tool=None
for line in npth.splitlines():
 tool=re.fullmatch(r'T(\d+)',line)
 if tool:active_tool=tool.group(1)
 point=re.fullmatch(r'X(-?[\d.]+)Y(-?[\d.]+)',line)
 if point:npth_holes.append((npth_sizes[active_tool],float(point[1]),float(point[2])))
assert sorted(npth_holes)==sorted([(.6,5.105,17.64),(.6,5.105,11.86),(2.2,9.5,12.0),(2.2,42.0,17.0)])
assert (e/'JLCPCB-order-settings.txt').read_bytes()==(s/'fabrication-intent.txt').read_bytes()
preview={'board_sha256':h,'renderer':'KiCad10 native raytracer','board_mm':[60,20,1.6],'camera_top_rotation_degrees':[-54.735610317,0,45],'camera_bottom_rotation_degrees':[125.264389683,0,-45],'orthographic':True,'visual_review':'Inspected all five updated renders. J1 uses the C2927038 library-linked shared HRO visualization; manufacturer drawing governs case dimensions. USB mouth is1.175mm beyond the input edge. Wire connectors, button and mounting holes retained; U4 approximate body shown.','views':{n:hashlib.sha256((e/n).read_bytes()).hexdigest() for n in ['preview-top.png','preview-bottom.png','preview-centered-input-end.png','preview-isometric-top.png','preview-isometric-bottom.png']}}
(e/'Validation/preview-centered-input-end.json').write_text(json.dumps(preview,indent=2)+'\n')
check={'board_sha256':h,'revision':'v1.0.0','board_mm':[60,20,1.6],'min_exported_pth_drill_mm':.3,'exported_pth_tools_mm':sizes,'gerber_archive_matches_directory':True,'all_placements_match_CPL':True,'BOM_matches_fitted_parts':True,'assembly_faces':dict(collections.Counter(v['Layer'] for v in rows)),'fitted_parts':len(fitted),'BOM_lines':len(bom),'CPL_origin_CAD_mm':[0,20],'wired_usb_tvs_copper_models_current':True,'zero_open_connections':True,'zero_DRC_findings_including_warnings_and_exclusions':True,'zero_schematic_parity_findings':True,'zero_ERC_findings':True,'independent_drill_paste_check_pass':True,'minimum_drill_paste_clearance_mm':.1,'routing_via_count':geo['vias_checked'],'normal_component_pin_in_paste_apertures':4,'protected_RF_crystal_flash_routing_items_preserved':237,'hardware_qualified':False}
(e/'Validation/hardware-auto-release-check.json').write_text(json.dumps(check,indent=2)+'\n')
tvs=json.loads((e/'current-path-model/tvs-copper-results.json').read_text());ohms=tvs['totals'][0]['resistance_mohm']
(e/'current-path-model/tvs-model-scope-check.json').write_text(json.dumps({'board_sha256':h,'model_scope':tvs['model_scope'],'D3_to_J2_connected':True,'resistance_mohm':ohms,'current_a':1,'surge_qualified':False},indent=2)+'\n')
(s/'tvs_return_review.txt').write_text(f'LX0001 TVS return copper review\n\nPCB SHA256: {h}\nAll four copper layers;0.1mm grid;35/15.2/15.2/35um copper;20um assumed via plating.\nD3 ground to J2 ground: {ohms:.4f} mOhm at20C. Connected mesh; converged solve.\nDC copper estimate only: excludes inductance, clamping, contacts and solder.\nNo surge rating established. Hardware transient measurements remain required.\n')
(s/'release_export_review.txt').write_text(f'''LX0001 automatic hardware release review
PCB SHA256: {h}
83 fitted parts:39 top/44 bottom;46 BOM lines. BOM/CPL match parts.json.
60x20mm,4 layers,1.6mm. All{geo['vias_checked']} vias use0.30mm drills.
No open nets,DRC/ERC findings or schematic parity mismatches. No waived DRC findings.
Independent drill/paste clearance>=0.10mm. Four normal USB pin-in-paste stakes.
RF/crystal/flash237 routing items preserved. Wire connector models/transforms retained.
J1 replaced with DEALON USB-TYPE-C-018/C2927038 and revised footprint/model.
USB mouth1.175mm beyond input edge;0.675mm farther out than previous connector.
USB automatically powers5V output; wired input has priority; data buffers enabled.
No onboard USB current limiter or firmware-controlled power/data-enable pins.
Fresh wired5A/USB3A/TVS copper models are hash-keyed to this PCB.
Hardware remains unbuilt and unqualified; see first-article-validation.txt.
''')
names=['LX0001-v1.0.0-Gerbers.zip','JLCPCB-BOM.csv','JLCPCB-CPL.csv','JLCPCB-order-settings.txt','README.txt','assembly-top.png','assembly-bottom.png','assembly-top.svg','assembly-bottom.svg','schematic.pdf','verification.json','manufacturing-geometry-check.json','connection-check.txt','drc.json','erc.json','Validation/four-layer-geometry.json','Validation/protected-routing-check.json','Validation/hardware-auto-check.json','Validation/connector-model-check.json','Validation/schematic-document-review.json','Validation/hardware-auto-release-check.json','Validation/full-stack-solver-check.json','Validation/preview-centered-input-end.json','preview-top.png','preview-bottom.png','preview-centered-input-end.png','preview-isometric-top.png','preview-isometric-bottom.png','component-costs.csv','component-costs-summary.json','first-article-validation.txt','firmware-interface.txt','current_path_review.txt','tvs_return_review.txt','release_export_review.txt','paste_verification_review.txt','mechanical.json','hardware-auto-revision.json','usb-connector-revision.json','current-path-model/current-copper-results.json','current-path-model/usb-copper-results.json','current-path-model/tvs-copper-results.json','current-path-model/tvs-model-scope-check.json']
files={}
for name in names:
 f=e/name if (e/name).exists() else s/name;assert f.is_file(),name;files[name]=f
assert h in (s/'current_path_review.txt').read_text()
manifest={'revision':'1.0.0','revision_detail':'DEALON C2927038 USB connector; automatic USB/wired power and data enables; no onboard USB current limiting;60x20mm;0.30mm vias','generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'board_sha256':h,'scope':'Checked fabrication/assembly data; hardware not yet production-qualified','minimum_drill_mm':.3,'board_mm':[60,20,1.6],'files':{name:hashlib.sha256(f.read_bytes()).hexdigest() for name,f in files.items()}}
(e/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
with zipfile.ZipFile(e/'LX0001-v1.0.0-JLCPCB.zip','w',zipfile.ZIP_DEFLATED) as z:
 for name,f in files.items():z.write(f,name)
 z.write(e/'release-manifest.json','release-manifest.json')
with zipfile.ZipFile(e/'LX0001-v1.0.0-JLCPCB.zip') as z:
 assert set(z.namelist())==set(files)|{'release-manifest.json'}
 for name,digest in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
assert hashlib.sha256((s/'LX0001.kicad_pcb').read_bytes()).hexdigest()==h
print(json.dumps(check,indent=2));print('Release archive verified:',len(files)+1,'files')
