"""Render the exported case meshes; no geometry is invented or modified.

Run with the CAD virtual environment's Python. Optional --pcb-glb supplies the
full KiCad PCB GLB (metres, X/height/PCB-Y axes) for original component colors.
Without that file, the verified PCB reference STL is rendered in one color.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import trimesh
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--case-dir", type=Path,
                    default=Path(__file__).resolve().parents[3] / "Enclosure/v1.0.0/Export/Case")
parser.add_argument("--pcb-glb", type=Path, default=Path("/tmp/lx0002-full.glb"))
args = parser.parse_args()
case_dir = args.case_dir.resolve()
parameters = json.loads((case_dir / "verification.json").read_text())["parameters"]

# Each entry contains actual mesh vertices/faces and its original material color.
pcb_meshes = []
pcb_reference = trimesh.load_mesh(case_dir / "pcb-reference.stl", process=False) if (case_dir / "pcb-reference.stl").exists() else None
if args.pcb_glb.exists() and pcb_reference is not None:
    scene = trimesh.load(args.pcb_glb, force="scene", process=False)
    grouped_meshes = defaultdict(list)
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        vertices = np.asarray(mesh.vertices) * 1000.0
        vertices = vertices[:, [0, 2, 1]]
        vertices[:, 1] *= -1
        vertices[:, 2] -= 1.6012 + parameters["floor_outer_z_mm"]
        # GLB (X, height, PCB-Y) -> CAD (X, -PCB-Y, height) is a rotation,
        # determinant +1. Keep the original winding and physical handedness.
        mesh.vertices = vertices
        material = getattr(mesh.visual, "material", None)
        color = getattr(material, "baseColorFactor", None)
        if color is None:
            color = getattr(material, "diffuse", [100, 100, 100, 255])
        color = tuple(int(c) for c in color[:3])
        grouped_meshes[color].append(mesh)
    for color, meshes in grouped_meshes.items():
        combined = trimesh.util.concatenate(meshes)
        pcb_meshes.append((combined, color))
    bounds = np.array([np.min([m.bounds[0] for m, _ in pcb_meshes], axis=0),
                       np.max([m.bounds[1] for m, _ in pcb_meshes], axis=0)])
    bounds_error = np.abs(bounds - pcb_reference.bounds)
    # GLB includes bottom copper/mask visualization absent from the STEP body.
    # Only the lower Z bound receives that allowance; XY and top stay strict.
    allowed_error = np.full((2, 3), 0.025)
    allowed_error[0, 2] = 0.10
    if np.any(bounds_error > allowed_error):
        raise ValueError(f"Colored PCB bounds differ from case reference: {bounds}")
    print(f"Using original PCB materials from {args.pcb_glb}: {len(pcb_meshes)} colors")
elif pcb_reference is not None:
    pcb_meshes.append((pcb_reference, (60, 66, 65)))
    print("PCB GLB unavailable; using the exact PCB reference STL in one color")

for view in ("closed", "exploded", "inside"):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.957, 0.965, 0.973)
    renderer.SetUseFXAA(True)
    renderer.SetAutomaticLightCreation(False)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(True)
    window.SetSize(1800, 1200)
    window.SetMultiSamples(8)
    window.AddRenderer(renderer)

    if view == "inside":
        base = trimesh.load_mesh(case_dir / "base.stl", process=False)
        lid = trimesh.load_mesh(case_dir / "lid.stl", process=False)
        lid.apply_translation([0, base.bounds[1, 1] + 10, 0])
        meshes = [(base, (63, 68, 76)), (lid, (192, 198, 206))]
    else:
        base = trimesh.load_mesh(case_dir / "base-assembly.stl", process=False)
        lid = trimesh.load_mesh(case_dir / "lid-assembly.stl", process=False)
        if view == "exploded":
            lid.apply_translation([0, 0, 16.0])
        meshes = [(base, (63, 68, 76)), (lid, (192, 198, 206))] + pcb_meshes

    for mesh, color in meshes:
        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(np.asarray(mesh.vertices, dtype=np.float64), deep=True))
        cells = vtk.vtkCellArray()
        cells.SetData(numpy_to_vtkIdTypeArray(np.arange(len(mesh.faces)+1, dtype=np.int64)*3,
                                             deep=True),
                      numpy_to_vtkIdTypeArray(np.asarray(mesh.faces, dtype=np.int64).ravel(),
                                             deep=True))
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(cells)
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(polydata)
        normals.SetFeatureAngle(45)
        normals.SplittingOn()
        normals.ConsistencyOn()
        normals.ComputePointNormalsOn()
        normals.ComputeCellNormalsOff()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        material = actor.GetProperty()
        material.SetColor(*(channel / 255 for channel in color))
        material.SetInterpolationToPhong()
        material.SetAmbient(0.24)
        material.SetDiffuse(0.72)
        material.SetSpecular(0.18)
        material.SetSpecularPower(35)
        renderer.AddActor(actor)

    bounds = renderer.ComputeVisiblePropBounds()
    center = np.array([(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2,
                       (bounds[4]+bounds[5])/2])
    span = max(bounds[1]-bounds[0], bounds[3]-bounds[2], bounds[5]-bounds[4])
    camera = renderer.GetActiveCamera()
    # Equal axis components give an orthographic isometric view. The input end
    # is in the lower left; positive X runs up and right toward the outputs.
    camera.SetPosition(*(center + np.array([-1.0, -1.0, 1.0]) * span * 3))
    camera.SetFocalPoint(*center)
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    # Fit the actual projected meshes with a fixed margin; the exploded lid
    # must not be clipped when the board length or model height changes.
    view_direction = np.array([1.0, 1.0, -1.0]) / np.sqrt(3.0)
    screen_right = np.cross(view_direction, np.array([0.0, 0.0, 1.0]))
    screen_right /= np.linalg.norm(screen_right)
    screen_up = np.cross(screen_right, view_direction)
    vertices = np.concatenate([np.asarray(mesh.vertices) for mesh, _ in meshes]) - center
    projected_x = vertices @ screen_right
    projected_y = vertices @ screen_up
    center += screen_right * (projected_x.min()+projected_x.max())/2
    center += screen_up * (projected_y.min()+projected_y.max())/2
    camera.SetPosition(*(center - view_direction * span * 3))
    camera.SetFocalPoint(*center)
    camera.SetParallelScale(max(np.ptp(projected_y)/2, np.ptp(projected_x)/(2*1.5))*1.12)
    renderer.ResetCameraClippingRange()
    for position, intensity in [((-0.8, -1.2, 2.0), 0.8),
                                ((1.0, 0.2, 1.5), 0.5),
                                ((-0.1, 1.0, 0.7), 0.25)]:
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(*(center + np.array(position) * span * 3))
        light.SetFocalPoint(*center)
        light.SetIntensity(intensity)
        light.SetPositional(False)
        renderer.AddLight(light)

    # Screen-space ambient occlusion provides contact shading without adding
    # a floor, supports, fasteners, or any other geometry absent from the CAD.
    steps = vtk.vtkRenderStepsPass()
    occlusion = vtk.vtkSSAOPass()
    occlusion.SetDelegatePass(steps)
    occlusion.SetRadius(2.0)
    occlusion.SetBias(0.015)
    occlusion.SetKernelSize(128)
    occlusion.BlurOn()
    renderer.SetPass(occlusion)
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()
    output = case_dir / f"case-{view}.png"
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(output))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()
    print(output)
