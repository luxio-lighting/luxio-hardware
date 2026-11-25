"""Portable geometry-only 3MF. No printer profile, executable G-code or supports.
Both original STLs retain their supplied print orientation; lid moves 35 mm in Y.
"""
from pathlib import Path
import hashlib, json, struct, zipfile, subprocess, tempfile
import numpy as np
import trimesh
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[3]
out=root/'Enclosure/v1.0.0/Export/Case'
parameters=json.loads((Path(__file__).resolve().parent/'parameters.json').read_text())
layer_mm=float(parameters['layer_mm']);nozzle_mm=float(parameters['nozzle_mm'])
ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
ET.register_namespace('',ns)
model=ET.Element('{'+ns+'}model',{'unit':'millimeter','{http://www.w3.org/XML/1998/namespace}lang':'en-US'})
for key,value in [('Title','LX0002 base and lid - print oriented'),('Description',f'Geometry only. PLA, {nozzle_mm:g} mm nozzle, {layer_mm:g} mm layers were reference-sliced without supports. Select your actual printer and filament, then slice. No G-code included.'),('Application','LX0002 export_print_3mf.py')]:
    ET.SubElement(model,'{'+ns+'}metadata',{'name':key}).text=value
resources=ET.SubElement(model,'{'+ns+'}resources');build=ET.SubElement(model,'{'+ns+'}build');audit={}
for index,name in enumerate(['base','lid'],1):
    raw=(out/(name+'.stl')).read_bytes();count=struct.unpack_from('<I',raw,80)[0]
    assert len(raw)==84+50*count, 'Expected binary STL exported by enclosure.py'
    vertices=[];triangles=[];lookup={}
    for i in range(count):
        triangle=[]
        for j in range(3):
            point=struct.unpack_from('<fff',raw,84+50*i+12+12*j)
            if point not in lookup:lookup[point]=len(vertices);vertices.append(point)
            triangle.append(lookup[point])
        triangles.append(triangle)
    obj=ET.SubElement(resources,'{'+ns+'}object',{'id':str(index),'type':'model','name':name})
    mesh=ET.SubElement(obj,'{'+ns+'}mesh');vs=ET.SubElement(mesh,'{'+ns+'}vertices');ts=ET.SubElement(mesh,'{'+ns+'}triangles')
    for x,y,z in vertices:ET.SubElement(vs,'{'+ns+'}vertex',{'x':format(x,'.8g'),'y':format(y,'.8g'),'z':format(z,'.8g')})
    for a,b,c in triangles:ET.SubElement(ts,'{'+ns+'}triangle',{'v1':str(a),'v2':str(b),'v3':str(c)})
    offset_y=35*(index-1)
    ET.SubElement(build,'{'+ns+'}item',{'objectid':str(index),'transform':f'1 0 0 0 1 0 0 0 1 0 {offset_y} 0'})
    audit[name]={'stl_sha256':hashlib.sha256(raw).hexdigest(),'vertices':len(vertices),'triangles':len(triangles),'translation_mm':[0,offset_y,0]}
content_types=b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
rels=b'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
output=out/'LX0002-case-print-layout.3mf'
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('[Content_Types].xml',content_types);archive.writestr('_rels/.rels',rels)
    archive.writestr('3D/3dmodel.model',ET.tostring(model,encoding='utf-8',xml_declaration=True))
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    assert not any('gcode' in p.lower() for p in archive.namelist())
    document=ET.fromstring(archive.read('3D/3dmodel.model'))
    assert len(document.find('{'+ns+'}build'))==2
(out/'Validation').mkdir(exist_ok=True)
roundtrip=[]
for index,name in enumerate(['base','lid'],1):
    element=document.find('{'+ns+'}resources').findall('{'+ns+'}object')[index-1].find('{'+ns+'}mesh')
    vertices=np.array([[float(vertex.get(axis)) for axis in ['x','y','z']] for vertex in element.find('{'+ns+'}vertices')])
    faces=np.array([[int(triangle.get(axis)) for axis in ['v1','v2','v3']] for triangle in element.find('{'+ns+'}triangles')])
    mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0
    original=trimesh.load(out/(name+'.stl'),force='mesh',process=False)
    expected=original.triangles.reshape((-1,3))
    restored=vertices[faces].reshape((-1,3))
    error=float(np.max(np.abs(expected-restored)))
    assert error<1e-5
    roundtrip.append({'part':name,'maximum_vertex_roundtrip_error_mm':error,'build_transform_determinant':1,'translation_only':True,'watertight':True,'winding_consistent':True})
work=Path(tempfile.mkdtemp(prefix='lx0002-3mf-import-'))
command=['/Applications/BambuStudio.app/Contents/MacOS/BambuStudio','--debug','3','--datadir',str(work/'data'),'--orient','0','--arrange','0','--info',str(output.resolve())]
result=subprocess.run(command,cwd=work,capture_output=True,text=True)
log=result.stdout+result.stderr
(out/'Validation/portable-3mf-import.log').write_text(log)
assert result.returncode==0 and log.count('manifold = yes')==2 and log.count('number_of_parts =  1')==2, 'Bambu 3MF import failed'
(out/'Validation/portable-3mf.json').write_text(json.dumps({'file':output.name,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'geometry_only':True,'units':'mm','models':audit,'mesh_roundtrip_checks':roundtrip,'bambu_cli_import':{'succeeded':True,'manifold_models':2,'model_count':2,'log':'portable-3mf-import.log','command':command}},indent=2)+'\n')
print(output)
