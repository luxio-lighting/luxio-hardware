"""LX0002 two-part screwless enclosure; build with CadQuery 2.8.
Construction uses the 2D PCB drawing's X/right and Y/down coordinates, mm.
Before export, both solids are converted to physical right-handed CAD axes:
X unchanged, Y negated, Z up. The original PCB reference is never reflected.
The PCB STEP and connector dimension files remain unchanged.
"""
from pathlib import Path
import argparse, json, hashlib
import cadquery as cq
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=ROOT / 'Enclosure/v1.0.0/Export/Case')
parser.add_argument('--skip-pcb-reference', action='store_true', help='Build a draft case without the previous PCB model')
args = parser.parse_args()
OUT = args.output
assert not args.skip_pcb_reference or OUT != ROOT / 'Enclosure/v1.0.0/Export/Case', 'Put preliminary geometry in a separate output directory'
reference_file=ROOT/'Enclosure/v1.0.0/Assets/LX0002-assembled-mm.stl'
reference_available = reference_file.exists() and not args.skip_pcb_reference
if reference_available:
    provenance = json.loads((reference_file.parent/'assembled-export-verification.json').read_text())
    assert provenance['pcb_sha256'] == hashlib.sha256((ROOT/'PCB/v1.0.0/Source/LX0002.kicad_pcb').read_bytes()).hexdigest(), 'Stale PCB reference: use --skip-pcb-reference for a preliminary case'
    assert provenance['sha256'][reference_file.name] == hashlib.sha256(reference_file.read_bytes()).hexdigest()
OUT.mkdir(parents=True, exist_ok=True)
p = json.loads((Path(__file__).parent/'parameters.json').read_text())
mechanical = json.loads((ROOT/'PCB/v1.0.0/Source/mechanical.json').read_text())
length, width, pcb_thickness = mechanical['size_mm']
assert width == 20 and pcb_thickness == 1.6
p['outer_x_mm'] = [-p['pcb_end_overhang_mm'][0], length+p['pcb_end_overhang_mm'][1]]
p['button_xy_mm'] = mechanical['button_center']
xy = json.loads((ROOT/'Enclosure/v1.0.0/Assets/enclosure-geometry.json').read_text())
anchors = {'J1': mechanical['usb']['center'], 'J3': mechanical['output_centers'][0],
           'J4': mechanical['output_centers'][1], 'SW1': mechanical['button_center']}
xy['nominal_key_body_bounds_xy'] = {}
for ref, bounds in xy['key_body_bounds_relative_to_center_xy'].items():
    cx, cy = anchors[ref]
    xy['nominal_key_body_bounds_xy'][ref] = [cx+bounds[0], cy+bounds[1], cx+bounds[2], cy+bounds[3]]
button_window_web = (xy['nominal_key_body_bounds_xy']['J3'][0]-p['terminal_top_clearance_mm']
                     -p['button_xy_mm'][0]-p['button_membrane_size_mm'][0]/2)
assert button_window_web >= 2*p['nozzle_mm'], 'Button membrane needs a continuous printable roof web before the terminal opening'
for capture_x in p['pcb_edge_capture_centers_x_mm']:
    for snap_x in p['snap_centers_x_mm']:
        assert abs(capture_x-snap_x) >= (p['snap_beam_width_mm']+p['pcb_edge_capture_width_mm'])/2+.4, 'PCB capture must leave the case latch free to flex'
x0, x1 = p['outer_x_mm']; y0, y1 = p['outer_y_mm']
z0 = p['floor_outer_z_mm']; floor = p['floor_inner_z_mm']
roof = p['roof_inner_z_mm']; top = p['roof_outer_z_mm']
r = p['outer_corner_radius_mm']
side_clearance=p['pcb_side_clearance_mm']; inner_t=p['inner_wall_thickness_mm']; fit=p['wall_fit_clearance_mm']
left_inner=-side_clearance; left_outer=left_inner-inner_t
right_inner=20+side_clearance; right_outer=right_inner+inner_t
cap_left=left_outer-fit; cap_right=right_outer+fit
beam_w=p['snap_beam_width_mm']; slot_w=p['snap_slot_width_mm']; root_z=p['snap_root_z_mm']; tip_z=p['snap_tip_z_mm']
projection=fit+p['snap_engagement_mm']
boss_r=p['boss_diameter_mm']/2; pin_r=p['locating_pin_diameter_mm']/2
capture_z=p['pcb_capture_top_z_mm']; pin_tip=p['pin_tip_z_mm']
bx,by=p['button_xy_mm']
usb_center_z=p['usb_nominal_height_mm']/2+p['usb_opening_vertical_offset_mm']
usb_clearance=p['usb_clearance_per_side_mm']
end_y0=-p['end_wall_side_margin_mm']; end_y1=20+p['end_wall_side_margin_mm']
end_cut_y0=end_y0-p['end_wall_side_fit_mm']; end_cut_y1=end_y1+p['end_wall_side_fit_mm']

# The floor's outer flange is also the lid's seating stop.
base = cq.Workplane('XY').box(x1-x0,y1-y0,floor-z0,centered=(False,False,False)).translate((x0,y0,z0)).edges('|Z').fillet(r)
outer_limit = cq.Workplane('XY').box(x1-x0,y1-y0,top-z0,centered=(False,False,False)).translate((x0,y0,z0)).edges('|Z').fillet(r)
# Nested inner side walls leave room for inward snap deflection, outside the PCB.
for ya,yb in [(left_outer,left_inner),(right_inner,right_outer)]:
    wall = cq.Workplane('XY').box(length+.25,yb-ya,tip_z-floor,centered=(False,False,False)).translate((.1,ya,floor))
    base = base.union(wall)
# The base carries only the middle of each lower end face. The lid owns the
# complete outer corners, keeping both long faces continuous and flat.
# A 0.1mm gap to the inner sidewalls avoids a non-manifold edge-only junction;
# each wall has its own full-width bond to the floor.
base = base.union(cq.Workplane('XY').box(1.5,end_y1-end_y0,usb_center_z-floor,centered=(False,False,False)).translate((-1.5,end_y0,floor)))
base = base.union(cq.Workplane('XY').box(1.5,end_y1-end_y0,-.2-floor,centered=(False,False,False)).translate((length+.45,end_y0,floor)))
base = base.intersect(outer_limit)

# Rounded slots form four long vertical cantilevers. Their windows are hidden
# inside the continuous lid skirt when assembled.
for xc in p['snap_centers_x_mm']:
    for ya,yb,side in [(left_outer,left_inner,-1),(right_inner,right_outer,1)]:
        for sx in [xc-(beam_w+slot_w)/2,xc+(beam_w+slot_w)/2]:
            slot = cq.Workplane('XY').box(slot_w,inner_t+1.5,tip_z+1-(root_z+slot_w/2),centered=(False,False,False)).translate((sx-slot_w/2,ya-.7,root_z+slot_w/2))
            round_end = cq.Workplane('XZ').center(sx,root_z+slot_w/2).circle(slot_w/2).extrude(3,both=True).translate((0,(ya+yb)/2,0))
            base = base.cut(slot.union(round_end))
        if side == -1:
            profile=[(left_outer,tip_z-1.6),(left_outer-projection,tip_z-1.1),(left_outer-projection,tip_z-.6),(left_outer,tip_z)]
        else:
            profile=[(right_outer,tip_z-1.6),(right_outer+projection,tip_z-1.1),(right_outer+projection,tip_z-.6),(right_outer,tip_z)]
        hook = cq.Workplane('YZ',origin=(xc-(beam_w-.8)/2,0,0)).polyline(profile).close().extrude(beam_w-.8)
        base = base.union(hook)

for x,y in mechanical['mounting_holes'].values():
    boss=cq.Workplane('XY',origin=(x,y,floor)).circle(boss_r).extrude(-1.6-floor)
    pin=cq.Workplane('XY',origin=(x,y,-1.6)).circle(pin_r).extrude(pin_tip-.5+1.6)
    tip=cq.Workplane('XY',origin=(x,y,pin_tip-.5)).circle(pin_r).workplane(offset=.5).circle(max(.4,pin_r-.35)).loft()
    base=base.union(boss).union(pin).union(tip)

# Continuous outer cap. It prints exterior down, as an open cup.
lid=cq.Workplane('XY').box(x1-x0,y1-y0,top-floor,centered=(False,False,False)).translate((x0,y0,floor)).edges('|Z').fillet(r)
end_clear=p['inner_corner_end_clearance_mm']
cavity=cq.Workplane('XY').box(length+.45+2*end_clear,cap_right-cap_left,roof-floor+.2,centered=(False,False,False)).translate((-end_clear,cap_left,floor-.2)).edges('|Z').fillet(.35)
lid=lid.cut(cavity)
# The roof aligns with the terminal tops. USB needs a local higher ceiling;
# this leaves 0.90mm of roof and allows for upward PCB float.
usb_bounds=xy['nominal_key_body_bounds_xy']['J1']
usb_ceiling=p['usb_ceiling_z_mm']
if usb_ceiling>roof:
    usb_pocket=cq.Workplane('XY').box(usb_bounds[2]+usb_clearance,usb_bounds[3]-usb_bounds[1]+2*usb_clearance,usb_ceiling-roof+.01,centered=(False,False,False)).translate((0,usb_bounds[1]-usb_clearance,roof-.01))
    lid=lid.cut(usb_pocket)
# The parting joint stays on the end faces, with 1mm-wide corner returns.
# The connector openings still meet the open rim for support-free printing.
lid=lid.cut(cq.Workplane('XY').box(1.82,end_cut_y1-end_cut_y0,usb_center_z+p['end_seam_clearance_mm']-(floor-.1),centered=(False,False,False)).translate((-1.51,end_cut_y0,floor-.1)))
lid=lid.cut(cq.Workplane('XY').box(1.82,end_cut_y1-end_cut_y0,-.2+p['end_seam_clearance_mm']-(floor-.1),centered=(False,False,False)).translate((length+.15,end_cut_y0,floor-.1)))
# Close-fitting rounded USB profile, split across the two input end faces.
# DEALON width/height are dimensioned; corner R1.0 is inferred from the shared
# library model, with 0.30mm horizontal, 0.20mm lower and 0.40mm upper clearance.
# It is not an authenticated
# exact profile of the manufactured connector.
usb=cq.Workplane('YZ',origin=(-1.7,width/2,usb_center_z)).rect(p['usb_nominal_width_mm']+2*usb_clearance,p['usb_nominal_height_mm']+2*usb_clearance).extrude(2.5).edges('|X').fillet(p['usb_inferred_corner_radius_mm']+usb_clearance)
wireout=cq.Workplane('XY').box(2.5,17.4,5.1-(floor-.1),centered=(False,False,False)).translate((length,1.3,floor-.1))
base=base.cut(usb)
lid=lid.cut(usb).cut(wireout)
# Open connector tops allow a pin/tool to press all four wire releases.
body_bounds=xy['nominal_key_body_bounds_xy']; clear=p['terminal_top_clearance_mm']
# Use exactly the end-port Y limits and put the outboard round corners outside
# the case. Each terminal opening then has straight side faces through the end,
# rather than a sharp lip where a rounded roof window meets a rectangle.
for bb in [(body_bounds['J3'][0]-clear,1.3,x1+.9,18.7)]:
    access=cq.Workplane('XY').box(bb[2]-bb[0],bb[3]-bb[1],top-roof+.3,centered=(False,False,False)).translate((bb[0],bb[1],roof-.1)).edges('|Z').fillet(.8)
    lid=lid.cut(access)
# Relief for the PCB edge where the shallow input wall reaches slightly past X0.
relief=cq.Workplane('XY').box(.7,20.6,2.2,centered=(False,False,False)).translate((-.3,-.3,-1.9))
base=base.cut(relief);lid=lid.cut(relief)

for xc in p['snap_centers_x_mm']:
    for side in [-1,1]:
        if side==-1: profile=[(cap_left+.05,tip_z-1.8),(cap_left-p['snap_engagement_mm']-.3,tip_z-1.2),(cap_left-p['snap_engagement_mm']-.3,tip_z-.5),(cap_left+.05,tip_z+.1)]
        else: profile=[(cap_right-.05,tip_z-1.8),(cap_right+p['snap_engagement_mm']+.3,tip_z-1.2),(cap_right+p['snap_engagement_mm']+.3,tip_z-.5),(cap_right-.05,tip_z+.1)]
        recess=cq.Workplane('YZ',origin=(xc-(beam_w-.3)/2,0,0)).polyline(profile).close().extrude(beam_w-.3)
        lid=lid.cut(recess)

# The single pin locates the board; four perimeter seats/capture pads keep
# it level and trapped when closed. No roof pillar stiffens the button membrane.
for xc in p['pcb_edge_capture_centers_x_mm']:
    for ya,yb in [(left_outer,p['pcb_edge_capture_overlap_mm']),
                  (width-p['pcb_edge_capture_overlap_mm'],right_outer)]:
        seat=cq.Workplane('XY').box(p['pcb_edge_capture_width_mm'],yb-ya,-pcb_thickness-floor,centered=(False,False,False)).translate((xc-p['pcb_edge_capture_width_mm']/2,ya,floor))
        base=base.union(seat)
    for ya,yb in [(left_inner+fit,p['pcb_edge_capture_overlap_mm']),
                  (width-p['pcb_edge_capture_overlap_mm'],right_inner-fit)]:
        capture=cq.Workplane('XY').box(p['pcb_edge_capture_width_mm'],yb-ya,roof-capture_z+.01,centered=(False,False,False)).translate((xc-p['pcb_edge_capture_width_mm']/2,ya,capture_z))
        lid=lid.union(capture)

# Fingernail purchase points expose the base flange. The inner base wall
# remains behind each notch, so there is no direct opening to the PCB.
for yc in [y0+.5,y1-.5]:
    grip=cq.Workplane('XZ',origin=(0,yc,0)).polyline([(bx-4,floor-.1),(bx-4,floor+.4),(bx-3,floor+1.2),(bx+3,floor+1.2),(bx+4,floor+.4),(bx+4,floor-.1)]).close().extrude(1.2,both=True)
    lid=lid.cut(grip)

# A continuous, four-layer PLA diaphragm avoids an exposed slit and a separate
# button. Its center stem has0.60mm nominal rest clearance, allowing PCB float.
membrane_z=top-p['button_membrane_thickness_mm']
pocket=cq.Workplane('XY',origin=(bx,by,roof-.01)).ellipse(p['button_membrane_size_mm'][0]/2,p['button_membrane_size_mm'][1]/2).extrude(membrane_z-roof+.01)
lid=lid.cut(pocket)
plunger=cq.Workplane('XY',origin=(bx,by,p['button_tip_z_mm'])).circle(p['button_plunger_diameter_mm']/2).extrude(membrane_z-p['button_tip_z_mm']+.01)
lid=lid.union(plunger)
# Tiny recessed center mark lies above the solid stem, not the flexible ring.
mark=cq.Workplane('XY',origin=(bx,by,top-.2)).circle(p['button_plunger_diameter_mm']*.4).extrude(.3)
lid=lid.cut(mark)

# KiCad's top-view drawing has Y down. Keeping that sign with Z up in a
# right-handed CAD model would mirror the real PCB. Convert the constructed
# case here; all printable and editable exports then share the PCB STEP axes.
base=base.clean().mirror('XZ');lid=lid.clean().mirror('XZ')
assert len(base.solids().vals())==1 and base.val().isValid(), 'Base must be one valid solid'
assert len(lid.solids().vals())==1 and lid.val().isValid(), 'Lid must be one valid solid'
intersection=base.intersect(lid)
collision_volume=sum(s.Volume() for s in intersection.solids().vals())
assert collision_volume < 1e-6, f'Base/lid interference: {collision_volume}mm3'

# Native coordinates for editable assembly; positive Z puts base floor on ground.
base_assm=base.translate((0,0,-z0));lid_assm=lid.translate((0,0,-z0))
base_print=base.translate((-x0,y1,-z0))
lid_print=lid.rotate((0,0,0),(1,0,0),180).translate((-x0,-y0,top))
for name,obj in [('base',base_print),('lid',lid_print),('base-assembly',base_assm),('lid-assembly',lid_assm)]:
    cq.exporters.export(obj,str(OUT/f'{name}.stl'),tolerance=.035,angularTolerance=.12)
    if name in ['base','lid']: cq.exporters.export(obj,str(OUT/f'{name}.step'))
assembly=cq.Assembly(name='LX0002 screwless case')
assembly.add(base_assm,name='Base',color=cq.Color(.15,.19,.22))
assembly.add(lid_assm,name='Lid',color=cq.Color(.78,.81,.82))
assembly.export(str(OUT/'LX0002-case-assembly.step'))

# The exact PCB reference is optional during preliminary case construction.
# Final release requires verify_mechanical.py with the completed original STEP.
transform=np.eye(4);transform[2,3]=-1.6012-z0
assert np.linalg.det(transform[:3,:3])==1, 'Physical PCB reference must not be mirrored'
if reference_available:
    pcb=trimesh.load(reference_file,force='mesh',process=False)
    pcb.apply_transform(transform)
    pcb.export(OUT/'pcb-reference.stl')

mesh_checks={}
for name in ['base','lid']:
    mesh=trimesh.load(OUT/f'{name}.stl',force='mesh')
    mesh_checks[name]={'watertight':bool(mesh.is_watertight),'winding_consistent':bool(mesh.is_winding_consistent),'volume_mm3':float(mesh.volume),'bounds_mm':mesh.bounds.tolist(),'faces':len(mesh.faces),'connected_bodies':int(mesh.body_count)}
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0 and mesh.body_count==1

report={'pcb_sha256':hashlib.sha256((ROOT/'PCB/v1.0.0/Source/LX0002.kicad_pcb').read_bytes()).hexdigest(), 'parameters':p,'base_lid_overlap_mm3':collision_volume,'print_meshes':mesh_checks,'physical_fit_tested':False,'final_pcb_overlay_verified':False,'stage':'PRELIMINARY CASE GEOMETRY; final PCB overlay pending','coordinates':{'construction':'2D PCB drawing coordinates: X right, Y down; converted before export','physical_assembly':'Original KiCad STEP axes: X right, Y up in top view, Z toward top components; PCB top shifted above the base datum','construction_to_physical':'(x,y,z) -> (x,-y,z)','pcb_reference_available':reference_available,'pcb_reference_transform':transform.tolist(),'pcb_reference_transform_determinant':float(np.linalg.det(transform[:3,:3]))},'button_note':f'Continuous{p["button_membrane_size_mm"][0]}×{p["button_membrane_size_mm"][1]}mm elliptical membrane,{p["button_membrane_thickness_mm"]}mm thick PLA membrane;{p["button_tip_z_mm"]-2}mm nominal switch gap. No assumed housing-stop geometry; force/travel requires physical fit testing.','pcb_capture_gap_mm':1.6+capture_z,'intended_print_orientation':'STL base floor down; STL lid exterior roof down; no supports.'}
(OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
report['latch_estimate']={'beam_length_mm':tip_z-root_z,'thickness_mm':inner_t,'required_tip_deflection_mm':p['snap_engagement_mm'],'small_deflection_surface_strain_estimate':1.5*inner_t*p['snap_engagement_mm']/(tip_z-root_z)**2,'note':'First-order cantilever estimate only, no FEA or PLA fatigue qualification.'}
(OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
for filename,lid_dz in [('assembly.tsv',0),('exploded.tsv',16)]:
    (OUT/filename).write_text('# name\tSTL\tRGB\ttranslation mm\nBase\tbase-assembly.stl\t48,58,66\t0,0,0\nLid\tlid-assembly.stl\t195,204,209\t0,0,'+str(lid_dz)+'\n'+('PCB reference\tpcb-reference.stl\t35,80,50\t0,0,0\n' if reference_available else ''))
(OUT/'print-layout.tsv').write_text('# Printable parts, already oriented on bed\nBase\tbase.stl\t48,58,66\t0,0,0\nLid\tlid.stl\t195,204,209\t0,35,0\n')
print(json.dumps({'overlap_mm3':collision_volume,'mesh_checks':mesh_checks},indent=2))
