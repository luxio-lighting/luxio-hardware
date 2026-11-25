"""Convert the two retained simple VRML previews to matching STEP solids.

Uses the CAD virtual environment. Geometry and colors come from the existing
preview files; this does not turn approximate models into certified drawings.
"""
from pathlib import Path
import hashlib
import json
import re
import cadquery as cq

directory = Path(__file__).resolve().parents[1] / 'libraries/models'
records = []
for name in ['Walsin_RFECA3216060A1T_preview', 'SW_TS_1088_AR02016_preview']:
    source = directory / (name + '.wrl')
    text = source.read_text()
    assembly = cq.Assembly(name=name)
    solids = []
    if name.startswith('Walsin'):
        shapes = re.findall(r'Transform\s*\{\s*translation\s+([\d.eE+\-\s]+)\s+children.*?diffuseColor\s+([\d.eE+\-\s]+)\}.*?Box\s*\{\s*size\s+([\d.eE+\-\s]+)\}', text)
        assert len(shapes) == text.count('geometry Box') == 4
        for position, color, size in shapes:
            position = [float(value)*2.54 for value in position.split()]
            size = [float(value)*2.54 for value in size.split()]
            solid = cq.Workplane('XY').box(*size).translate(position).val()
            assert solid.isValid() and solid.Volume() > 0
            solids.append(solid)
            assembly.add(solid, name='part_' + str(len(solids)), color=cq.Color(*map(float, color.split())))
    else:
        shapes = re.findall(r'Shape\s*\{.*?diffuseColor\s+([\d.eE+\-\s]+)\s+specularColor.*?point\s*\[([^]]+)\].*?coordIndex\s*\[([^]]+)\]', text)
        assert len(shapes) == text.count('geometry IndexedFaceSet') == 5
        for color, coordinates, indices in shapes:
            values = [float(value)*2.54 for value in re.split(r'[\s,]+', coordinates.strip())]
            vertices = [cq.Vector(*values[index:index+3]) for index in range(0, len(values), 3)]
            faces = []
            for polygon in indices.split('-1'):
                polygon = [int(value) for value in re.split(r'[\s,]+', polygon.strip(' ,\n')) if value]
                if polygon:
                    faces.append(cq.Face.makeFromWires(cq.Wire.makePolygon([vertices[index] for index in polygon], close=True)))
            solid = cq.Solid.makeSolid(cq.Shell.makeShell(faces))
            assert solid.isValid() and solid.Volume() > 0
            solids.append(solid)
            assembly.add(solid, name='part_' + str(len(solids)), color=cq.Color(*map(float, color.split())))
    target = directory / (name + '.step')
    assembly.export(str(target))
    loaded = cq.importers.importStep(str(target)).val()
    assert loaded.isValid() and len(loaded.Solids()) == len(solids)
    box = loaded.BoundingBox()
    records.append({'source': source.name, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'step': target.name, 'step_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'solids': len(solids), 'bounds_mm': [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax],
                    'scope': 'Same approximate geometry as the retained VRML preview, converted at 2.54mm per WRL unit.'})
    print(target)
(directory / 'preview-step-conversion.json').write_text(json.dumps(records, indent=2) + '\n')
