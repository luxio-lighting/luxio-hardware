"""Render the actual KiCad GLB in orthographic views; no generated geometry."""
from pathlib import Path
from collections import defaultdict
import argparse
import hashlib
import json
import numpy as np
import trimesh
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--glb', type=Path, default=root / 'Export/LX0002-assembled.glb')
parser.add_argument('--output', type=Path, default=root / 'Export')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
scene = trimesh.load(args.glb, force='scene', process=False)
grouped = defaultdict(list)
for node in scene.graph.nodes_geometry:
    transform, name = scene.graph[node]
    mesh = scene.geometry[name].copy()
    mesh.apply_transform(transform)
    # KiCad GLB metres: (X, height, drawing-Y). This conversion is a rotation,
    # determinant +1; never reflect the populated board.
    mesh.vertices = np.asarray(mesh.vertices)[:, [0, 2, 1]] * np.array([1000, -1000, 1000])
    material = getattr(mesh.visual, 'material', None)
    color = getattr(material, 'baseColorFactor', None)
    if color is None:
        color = getattr(material, 'diffuse', [90, 90, 90, 255])
    grouped[tuple(int(channel) for channel in color[:3])].append(mesh)
meshes = [(trimesh.util.concatenate(values), color) for color, values in grouped.items()]
bounds = np.array([np.min([mesh.bounds[0] for mesh, _ in meshes], axis=0),
                   np.max([mesh.bounds[1] for mesh, _ in meshes], axis=0)])
center = bounds.mean(axis=0)
span = float(np.max(bounds[1] - bounds[0]))
views = [
    ('isometric-top', False, [-1, -1, 1], [0, 0, 1]),
    ('isometric-bottom', True, [-1, -1, 1], [0, 0, 1]),
    ('centered-input-end', False, [-1, 0, .25], [0, 0, 1]),
    ('top', False, [0, 0, 1], [0, 1, 0]),
    ('bottom', True, [0, 0, 1], [0, 1, 0]),
]
for name, flip, direction, up in views:
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(.957, .965, .973)
    renderer.SetUseFXAA(True)
    renderer.SetAutomaticLightCreation(False)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(True)
    window.SetSize(1800, 1100)
    window.SetMultiSamples(8)
    window.AddRenderer(renderer)
    for original, color in meshes:
        mesh = original.copy()
        if flip:
            # Exactly 180 degrees about the board's long X axis.
            mesh.vertices = (np.asarray(mesh.vertices)-center) * [1, -1, -1] + center
        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(np.asarray(mesh.vertices, dtype=np.float64), deep=True))
        cells = vtk.vtkCellArray()
        cells.SetData(numpy_to_vtkIdTypeArray(np.arange(len(mesh.faces)+1, dtype=np.int64)*3, deep=True),
                      numpy_to_vtkIdTypeArray(np.asarray(mesh.faces, dtype=np.int64).ravel(), deep=True))
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(cells)
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(polydata)
        normals.SetFeatureAngle(45)
        normals.SplittingOn()
        normals.ConsistencyOn()
        normals.ComputePointNormalsOn()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*(channel/255 for channel in color))
        prop.SetInterpolationToPhong()
        prop.SetAmbient(.24)
        prop.SetDiffuse(.72)
        prop.SetSpecular(.18)
        prop.SetSpecularPower(35)
        renderer.AddActor(actor)
    camera = renderer.GetActiveCamera()
    camera.SetPosition(*(center + np.asarray(direction)*span*3))
    camera.SetFocalPoint(*center)
    camera.SetViewUp(*up)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    camera.Zoom(1.12)
    renderer.ResetCameraClippingRange()
    for vector, intensity in [([-1, -1.5, 2], .85), ([1, .3, 1.5], .5), ([0, 1, .5], .25)]:
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(*(center + np.asarray(vector)*span*3))
        light.SetFocalPoint(*center)
        light.SetIntensity(intensity)
        light.SetPositional(False)
        renderer.AddLight(light)
    steps = vtk.vtkRenderStepsPass()
    ambient = vtk.vtkSSAOPass()
    ambient.SetDelegatePass(steps)
    ambient.SetRadius(1.5)
    ambient.SetBias(.015)
    ambient.SetKernelSize(128)
    ambient.BlurOn()
    renderer.SetPass(ambient)
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()
    target = args.output / ('preview-' + name + '.png')
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(target))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()
    print(target, flush=True)
(args.output / 'render-verification.json').write_text(json.dumps({
    'source_glb': str(args.glb), 'source_glb_sha256': hashlib.sha256(args.glb.read_bytes()).hexdigest(),
    'bounds_mm': bounds.tolist(), 'material_groups': len(meshes),
    'projection': 'orthographic; isometric camera has equal axis components',
    'underside_transform': '180-degree rotation about long X axis; determinant +1',
    'views': [name for name, _, _, _ in views],
}, indent=2) + '\n')
