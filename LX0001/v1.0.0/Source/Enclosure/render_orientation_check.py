"""Show the original PCB and corrected base from above, using one camera.

This is a geometry render with labels, not a reconstruction from a photograph.
The PCB retains native KiCad STEP handedness; the only GLB axis conversion is
the determinant-positive rotation (X, Y, Z) = (GLB-X, -GLB-Z, GLB-Y).
"""
from pathlib import Path
from collections import defaultdict
import hashlib, json
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy

root = Path(__file__).resolve().parents[2]
out = root / 'Export/Enclosure/Case'
pcb_glb = Path('/tmp/lx0001-full.glb')
source = root / 'Export/Enclosure/LX0001-assembled-mm.stl'
parameters = json.loads((out/'verification.json').read_text())['parameters']
pcb = trimesh.load_mesh(source, process=False)
pcb.apply_translation((0, 0, -1.6012-parameters['floor_outer_z_mm']))
pcb_parts = [(pcb, (50, 90, 65))]
if pcb_glb.exists():
    scene = trimesh.load(pcb_glb, force='scene', process=False)
    colored = defaultdict(list)
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        mesh = scene.geometry[name].copy()
        mesh.apply_transform(transform)
        vertices = np.asarray(mesh.vertices)*1000
        vertices = vertices[:, [0, 2, 1]]
        vertices[:, 1] *= -1
        vertices[:, 2] -= 1.6012+parameters['floor_outer_z_mm']
        mesh.vertices = vertices
        material = getattr(mesh.visual, 'material', None)
        color = getattr(material, 'baseColorFactor', None)
        if color is None:
            color = getattr(material, 'diffuse', [100, 100, 100, 255])
        colored[tuple(int(c) for c in color[:3])].append(mesh)
    pcb_parts = [(trimesh.util.concatenate(meshes), color) for color, meshes in colored.items()]
base = trimesh.load_mesh(out/'base-assembly.stl', process=False)
width, height = 1100, 500
panels = []
label_points = []
for title, parts in [('PCB: components facing up', pcb_parts),
                     ('Corrected base: looking inside', [(base, (63, 68, 76))])]:
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(.957, .965, .973)
    renderer.SetUseFXAA(True)
    renderer.SetAutomaticLightCreation(False)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(True)
    window.SetSize(width, height)
    window.SetMultiSamples(8)
    window.AddRenderer(renderer)
    for mesh, color in parts:
        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(np.asarray(mesh.vertices, dtype=np.float64), deep=True))
        cells = vtk.vtkCellArray()
        cells.SetData(numpy_to_vtkIdTypeArray(np.arange(len(mesh.faces)+1, dtype=np.int64)*3, deep=True),
                      numpy_to_vtkIdTypeArray(np.asarray(mesh.faces, dtype=np.int64).ravel(), deep=True))
        data = vtk.vtkPolyData()
        data.SetPoints(points)
        data.SetPolys(cells)
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(data)
        normals.SetFeatureAngle(45)
        normals.SplittingOn()
        normals.ConsistencyOn()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*(c/255 for c in color))
        actor.GetProperty().SetAmbient(.25)
        actor.GetProperty().SetDiffuse(.75)
        renderer.AddActor(actor)
    camera = renderer.GetActiveCamera()
    camera.SetPosition(30.225, -10, 110)
    camera.SetFocalPoint(30.225, -10, 5)
    camera.SetViewUp(0, 1, 0)
    camera.ParallelProjectionOn()
    camera.SetParallelScale(16.5)
    renderer.ResetCameraClippingRange()
    for position, intensity in [((0, 20, 90), .8), ((50, -30, 90), .4)]:
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(*position)
        light.SetFocalPoint(30.225, -10, 5)
        light.SetIntensity(intensity)
        renderer.AddLight(light)
    steps = vtk.vtkRenderStepsPass()
    occlusion = vtk.vtkSSAOPass()
    occlusion.SetDelegatePass(steps)
    occlusion.SetRadius(2.0)
    occlusion.SetBias(.015)
    occlusion.SetKernelSize(128)
    occlusion.BlurOn()
    renderer.SetPass(occlusion)
    window.Render()
    pixels = vtk.vtkWindowToImageFilter()
    pixels.SetInput(window)
    pixels.SetInputBufferTypeToRGB()
    pixels.ReadFrontBufferOff()
    pixels.Update()
    array = vtk_to_numpy(pixels.GetOutput().GetPointData().GetScalars()).reshape(height, width, 3)
    panels.append(Image.fromarray(np.flipud(array)))
    labels = []
    for label, x, y, dx, dy in [('H1', 9.5, -8, 0, 42), ('H2', 42, -3, 0, -43),
                               ('USB-C', 0, -5.25, -20, -90), ('Wire input', 0, -15.25, -20, 105)]:
        renderer.SetWorldPoint(x, y, 6.8, 1)
        renderer.WorldToDisplay()
        sx, sy, _ = renderer.GetDisplayPoint()
        labels.append((label, sx, height-sy, dx, dy))
    label_points.append(labels)
    window.Finalize()

canvas = Image.new('RGB', (2240, 680), (244, 246, 248))
draw = ImageDraw.Draw(canvas)
font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 34)
small = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 25)
for index, title in enumerate(['PCB: components facing up', 'Corrected base: looking inside']):
    ox = 10+index*1120
    canvas.paste(panels[index], (ox, 70))
    draw.text((ox+25, 20), title, fill=(35, 40, 48), font=font)
    for label, x, y, dx, dy in label_points[index]:
        x += ox
        y += 70
        if label.startswith('H'):
            draw.ellipse((x-20, y-20, x+20, y+20), outline=(223, 108, 18), width=3)
        draw.line((x, y+(23 if dy>0 else -23), x+dx, y+dy), fill=(223, 108, 18), width=2)
        text_xy = (x+dx, y+dy+(4 if dy>0 else -4))
        anchor = 'mt' if dy>0 else 'mb'
        box = draw.textbbox(text_xy, label, anchor=anchor, font=small)
        draw.rounded_rectangle((box[0]-6, box[1]-4, box[2]+6, box[3]+4), radius=4,
                               fill=(244, 246, 248))
        draw.text(text_xy, label, anchor=anchor, fill=(114, 57, 9), font=small)
draw.text((35, 600), 'Same top view and scale. Input end left; output end right. H1 and H2 mark the mounting holes / locating pins.',
          fill=(55, 60, 68), font=small)
draw.text((35, 638), 'Corrected file orientation: USB-C above the input wire connector in this view.',
          fill=(75, 80, 88), font=small)
canvas.save(out/'orientation-check.png')
(out/'orientation-check.json').write_text(json.dumps({
    'pcb_source': str(source.relative_to(root)),
    'pcb_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'base_source': 'base-assembly.stl',
    'base_source_sha256': hashlib.sha256((out/'base-assembly.stl').read_bytes()).hexdigest(),
    'pcb_source_transform': 'Z translation only, +5.1988mm',
    'glb_mapping_if_available': '(X,-Z,Y)*1000 + (0,0,5.1988); determinant positive',
    'pcb_glb_sha256': hashlib.sha256(pcb_glb.read_bytes()).hexdigest() if pcb_glb.exists() else None,
    'camera': {'eye': [30.225,-10,110], 'target': [30.225,-10,5], 'up': [0,1,0], 'parallel_scale_mm':16.5},
    'landmarks_xy_mm': {'H1':[9.5,-8], 'H2':[42,-3], 'USB-C':[0,-5.25], 'wire_input':[0,-15.25]},
    'image_sha256': hashlib.sha256((out/'orientation-check.png').read_bytes()).hexdigest()
}, indent=2)+'\n')
print(out/'orientation-check.png')
