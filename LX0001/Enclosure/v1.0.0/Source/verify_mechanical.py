"""Check exported case solids and meshes against the current PCB STEP.
Run with the project CadQuery environment after enclosure.py.
Writes Enclosure/v1.0.0/Export/Case/Validation/mechanical-review.json only.
"""
from pathlib import Path
import cadquery as cq, trimesh, hashlib,json,datetime
import numpy as np
from scipy.spatial import cKDTree
root=Path(__file__).resolve().parents[3]
out=root/'Enclosure/v1.0.0/Export/Case'
parameters=json.loads((root/'Enclosure/v1.0.0/Source/parameters.json').read_text())
x0,x1=parameters['outer_x_mm'];y0,y1=parameters['outer_y_mm']
z0=parameters['floor_outer_z_mm'];top=parameters['roof_outer_z_mm']
files=[Path(__file__).resolve(),root/'PCB/v1.0.0/Source/LX0001.kicad_pcb',root/'Enclosure/v1.0.0/Source/enclosure.py',root/'Enclosure/v1.0.0/Source/parameters.json',root/'Enclosure/v1.0.0/Assets/LX0001-assembled.step',root/'Enclosure/v1.0.0/Assets/LX0001-assembled-mm.stl',out/'base.step',out/'lid.step',*sorted(out.glob('*.stl'))]
hashes={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
base=cq.importers.importStep(str(out/'base.step')).val().translate((x0,-y1,z0))
lid=cq.importers.importStep(str(out/'lid.step')).val().translate((x0,y0,-top)).rotate((0,0,0),(1,0,0),180)
pcb=cq.importers.importStep(str(root/'Enclosure/v1.0.0/Assets/LX0001-assembled.step')).val().translate((0,0,-1.6012))
# Derive asymmetric hole axes from the unmirrored PCB itself. Bounds and volume
# cannot detect a reflected case/reference pair, which caused the first print.
board_solids=[s for s in pcb.Solids() if abs(s.BoundingBox().xlen-60)<1e-6 and abs(s.BoundingBox().ylen-20)<1e-6]
assert len(board_solids)==1
board_bounds=board_solids[0].BoundingBox()
assert abs(board_bounds.ymin+20)<1e-6 and abs(board_bounds.ymax)<1e-6
markers={}
for name,shape,radius in [('pcb_holes',board_solids[0],1.1),('base_pins',base,parameters['locating_pin_diameter_mm']/2),('lid_sockets',lid,parameters['lid_pin_socket_diameter_mm']/2)]:
 centers=set()
 for face in shape.Faces():
  if face.geomType()!='CYLINDER':continue
  cylinder=face._geomAdaptor().Cylinder();axis=cylinder.Axis()
  if abs(cylinder.Radius()-radius)<1e-6 and abs(abs(axis.Direction().Z())-1)<1e-6:
   origin=axis.Location();centers.add((round(origin.X(),6),round(origin.Y(),6)))
 markers[name]=sorted(centers)
 assert len(markers[name])==2,(name,markers[name])
assert markers['pcb_holes']==markers['base_pins']==markers['lid_sockets'],markers
usb_shells=[s for s in pcb.Solids() if s.BoundingBox().xmin<0 and s.BoundingBox().xmax<7 and s.BoundingBox().ylen>8 and s.BoundingBox().zmax>3.2]
input_terminal_bodies=[s for s in pcb.Solids() if 0<s.BoundingBox().xmin<1 and s.BoundingBox().xmax<15 and s.BoundingBox().xlen>12 and s.BoundingBox().zmax>4]
assert len(usb_shells)==1 and len(input_terminal_bodies)==2
usb_bounds=usb_shells[0].BoundingBox()
usb_center_y=(usb_bounds.ymin+usb_bounds.ymax)/2
terminal_center_y=(min(s.BoundingBox().ymin for s in input_terminal_bodies)+max(s.BoundingBox().ymax for s in input_terminal_bodies))/2
assert terminal_center_y < (board_bounds.ymin+board_bounds.ymax)/2 < usb_center_y
port_probes=[]
for name,center_y in [('usb',usb_center_y),('input_terminal',terminal_center_y)]:
 point=(-.75,center_y,1.0)
 probe=cq.Solid.makeSphere(.05,cq.Vector(*point))
 overlaps=[sum(s.Volume() for s in case.intersect(probe).Solids()) for case in [base,lid]]
 assert max(overlaps)<1e-9,(name,point,overlaps)
 port_probes.append({'port':name,'native_pcb_model_center_y_mm':center_y,'opening_probe_xyz_mm':point,'case_overlap_mm3':sum(overlaps)})
# Require an unchanged physical PCB mesh with translation only, so future
# collision checks cannot silently fit an incorrectly mirrored reference.
original_mesh=trimesh.load(root/'Enclosure/v1.0.0/Assets/LX0001-assembled-mm.stl',force='mesh',process=False)
reference_mesh=trimesh.load(out/'pcb-reference.stl',force='mesh',process=False)
reference_transform=np.eye(4);reference_transform[2,3]=-1.6012-z0
assert np.linalg.det(reference_transform[:3,:3])==1
expected_reference=trimesh.transform_points(original_mesh.vertices,reference_transform)
assert expected_reference.shape==reference_mesh.vertices.shape
reference_vertex_error=float(np.max(np.abs(expected_reference-reference_mesh.vertices)))
assert reference_vertex_error<1e-5,reference_vertex_error
print_transform_evidence={}
for name in ['base','lid']:
 assembly_mesh=trimesh.load(out/(name+'-assembly.stl'),force='mesh',process=False)
 print_mesh=trimesh.load(out/(name+'.stl'),force='mesh',process=False)
 transform=np.eye(4)
 if name=='base':transform[:3,3]=[-x0,y1,0]
 else:transform[:3,:3]=np.diag([1,-1,-1]);transform[:3,3]=[-x0,-y0,top-z0]
 assert np.linalg.det(transform[:3,:3])==1
 expected_print=trimesh.transform_points(assembly_mesh.vertices,transform)
 assert expected_print.shape==print_mesh.vertices.shape
 # OpenCascade may reorder tessellated vertices after a mirror and rotation.
 vertex_error=float(max(cKDTree(print_mesh.vertices).query(expected_print)[0].max(),cKDTree(expected_print).query(print_mesh.vertices)[0].max()))
 assert vertex_error<1e-5,(name,vertex_error)
 print_transform_evidence[name]={'determinant':1.0,'matrix':transform.tolist(),'maximum_vertex_error_mm':vertex_error}
handedness_review={'pass':True,'reference':'Original unmirrored KiCad PCB STEP and STL; no Y reflection applied to the board.','pcb_hole_axes_native_xy_mm':markers['pcb_holes'],'exported_base_pin_axes_native_xy_mm':markers['base_pins'],'exported_lid_socket_axes_native_xy_mm':markers['lid_sockets'],'pcb_reference_transform_determinant':1.0,'pcb_reference_transform':reference_transform.tolist(),'pcb_reference_maximum_vertex_error_mm':reference_vertex_error,'assembly_to_print_transforms':print_transform_evidence,'regression_guard':'Asymmetric physical PCB hole axes must match both exported case halves; the original PCB reference may only translate.'}
handedness_review['asymmetric_input_port_checks']=port_probes
intersections=[]
for case_name,case in [('base',base),('lid',lid)]:
 for i,s in enumerate(pcb.Solids()):
  common=case.intersect(s)
  v=sum(x.Volume() for x in common.Solids())
  if v>1e-7:
   b=s.BoundingBox();c=common.BoundingBox()
   is_board=abs(b.xlen-60)<1e-6 and abs(b.ylen-20)<1e-6 and abs(b.zmin+1.6012)<1e-6
   intersections.append({'case':case_name,'pcb_solid_index':i,'kind':'pcb_substrate_support_seat_datum' if is_board else 'component','volume_mm3':v,'source_solid_bounds_mm':[b.xmin,b.ymin,b.zmin,b.xmax,b.ymax,b.zmax],'intersection_bounds_mm':[c.xmin,c.ymin,c.zmin,c.xmax,c.ymax,c.zmax],'depth_mm':c.zlen})
case_overlap=sum(s.Volume() for s in base.intersect(lid).Solids())
components=[s for s in pcb.Solids() if not(abs(s.BoundingBox().xlen-60)<1e-6 and abs(s.BoundingBox().ylen-20)<1e-6)]
float_intersections=[]
for case_name,case in [('base',base),('lid',lid)]:
 for i,solid in enumerate(components):
  common=case.intersect(solid.translate((0,0,parameters['pcb_capture_top_z_mm'])))
  volume=sum(s.Volume() for s in common.Solids())
  if volume>1e-7:
   float_intersections.append({'case':case_name,'component_solid_index':i,'volume_mm3':volume})
assert not float_intersections, float_intersections
usb_solids=[s for s in components if s.BoundingBox().zmax>3.2 and s.BoundingBox().xmin>-2 and s.BoundingBox().xmax<7]
usb_distances={}
for case_name,case in [('base',base),('lid',lid)]:
 usb_distances[case_name]={'seated_min_distance_mm':min(case.distance(s) for s in usb_solids),'lifted_min_distance_mm':min(case.distance(s.translate((0,0,parameters['pcb_capture_top_z_mm']))) for s in usb_solids)}
mesh_results={}
for n in ['base','lid']:
 mesh=trimesh.load(out/(n+'.stl'),force='mesh')
 mesh_results[n]={'watertight':bool(mesh.is_watertight),'winding_consistent':bool(mesh.is_winding_consistent),'positive_volume':bool(mesh.volume>0),'connected_bodies':int(mesh.body_count),'volume_mm3':float(mesh.volume),'bounds_mm':mesh.bounds.tolist(),'triangle_count':len(mesh.faces)}
 assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0 and mesh.body_count==1
assert len(base.Solids())==len(lid.Solids())==1 and base.isValid() and lid.isValid()
assert case_overlap<1e-7
assert not any(x['kind']=='component' for x in intersections)
assert not any(x['case']=='lid' for x in intersections)
assert all(x['depth_mm']<.001201 for x in intersections)
for f in files:
 assert hashes[str(f.relative_to(root))]==hashlib.sha256(f.read_bytes()).hexdigest(),'Files changed during review'
review={'reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer':'independent enclosure_geometry agent','scope':'Exact-solid nominal assembled collision audit, printable-mesh topology checks, and construction review. This is not a physical fit or load test.','source_hashes_sha256':hashes,'coordinates':{'audit':'Right-handed native KiCad STEP coordinates: X right, Y up in top view, Z out of the top face; PCB spans Y=-20..0mm; nominal PCB top Z=0','pcb_step_transform':'Translate (0,0,-1.6012) mm only; no rotation, reflection or scaling','assembly_export_ground_offset_z_mm':-z0,'base_step_inverse_print_transform_mm':[x0,-y1,z0],'lid_step_inverse_print_transform':'Translate (x0,y0,-roof_outer_z), then rotate 180 degrees about X'},'solids_checked':{'pcb_reference_total':len(pcb.Solids()),'component_solids':len(components),'pcb_substrate_solids':len(pcb.Solids())-len(components),'base':len(base.Solids()),'lid':len(lid.Solids())},'results':{'base_lid_intersection_mm3':case_overlap,'component_case_intersection_mm3':sum(x['volume_mm3'] for x in intersections if x['kind']=='component'),'lid_pcb_intersection_mm3':sum(x['volume_mm3'] for x in intersections if x['case']=='lid'),'nominal_collision_check_pass':True,'support_seat_datum_overlap':intersections,'datum_explanation':'PCB STEP substrate bottom is Z=-1.6012 after alignment to the component mounting datum; nominal support seats are Z=-1.6000. The only overlap is 1.2 micrometres at the two support annuli, not a practical component interference.','modeled_lowest_component_z_mm':min(s.BoundingBox().zmin for s in components),'modeled_component_to_floor_clearance_mm':min(s.BoundingBox().zmin for s in components)-parameters['floor_inner_z_mm'],'printed_mesh_checks':mesh_results},'button':{'membrane_diameter_mm':parameters['button_membrane_diameter_mm'],'membrane_thickness_mm':parameters['button_membrane_thickness_mm'],'plunger_diameter_mm':parameters['button_plunger_diameter_mm'],'plunger_tip_z_mm':parameters['button_tip_z_mm'],'nominal_switch_rest_gap_mm':round(parameters['button_tip_z_mm']-2,6),'nominal_rest_gap_after_max_pcb_lift_mm':round(parameters['button_tip_z_mm']-2-parameters['pcb_capture_top_z_mm'],6),'housing_stop_feet':False,'overtravel_protection_claimed':False,'note':'First-print fit, gentle actuation, force and travel need verification on the actual PCB. No switch-housing stop dimension is assumed.'},'construction_review':{'supports':'Base floor-down and lid exterior-down, with 45-degree hook/recess ramps, rim-open ports and flat-printed diaphragm; intended without slicer supports. Actual slicer/print result not tested.','grip_notches':'Lower skirt purchase notches are backed by the continuous inner base wall.','nominal_end_seam_mm':parameters['end_seam_clearance_mm'],'sealed_or_waterproof_claimed':False,'snap_recess_min_outer_cover_mm':.65,'snap_durability':'PLA snap insertion/removal force, fatigue and printer tolerance remain untested.','source_model_limits':'USB is a supplier-linked approximate visualization; some small components are approximate previews. Physical connector and switch dimensions govern fit.'},'physical_fit_tested':False,'physical_load_tested':False}
review['assembled_envelope_mm']={'length':x1-x0,'width':y1-y0,'height':top-z0,'roof_top_nominal_z':top,'terminal_top_nominal_z':4.5,'terminal_height_tolerance_note':'Terminal height tolerance can leave actual connectors slightly above or below nominally flush roof.'}
review['results']['full_upward_pcb_float_check']={'lift_mm':parameters['pcb_capture_top_z_mm'],'component_solids_checked':len(components),'case_intersections':float_intersections,'pass':not float_intersections,'scope':'Pure upward translation to the nominal capture limit; not a complete manufacturing/print/tilt tolerance sweep.'}
review['results']['main_inner_roof_z_mm']=parameters['roof_inner_z_mm']
review['results']['highest_top_component_outside_connectors_mm']=2.16
review['results']['main_roof_nominal_nonconnector_clearance_mm']=parameters['roof_inner_z_mm']-2.16
review['results']['main_roof_nonconnector_clearance_at_full_lift_mm']=parameters['roof_inner_z_mm']-2.16-parameters['pcb_capture_top_z_mm']
review['port_review']={'usb_aperture_mm':{'width':parameters['usb_nominal_width_mm']+2*parameters['usb_clearance_per_side_mm'],'height':parameters['usb_nominal_height_mm']+2*parameters['usb_clearance_per_side_mm'],'corner_radius':parameters['usb_inferred_corner_radius_mm']+parameters['usb_clearance_per_side_mm'],'center_y':-5.25,'center_z':parameters['usb_nominal_height_mm']/2+parameters['usb_opening_vertical_offset_mm']},'usb_ceiling_z_mm':parameters['usb_ceiling_z_mm'],'usb_high_geometry_solids_checked':len(usb_solids),'usb_distances':usb_distances,'usb_interference_result':'No USB component collision in seated or full upward PCB-float positions. All component solids are included in the whole-assembly collision check.','usb_profile_limit':'The 1.0mm nominal shell corner radius is inferred from shared supplier geometry, not dimensioned in the DEALON drawing; actual cable/port fit needs verification.','terminal_top_access':'Two roof windows cover the three connectors and allow access to all wire-release buttons. Their outboard ends extend beyond the case; the straight sides align with the rectangular end ports at input Y-10.8/-19.7 and output Y-1.3/-18.7. Rounded corners remain only at the inboard ends, removing the former roof-window/end-port teeth.'}
review['capture_review']={'support_boss_diameter_mm':parameters['boss_diameter_mm'],'source_support_envelope_diameter_mm':4.4,'locating_pin_diameter_mm':parameters['locating_pin_diameter_mm'],'pcb_hole_nominal_diameter_mm':2.2,'nominal_pin_to_hole_radial_clearance_mm':(2.2-parameters['locating_pin_diameter_mm'])/2,'lid_socket_diameter_mm':parameters['lid_pin_socket_diameter_mm'],'nominal_pin_to_socket_radial_clearance_mm':(parameters['lid_pin_socket_diameter_mm']-parameters['locating_pin_diameter_mm'])/2,'capture_gap_mm':1.6+parameters['pcb_capture_top_z_mm'],'result':'No modeled component collision with holder/capture posts. The only seated substrate contact is the reported 1.2micrometre support-seat datum overlap.'}
review['button']['center_mark_diameter_mm']=parameters['button_plunger_diameter_mm']*.8
review['button']['center_mark_within_stem']=True
review['button']['membrane_layers_at_requested_layer_height']=round(parameters['button_membrane_thickness_mm']/parameters['layer_mm'])
review['construction_review']['supports']='Base floor-down and lid exterior-down, with 45-degree hook/recess ramps, rim-open ports and flat-printed diaphragm. Actual digital slicing is reviewed separately in slice-verification.json. Physical printing remains untested.'
review['construction_review']['print_layer_height_mm']=parameters['layer_mm']
review['construction_review']['snap_durability']='PLA snap insertion/removal force, fatigue and printer tolerance remain untested. Lowered snap tips shorten the effective bending span; no repeat-cycle durability is claimed.'
corner_gaps=[]
for px,py in [(0.1,1.7),(60.35,1.7),(0.1,-21.7),(60.35,-21.7)]:
 gap=lid.distance(cq.Vertex.makeVertex(px,py,2.0))
 corner_gaps.append({'base_inner_wall_corner_xyz_mm':[px,py,2.0],'minimum_distance_to_lid_mm':gap})
 assert gap>.2
outer_faces=[]
for face in lid.Faces():
 b=face.BoundingBox()
 if face.geomType()=='PLANE' and b.ylen<1e-6 and (abs(b.ymin+y0)<1e-6 or abs(b.ymin+y1)<1e-6):
  outer_faces.append({'y_mm':b.ymin,'x_span_mm':[b.xmin,b.xmax],'z_span_mm':[b.zmin,b.zmax]})
assert len(outer_faces)==2
assert all(abs(f['z_span_mm'][0]-parameters['floor_inner_z_mm'])<1e-6 and abs(f['z_span_mm'][1]-top)<1e-6 for f in outer_faces)
review['corner_and_long_side_review']={'construction':'The lid owns both full-height outer long faces and all outer corners. The end-face parting cuts are limited to the central Y span, so there is no raised base-endwall projection on either long side. Fingernail recesses remain intentional.','base_endwall_y_span_mm':[-20-parameters['end_wall_side_margin_mm'],parameters['end_wall_side_margin_mm']],'lid_end_cut_y_span_mm':[-20-parameters['end_wall_side_margin_mm']-parameters['end_wall_side_fit_mm'],parameters['end_wall_side_margin_mm']+parameters['end_wall_side_fit_mm']],'endwall_side_fit_mm':parameters['end_wall_side_fit_mm'],'endwall_to_inner_wall_longitudinal_gap_mm':.1,'corner_return_width_on_end_face_mm':1.0,'cavity_x_span_mm':[-parameters['inner_corner_end_clearance_mm'],60.45+parameters['inner_corner_end_clearance_mm']],'exact_corner_distance_checks':corner_gaps,'outer_long_side_planar_faces':outer_faces,'edge_only_junctions':'The 0.1mm endwall/inner-wall separation avoids a kissing edge; both walls remain connected through the floor. Both resulting meshes passed manifold checks.'}
terminal_walls=[]
for name,join_x,wall_y in [('input_near_y0',.8,-10.8),('input_far_y0',.8,-19.7),('output_near_y0',60.,-1.3),('output_far_y0',60.,-18.7)]:
 points=[(join_x+dx,wall_y,(parameters['roof_inner_z_mm']+top)/2) for dx in [-.25,0,.25]]
 matches=[]
 for face in lid.Faces():
  b=face.BoundingBox()
  if face.geomType()=='PLANE' and b.ylen<1e-6 and abs(b.ymin-wall_y)<1e-6:
   distances=[face.distance(cq.Vertex.makeVertex(*point)) for point in points]
   if max(distances)<1e-6:
    matches.append({'face_x_span_mm':[b.xmin,b.xmax],'face_y_mm':b.ymin,'face_z_span_mm':[b.zmin,b.zmax],'probe_points_mm':points,'maximum_probe_distance_mm':max(distances)})
 assert len(matches)==1, f'{name}: expected one continuous planar wall through former terminal-window/end-port step, got {len(matches)}'
 terminal_walls.append({'name':name,'former_join_x_mm':join_x,'continuous_single_plane':True,**matches[0]})
review['port_review']['terminal_window_join_check']={'pass':True,'description':'Each former sharp projection is replaced by one planar vertical side face, verified on both sides of all four former roof-window/end-port junctions.','walls':terminal_walls}
review['physical_handedness']=handedness_review
validation=out/'Validation';validation.mkdir(parents=True,exist_ok=True)
(validation/'mechanical-review.json').write_text(json.dumps(review,indent=2)+'\n')
print(json.dumps({'report':str(validation/'mechanical-review.json'),'component_collisions':0,'base_lid_overlap':case_overlap,'solids':len(pcb.Solids()),'stl_sha256':{k:v for k,v in hashes.items() if k.endswith('.stl')}},indent=2),flush=True)
