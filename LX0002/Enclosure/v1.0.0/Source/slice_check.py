"""Slice the two oriented case STLs offline and audit the generated layer paths.

Run with Python3 + NumPy + Pillow. Bambu Studio is never asked to connect to a
printer. G-code stays in a temporary reference directory; it is not a release
print file. Bundled X1 Carbon / PLA Basic presets are reference settings only.
"""
from pathlib import Path
import argparse, collections, hashlib, json, math, re, shutil, subprocess, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bambu', default='/Applications/BambuStudio.app/Contents/MacOS/BambuStudio')
parser.add_argument('--profiles', default='/Applications/BambuStudio.app/Contents/Resources/profiles/BBL')
parser.add_argument('--case-dir', type=Path, default=Path(__file__).resolve().parents[3]/'Enclosure/v1.0.0/Export/Case')
parser.add_argument('--output', type=Path)
parser.add_argument('--parameters', type=Path, default=Path(__file__).resolve().parent/'parameters.json')
args = parser.parse_args()
parameters=json.loads(args.parameters.read_text())
layer_mm=float(parameters['layer_mm'])
nozzle_mm=float(parameters['nozzle_mm'])
assert 0.05<=layer_mm<=0.3 and nozzle_mm==0.4, 'Reference printer requires a0.4mm nozzle'
out = args.output or args.case_dir/'Validation'
out.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix='lx0002-reference-slice-'))
profiles = Path(args.profiles)
settings = {}
provenance = {}
for kind, name in [('machine','Bambu Lab X1 Carbon 0.4 nozzle'),('process','0.20mm Standard @BBL X1C'),('filament','Bambu PLA Basic @BBL X1C')]:
    queue=[name]; stack=[]; resolved={}; files=[]
    while queue:
        n=queue.pop(); source=profiles/kind/(n+'.json')
        d=json.loads(source.read_text()); stack.append(d); files.append(str(source))
        if d.get('inherits'): queue.append(d['inherits'])
    for d in reversed(stack):
        for inc in d.get('include',[]):
            source=profiles/kind/(inc+'.json')
            resolved.update(json.loads(source.read_text())); files.append(str(source))
        resolved.update(d)
    for key in ['inherits','include','setting_id']: resolved.pop(key,None)
    if kind=='process':
        original_layer_mm=float(resolved['layer_height'])
        bottom_mm=max(float(resolved.get('bottom_shell_thickness','0')),int(resolved['bottom_shell_layers'])*original_layer_mm)
        top_mm=max(float(resolved.get('top_shell_thickness','0')),int(resolved['top_shell_layers'])*original_layer_mm)
        resolved.update(enable_support='0', brim_type='no_brim', layer_height=str(layer_mm), initial_layer_print_height=str(layer_mm), bottom_shell_layers=str(math.ceil(bottom_mm/layer_mm-1e-6)), top_shell_layers=str(math.ceil(top_mm/layer_mm-1e-6)), bottom_shell_thickness=f'{bottom_mm:g}', top_shell_thickness=f'{top_mm:g}', name=f'LX0002 {layer_mm:.2f}mm PLA no-support reference', print_settings_id=f'LX0002 {layer_mm:.2f}mm PLA no-support reference')
    settings[kind]=work/(kind+'.json')
    settings[kind].write_text(json.dumps(resolved,indent=2)+'\n')
    shutil.copy2(settings[kind],out/(kind+'-reference.json'))
    provenance[kind]={'name':name,'source_files':files}
    if kind=='process': provenance[kind]['overrides']={k:resolved[k] for k in ['enable_support','brim_type','layer_height','initial_layer_print_height','bottom_shell_layers','top_shell_layers','bottom_shell_thickness','top_shell_thickness','name','print_settings_id']}
summary={'purpose':'Offline support-free slicing review; X1C reference settings, not a machine-specific print release.', 'slicer':'Bambu Studio', 'reference_presets':provenance, 'temporary_gcode_directory':str(work), 'layer_mm':layer_mm,'initial_layer_mm':layer_mm,'nozzle_mm':nozzle_mm,'supports_enabled':False,'parts':{},'physical_print_tested':False}
for name in ['base','lid']:
    source=args.case_dir/(name+'.stl'); source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    partwork=work/name; partwork.mkdir()
    command=[args.bambu,'--debug','3','--datadir',str(work/'data'),'--load-settings',str(settings['machine'])+';'+str(settings['process']),'--load-filaments',str(settings['filament']),'--orient','0','--arrange','1','--slice','0','--outputdir',str(partwork),str(source.resolve())]
    with (out/(name+'-slice.log')).open('w') as log:
        completed=subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT)
    result=json.loads((partwork/'result.json').read_text())
    assert completed.returncode==0 and result['return_code']==0, result
    shutil.copy2(partwork/'result.json',out/(name+'-slicer-result.json'))
    gcode=(partwork/'plate_1.gcode').read_text()
    assert re.search(r'^; enable_support = 0$',gcode,re.M)
    assert abs(float(re.search(r'^; layer_height = (.+)$',gcode,re.M).group(1))-layer_mm)<.0001
    assert abs(float(re.search(r'^; initial_layer_print_height = (.+)$',gcode,re.M).group(1))-layer_mm)<.0001
    summary['slicer_version']=re.search(r'^; BambuStudio (.+)$',gcode,re.M).group(1)
    layers={}; xyz=[0.,0.,0.]; absolute_xy=True; relative_e=True; e=0.; width=.42; feature='Custom'; z=None
    for line in gcode.splitlines():
        if line.startswith('; Z_HEIGHT:'):
            z=float(line.split(':',1)[1]); layers.setdefault(z,[])
        elif line.startswith('; FEATURE:'): feature=line.split(':',1)[1].strip()
        elif line.startswith('; LINE_WIDTH:'): width=float(line.split(':',1)[1])
        code=line.split(';',1)[0].strip()
        if not code: continue
        words=code.split(); op=words[0]
        if op=='G90': absolute_xy=True
        elif op=='G91': absolute_xy=False
        elif op=='M82': relative_e=False
        elif op=='M83': relative_e=True
        fields={k:float(v) for k,v in re.findall(r'([XYZIJE])([-+]?(?:\d*\.\d+|\d+))',code)}
        if op=='G92':
            if 'E' in fields: e=fields['E']
            for k,key in enumerate('XYZ'):
                if key in fields: xyz[k]=fields[key]
            continue
        if op not in ['G0','G1','G2','G3']: continue
        end=[fields.get(key,xyz[k]) if absolute_xy else xyz[k]+fields.get(key,0) for k,key in enumerate('XYZ')]
        extrusion=fields.get('E',0) if relative_e else fields.get('E',e)-e
        if 'E' in fields: e=e+fields['E'] if relative_e else fields['E']
        if z is not None and extrusion>0 and feature not in ['Custom','Flush','Skirt','Brim','Prime tower'] and math.dist(xyz[:2],end[:2])>.0001:
            points=[xyz[:2],end[:2]]
            if op in ['G2','G3'] and ('I' in fields or 'J' in fields):
                center=[xyz[0]+fields.get('I',0),xyz[1]+fields.get('J',0)]
                radius=math.dist(xyz[:2],center); a=math.atan2(xyz[1]-center[1],xyz[0]-center[0]); b=math.atan2(end[1]-center[1],end[0]-center[0])
                sweep=(b-a)%(2*math.pi) if op=='G3' else -((a-b)%(2*math.pi))
                steps=max(2,math.ceil(abs(sweep)*radius/.05))
                points=[[center[0]+radius*math.cos(a+sweep*i/steps),center[1]+radius*math.sin(a+sweep*i/steps)] for i in range(steps+1)]
                points[0]=xyz[:2]; points[-1]=end[:2]
            layers[z].append({'xy':points,'width':width,'feature':feature})
        xyz=end
    heights=sorted(layers)
    assert heights and all(layers[h] for h in heights)
    layer_steps=np.diff([0.]+heights)
    assert all(abs(step-layer_mm)<.001 for step in layer_steps[:-1])
    assert layer_mm/2<=layer_steps[-1]<=layer_mm+.001, 'Unexpected final-layer height'
    feature_counts=collections.Counter(path['feature'] for paths in layers.values() for path in paths)
    assert not any('support' in f.lower() for f in feature_counts)
    allpoints=np.array([pt for paths in layers.values() for path in paths for pt in path['xy']])
    low=allpoints.min(0)-1.; high=allpoints.max(0)+1.; pixel=.05
    size=tuple(np.ceil((high-low)/pixel).astype(int)+1)
    previous=None; layer_audit=[]; bridge_paths=[]; images={}
    for index,h in enumerate(heights):
        mask=Image.new('1',size,0); draw=ImageDraw.Draw(mask)
        color=Image.new('RGB',size,'#f7f8fa'); cd=ImageDraw.Draw(color)
        for path in layers[h]:
            pts=[tuple(np.rint((np.array(pt)-low)/pixel).astype(int)) for pt in path['xy']]
            w=max(1,round(path['width']/pixel)); draw.line(pts,fill=1,width=w,joint='curve')
            for pt in [pts[0],pts[-1]]: draw.ellipse((pt[0]-w/2,pt[1]-w/2,pt[0]+w/2,pt[1]+w/2),fill=1)
            c='#e56b28' if path['feature']=='Bridge' else '#176b93' if 'wall' in path['feature'] else '#76a6b4'
            cd.line(pts,fill=c,width=w,joint='curve')
            if path['feature']=='Bridge':
                prior=np.asarray(previous,dtype=bool) if previous is not None else np.zeros((size[1],size[0]),dtype=bool)
                longest_gap=0.;gap=0.
                for a,b in zip(path['xy'],path['xy'][1:]):
                    distance=math.dist(a,b);samples=max(1,math.ceil(distance/.025))
                    for sample in range(samples):
                        fraction=(sample+.5)/samples
                        point=np.array(a)+(np.array(b)-np.array(a))*fraction
                        xx,yy=np.rint((point-low)/pixel).astype(int)
                        backed=0<=xx<size[0] and 0<=yy<size[1] and bool(prior[yy,xx])
                        gap=0. if backed else gap+distance/samples
                        longest_gap=max(longest_gap,gap)
                bridge_paths.append({'z_mm':h,'length_mm':sum(math.dist(a,b) for a,b in zip(path['xy'],path['xy'][1:])),'maximum_unbacked_centerline_run_mm':round(longest_gap,4),'unsupported_span_method':'0.025mm centerline samples against preceding extrusion footprint at0.05mm raster resolution; extrusion move length includes anchors.','start_xy':path['xy'][0],'end_xy':path['xy'][-1]})
        filled=np.asarray(mask,dtype=bool)
        # Connected components by row runs; overlap with the previous layer is
        # tested with a 0.10 mm raster tolerance. This detects whole floating
        # islands, not mechanical strength or every small local overhang.
        parents={}; contacts={}; areas={}; prior_runs=[]; next_id=0
        support=np.asarray(previous.filter(ImageFilter.MaxFilter(5)),dtype=bool) if previous is not None else np.ones_like(filled)
        for yy,row in enumerate(filled):
            changes=np.diff(np.r_[False,row,False].astype(int)); starts=np.flatnonzero(changes==1); ends=np.flatnonzero(changes==-1)
            current=[]
            for left,right in zip(starts,ends):
                root=next_id; next_id+=1; parents[root]=root; contacts[root]=bool(support[yy,left:right].any());areas[root]=int(right-left)
                for pl,pr,pid in prior_runs:
                    if pr<left or pl>right: continue
                    a=root;b=pid
                    while parents[a]!=a: a=parents[a]
                    while parents[b]!=b: b=parents[b]
                    if a!=b:
                        parents[b]=a;contacts[a]=contacts[a] or contacts[b];areas[a]+=areas[b]
                current.append((left,right,root))
            prior_runs=current
        roots=[r for r in parents if parents[r]==r]
        floating=[{'area_mm2':areas[r]*pixel*pixel} for r in roots if not contacts[r] and areas[r]*pixel*pixel>.02]
        layer_audit.append({'layer':index+1,'z_mm':h,'extrusion_moves':len(layers[h]),'extruded_area_mm2':float(filled.sum()*pixel*pixel),'path_components':len(roots),'floating_components':floating,'outside_previous_layer_plus_0_10mm_mm2':float((filled & ~support).sum()*pixel*pixel) if previous is not None else 0.})
        previous=mask
        if index in {0,1,round(.4/layer_mm)-1,round(.4/layer_mm),round(1.6/layer_mm)-1,len(heights)//2,len(heights)-1} or any(path['feature']=='Bridge' for path in layers[h]): images[h]=color
    canvas=Image.new('RGB',(1440,math.ceil(len(images)/2)*340),'white'); pane=ImageDraw.Draw(canvas)
    for i,(h,im) in enumerate(images.items()):
        im.thumbnail((700,290)); x=(i%2)*720;y=(i//2)*340
        canvas.paste(im,(x+10,y+35));pane.text((x+12,y+10),f'{name}: layer {round(h/layer_mm)}, Z={h:.2f} mm (orange = bridge)',fill='black')
    canvas.save(out/(name+'-layer-review.png'))
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash, 'CAD changed during this check; rerun'
    floating=[{'z_mm':r['z_mm'],'components':r['floating_components']} for r in layer_audit if r['floating_components']]
    part={'stl_sha256':source_hash,'gcode_sha256':hashlib.sha256(gcode.encode()).hexdigest(),'command':command,'slicer_result':result,'layers':len(heights),'layer_z_mm':heights,'feature_move_counts':dict(feature_counts),'bridge_paths':bridge_paths,'whole_floating_islands':floating,'raster_pixel_mm':pixel,'support_contact_tolerance_mm':.10,'layer_audit':layer_audit}
    part['nominal_mesh_height_mm']=round(result['sliced_plates'][0]['objects'][0]['bbox']['height'],3)
    part['last_print_z_mm']=heights[-1]
    part['height_quantization_mm']=round(heights[-1]-part['nominal_mesh_height_mm'],3)
    (out/(name+'-layer-audit.json')).write_text(json.dumps(part,indent=2)+'\n')
    summary['parts'][name]={k:v for k,v in part.items() if k not in ['layer_audit','command','slicer_result','layer_z_mm']}
    summary['parts'][name]['slicer_warning']=result['sliced_plates'][0].get('warning_message','')
    summary['parts'][name]['filament_g']=result['sliced_plates'][0]['filaments'][0]['total_used_g']
    summary['parts'][name]['model_print_seconds']=result['sliced_plates'][0]['main_predication']
    assert not floating, f'{name}: floating path islands need review'
summary['bridge_assessment']={}
for name,record in summary['parts'].items():
    summary['bridge_assessment'][name]={'bridge_layer_z_mm':sorted({path['z_mm'] for path in record['bridge_paths']}),'maximum_bridge_labeled_move_mm':max([path['length_mm'] for path in record['bridge_paths']] or [0]),'maximum_unbacked_centerline_run_mm':max([path['maximum_unbacked_centerline_run_mm'] for path in record['bridge_paths']] or [0])}
summary['interpretation']='Supports-disabled slicing succeeds. Raster connectivity checks for whole floating islands; bridge paths are listed for visual review. This does not validate snap durability, PLA diaphragm force, tolerances, bed adhesion, or a physical print.'
(out/'slice-verification.json').write_text(json.dumps(summary,indent=2)+'\n')
readme=f'Offline Bambu Studio reference slicing: PLA / {nozzle_mm:g} mm nozzle / {layer_mm:g} mm first and subsequent layers.\nSupports disabled. Reference machine: X1 Carbon. Select the actual printer and filament before printing.\nThe portable 3MF contains geometry only, with no machine preset or G-code.\nReference G-code remains only in {work}. Do not send it to an unspecified printer.\nRerun Enclosure/v1.0.0/Source/slice_check.py and export_print_3mf.py after CAD changes.\nLayer JSON and PNGs inspect actual extrusion paths. Whole-island support uses 0.05 mm raster pixels and 0.10 mm contact tolerance.\n'
for name,record in summary['parts'].items():
    readme+=f"{name}: {record['layers']} layers; CAD height {record['nominal_mesh_height_mm']:g} mm; last print Z {record['last_print_z_mm']:g} mm; {len(record['whole_floating_islands'])} floating islands.\n"
readme+=f"Solid shell settings: {bottom_mm:g} mm bottom ({math.ceil(bottom_mm/layer_mm-1e-6)} layers), {top_mm:g} mm top ({math.ceil(top_mm/layer_mm-1e-6)} layers).\n"
for name,assessment in summary['bridge_assessment'].items():
    readme+=f"{name}: maximum bridge-labeled move {assessment['maximum_bridge_labeled_move_mm']:.3f} mm; maximum sampled unbacked run {assessment['maximum_unbacked_centerline_run_mm']:.3f} mm. Move lengths include supported anchors.\n"
readme+='Bridge paths and layer images are listed for visual review.\nThis LX0002 enclosure has not yet been physically printed or fit-tested. Snap durability, fit, button force and bed adhesion require physical testing.\n'
(out/'README.txt').write_text(readme)
print(json.dumps({name:{key:value for key,value in record.items() if key in ['layers','whole_floating_islands','bridge_paths','filament_g','slicer_warning']} for name,record in summary['parts'].items()},indent=2))
