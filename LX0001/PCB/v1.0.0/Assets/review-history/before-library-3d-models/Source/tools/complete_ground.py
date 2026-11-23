"""Complete disconnected GND contours with short reviewed traces and tented vias.

Run after stitch_ground.py, using KiCad Python:
  complete_ground.py INPUT.kicad_pcb --output DISTINCT.kicad_pcb [--project PROJECT]

All original tracks, vias, footprints and zones are retained. Each GND filled
contour is a separate physical connectivity node. Multi-source Dijkstra starts
inside one disconnected copper component and ends inside a different actual
component; DRC zone origins are never used as routing coordinates. New vias
exclude every pad/paste land, existing drills, antenna and via rule areas.
Each route is refilled and DRC checked on a private trial before acceptance.
Failed trials roll back. Foreign pours are fixed unless --allow-pour-cut NET
explicitly permits local refill changes; removed copper area is reported for
current-path review. Non-GND disconnects may not increase. Exit2 indicates
remaining GND components; output is always the last verified checkpoint.
"""
import argparse,collections,hashlib,heapq,json,math,shutil,subprocess
from pathlib import Path
import pcbnew as pcb
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('board',type=Path)
parser.add_argument('--output',required=True,type=Path)
parser.add_argument('--project',type=Path)
parser.add_argument('--max-routes',type=int,default=50)
parser.add_argument('--max-states',type=int,default=250000)
parser.add_argument('--fine-grid',type=float,default=.025,choices=[.025,.01])
parser.add_argument('--region',type=float,nargs=4,metavar=('XMIN','YMIN','XMAX','YMAX'),help='Restrict new ground routing to this board region in mm')
parser.add_argument('--allow-pour-cut',action='append',default=[],help='Net whose filled pour may be locally reshaped; authored tracks/outlines stay fixed')
parser.add_argument('--kicad-cli',default=shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
args=parser.parse_args()
assert not args.region or (args.region[0]<args.region[2] and args.region[1]<args.region[3])
assert args.board.resolve()!=args.output.resolve(),'Use distinct input/output paths'
project=args.project or args.board.with_suffix('.kicad_pro');assert project.exists()
args.output.parent.mkdir(parents=True,exist_ok=True)
trial_path=args.output.with_name('.'+args.output.stem+'.ground-trial.kicad_pcb')
for suffix in ['.kicad_pro','.kicad_dru']:
    source=project.with_suffix(suffix)
    if source.exists():
        for destination in [args.output.with_suffix(suffix),trial_path.with_suffix(suffix)]:
            if source.resolve()!=destination.resolve():shutil.copy2(source,destination)
board=pcb.LoadBoard(str(args.board));board.BuildConnectivity();pcb.ZONE_FILLER(board).Fill(board.Zones())
copper_layers=[pcb.F_Cu,pcb.In1_Cu,pcb.In2_Cu,pcb.B_Cu] if board.GetCopperLayerCount()==4 else [pcb.F_Cu,pcb.B_Cu]
original={t.m_Uuid.AsString():(t.GetNetname(),t.GetStart().x,t.GetStart().y,t.GetEnd().x,t.GetEnd().y,t.GetLayer(),t.GetWidth(pcb.F_Cu) if isinstance(t,pcb.PCB_VIA) else t.GetWidth()) for t in board.GetTracks()}
poses={f.GetReference():(f.GetPosition().x,f.GetPosition().y,f.GetOrientationDegrees(),f.GetLayer()) for f in board.GetFootprints()}
foreign_polygons={(z.m_Uuid.AsString(),layer):(z.GetNetname(),z.GetFilledPolysList(layer).CloneDropTriangulation()) for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname()!='GND' for layer in copper_layers if z.IsOnLayer(layer)}
original_zone_outlines={z.m_Uuid.AsString():z.Outline().Format() for z in board.Zones()}
foreign_fill={(z.m_Uuid.AsString(),layer):z.GetFilledPolysList(layer).Format() for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname()!='GND' and z.GetNetname() not in args.allow_pour_cut for layer in copper_layers if z.IsOnLayer(layer)}
pcb.SaveBoard(str(args.output),board)
drc_path=args.output.with_suffix('.ground-drc.json');log_path=args.output.with_suffix('.ground.json')
r=subprocess.run([args.kicad_cli,'pcb','drc','--format','json','--severity-all','-o',str(drc_path),str(args.output)],capture_output=True,text=True)
assert r.returncode in [0,5] and drc_path.exists(),r.stdout+r.stderr
report=json.loads(drc_path.read_text());baseline={(v['type'],tuple(sorted(x['uuid'] for x in v.get('items',[])))) for v in report['violations']}
log={'input':str(args.board.resolve()),'output':str(args.output.resolve()),'accepted':[],'rejected':[],'rounds':[],'candidate_region_mm':args.region};complete=False;rejected_routes=set()
for round_index in range(args.max_routes+1):
    objects={x.m_Uuid.AsString():x for x in list(board.GetTracks())+[d for f in board.GetFootprints() for d in f.Pads()]+list(board.Zones())}
    ground_records=[r for r in report['unconnected_items'] if r.get('items') and all(objects[i['uuid']].GetNetname()=='GND' for i in r['items'])]
    nonground_count=len(report['unconnected_items'])-len(ground_records)
    if round_index==0:log.update(initial_ground_unconnected=len(ground_records),initial_other_unconnected=nonground_count)
    if not ground_records:complete=True;break
    # Filled contours belong to separate nodes. A single ZONE object can contain
    # disconnected copper contours, so treating the ZONE UUID as one node is wrong.
    nodes = []
    for zone in board.Zones():
        if zone.GetIsRuleArea() or zone.GetNetname() != 'GND':
            continue
        for layer in copper_layers:
            if not zone.IsOnLayer(layer):
                continue
            polygons = zone.GetFilledPolysList(layer)
            for index in range(polygons.OutlineCount()):
                polygon = polygons.UnitSet(index)
                if polygon.IsEmpty():
                    continue
                nodes.append({'kind': 'island', 'key': (zone.m_Uuid.AsString(), layer, index),
                              'name': '%s:%s:%d' % (zone.m_Uuid.AsString(), board.GetLayerName(layer), index),
                              'shapes': {layer: polygon}, 'zone': zone, 'island_index': index})
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            if pad.GetNetname() != 'GND':
                continue
            shapes = {layer: pad.GetEffectiveShape(layer) for layer in copper_layers
                      if pad.IsOnLayer(layer)}
            if shapes:
                # One plated pad is one conductive node on all its copper layers.
                nodes.append({'kind': 'pad', 'key': pad.m_Uuid.AsString(),
                              'name': footprint.GetReference() + '/' + pad.GetNumber(),
                              'shapes': shapes, 'item': pad})
    for track in board.GetTracks():
        if track.GetNetname() != 'GND':
            continue
        shapes = {layer: track.GetEffectiveShape(layer) for layer in copper_layers
                  if track.IsOnLayer(layer)}
        if shapes:
            # A plated through-via likewise unifies its front/back copper shapes.
            nodes.append({'kind': 'via' if isinstance(track, pcb.PCB_VIA) else 'track',
                          'key': track.m_Uuid.AsString(), 'name': track.m_Uuid.AsString(),
                          'shapes': shapes, 'item': track})
    # Cache integer bounding boxes before exact shape collision. Keep every shape
    # object alive in nodes; temporary C++ shape references otherwise risk SWIG GC.
    for node in nodes:
        node['bounds'] = {}
        for layer, shape in node['shapes'].items():
            box = shape.BBox()
            node['bounds'][layer] = (box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom())
    parents = list(range(len(nodes)))
    edges = 0
    for i, a in enumerate(nodes):
        for j in range(i):
            b = nodes[j]
            connected = False
            for layer in set(a['shapes']) & set(b['shapes']):
                x = a['bounds'][layer]
                y = b['bounds'][layer]
                if x[0] > y[2] or x[2] < y[0] or x[1] > y[3] or x[3] < y[1]:
                    continue
                # Zero clearance means actual physical copper overlap/touch.
                if a['shapes'][layer].Collide(b['shapes'][layer], 0):
                    connected = True
                    break
            if connected:
                ra, rb = i, j
                while parents[ra] != ra:
                    parents[ra] = parents[parents[ra]]
                    ra = parents[ra]
                while parents[rb] != rb:
                    parents[rb] = parents[parents[rb]]
                    rb = parents[rb]
                if ra != rb:
                    parents[ra] = rb
                edges += 1
    components = {}
    for index, node in enumerate(nodes):
        root = index
        while parents[root] != root:
            parents[root] = parents[parents[root]]
            root = parents[root]
        node['component'] = root
        components.setdefault(root, []).append(index)
    log['rounds'].append({'round':round_index,'components':len(components),'ground_unconnected':len(ground_records)})
    print(f'Ground trace round{round_index}: {len(components)} actual components, {len(ground_records)} DRC gaps',flush=True)
    if round_index==args.max_routes:break
    bins=[{} for _ in copper_layers];padbins={};holebins={};viakeep=[];keep=[]
    rules=[z for z in board.Zones() if z.GetIsRuleArea()]+[z for f in board.GetFootprints() for z in f.Zones() if z.GetIsRuleArea()]
    for z in rules:
        if z.GetDoNotAllowVias():viakeep.append(z.Outline())
    for li,layer in enumerate(copper_layers):
        shapes=[d.GetEffectiveShape(layer) for f in board.GetFootprints() for d in f.Pads() if d.IsOnLayer(layer) and d.GetNetname()!='GND']
        shapes += [t.GetEffectiveShape(layer) for t in board.GetTracks() if t.IsOnLayer(layer) and t.GetNetname()!='GND']
        shapes += [z.Outline() for z in rules if z.IsOnLayer(layer) and z.GetDoNotAllowTracks()]
        shapes += [z.GetFilledPolysList(layer).CloneDropTriangulation() for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname()!='GND' and z.GetNetname() not in args.allow_pour_cut and z.IsOnLayer(layer)]
        shapes += [d.GetEffectiveHoleShape() for f in board.GetFootprints() for d in f.Pads() if d.GetAttribute()==pcb.PAD_ATTRIB_NPTH]
        for sh in shapes:
            keep.append(sh);box=sh.BBox()
            for bx in range(math.floor(pcb.ToMM(box.GetLeft())/2)-1,math.floor(pcb.ToMM(box.GetRight())/2)+2):
                for by in range(math.floor(pcb.ToMM(box.GetTop())/2)-1,math.floor(pcb.ToMM(box.GetBottom())/2)+2):bins[li].setdefault((bx,by),[]).append(sh)
    for f in board.GetFootprints():
        for d in f.Pads():
            for layer in [pcb.F_Paste,pcb.B_Paste]:
                if not d.IsOnLayer(layer):continue
                sh=d.GetEffectiveShape(layer);keep.append(sh);box=sh.BBox()
                for bx in range(math.floor(pcb.ToMM(box.GetLeft())/2)-1,math.floor(pcb.ToMM(box.GetRight())/2)+2):
                    for by in range(math.floor(pcb.ToMM(box.GetTop())/2)-1,math.floor(pcb.ToMM(box.GetBottom())/2)+2):padbins.setdefault((bx,by),[]).append(sh)
    holes=[d.GetEffectiveHoleShape() for f in board.GetFootprints() for d in f.Pads() if d.HasDrilledHole()]
    holes += [pcb.SHAPE_CIRCLE(t.GetPosition(),t.GetDrillValue()//2).Clone() for t in board.GetTracks() if isinstance(t,pcb.PCB_VIA)]
    keep+=holes
    for sh in holes:
        box=sh.BBox()
        for bx in range(math.floor(pcb.ToMM(box.GetLeft())/2)-1,math.floor(pcb.ToMM(box.GetRight())/2)+2):
            for by in range(math.floor(pcb.ToMM(box.GetTop())/2)-1,math.floor(pcb.ToMM(box.GetBottom())/2)+2):holebins.setdefault((bx,by),[]).append(sh)
    edge=board.GetBoardEdgesBoundingBox();accepted=False;restart=False
    # Small groups usually represent one local decoupler or test pad. Preserve
    # the largest component as the destination rather than exploring its area.
    main=max(components,key=lambda q:len(components[q]))
    ordered=sorted([q for q in components if q!=main],key=lambda q:len(components[q]))
    for root in ordered:
        if accepted or restart:break
        names=[nodes[i]['name'] for i in components[root] if nodes[i]['kind']=='pad']
        source_nodes=[nodes[i] for i in components[root]]
        targets=[n for n in nodes if n['component']!=root]
        targetbins=[{} for _ in copper_layers]
        for n in targets:
            for layer,sh in n['shapes'].items():
                box=sh.BBox();li=copper_layers.index(layer)
                for bx in range(math.floor(pcb.ToMM(box.GetLeft())/2)-1,math.floor(pcb.ToMM(box.GetRight())/2)+2):
                    for by in range(math.floor(pcb.ToMM(box.GetTop())/2)-1,math.floor(pcb.ToMM(box.GetBottom())/2)+2):targetbins[li].setdefault((bx,by),[]).append(sh)
        for width,diameter,drill in [(.30,.60,.30),(.20,.45,.20),(.15,.45,.20),(.13,.45,.20)]:
            scale=round(1/args.fine_grid) if width==.13 else 20
            margin=.305+max(width/2,diameter/2)
            xmin,xmax=pcb.ToMM(edge.GetLeft())+margin,pcb.ToMM(edge.GetRight())-margin
            ymin,ymax=pcb.ToMM(edge.GetTop())+margin,pcb.ToMM(edge.GetBottom())-margin
            if args.region:
                xmin,ymin=max(xmin,args.region[0]),max(ymin,args.region[1])
                xmax,ymax=min(xmax,args.region[2]),min(ymax,args.region[3])
            starts=set()
            for n in source_nodes:
                for layer,sh in n['shapes'].items():
                    li=copper_layers.index(layer);box=sh.BBox()
                    if n['kind']=='island':
                        points=[(round(ix*.15*scale),round(iy*.15*scale)) for ix in range(math.ceil(pcb.ToMM(box.GetLeft())/.15),math.floor(pcb.ToMM(box.GetRight())/.15)+1) for iy in range(math.ceil(pcb.ToMM(box.GetTop())/.15),math.floor(pcb.ToMM(box.GetBottom())/.15)+1)]
                    else:
                        obj=n['item'];pos=obj.GetPosition();points=[(round(pcb.ToMM(pos.x)*scale),round(pcb.ToMM(pos.y)*scale))]
                    for x,y in points:
                        point=pcb.VECTOR2I(pcb.FromMM(x/scale),pcb.FromMM(y/scale));key=(math.floor(x/scale/2),math.floor(y/scale/2))
                        if not (xmin<=x/scale<=xmax and ymin<=y/scale<=ymax):continue
                        if not sh.Collide(pcb.SEG(point,point),0):continue
                        if any(s.Collide(pcb.SEG(point,point),pcb.FromMM(width/2+.1285)) for s in bins[li].get(key,[])):continue
                        starts.add((li,x,y))
            if not starts:
                print(f'No starts {names}, width{width}',flush=True);continue
            queue=[(0,q) for q in starts];heapq.heapify(queue);cost={q:0 for q in starts};parents={};free={};viafree={};found=None
            while queue:
                dist,current=heapq.heappop(queue)
                if dist!=cost[current]:continue
                li,x,y=current;point=pcb.VECTOR2I(pcb.FromMM(x/scale),pcb.FromMM(y/scale));key=(math.floor(x/scale/2),math.floor(y/scale/2))
                if current not in starts and any(sh.Collide(pcb.SEG(point,point),0) for sh in targetbins[li].get(key,[])):
                    found=current;break
                if len(cost)>args.max_states:break
                for nl,dx,dy in [(li,dx,dy) for dx,dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]]+[(nl,0,0) for nl in range(len(copper_layers)) if nl!=li]:
                    q=(nl,x+dx,y+dy)
                    if not (xmin<=q[1]/scale<=xmax and ymin<=q[2]/scale<=ymax):continue
                    pos=pcb.VECTOR2I(pcb.FromMM(q[1]/scale),pcb.FromMM(q[2]/scale));bk=(math.floor(q[1]/scale/2),math.floor(q[2]/scale/2))
                    dd=dist+(2*scale if dx==dy==0 else math.hypot(dx,dy))
                    if dd>=cost.get(q,float('inf')):continue
                    if dx==dy==0:
                        xy=q[1:]
                        if xy not in viafree:
                            seg=pcb.SEG(pos,pos)
                            viafree[xy]=not any(sh.Collide(seg,pcb.FromMM(diameter/2+.129)) for sh in sum((bi.get(bk,[]) for bi in bins),[])) and not any(sh.Collide(seg,pcb.FromMM(drill/2+.105)) for sh in padbins.get(bk,[])) and not any(sh.Collide(seg,pcb.FromMM(drill/2+.255)) for sh in holebins.get(bk,[])) and not any(sh.Collide(seg,pcb.FromMM(diameter/2+.005)) for sh in viakeep)
                        if not viafree[xy]:continue
                    else:
                        if q not in free:free[q]=not any(sh.Collide(pcb.SEG(pos,pos),pcb.FromMM(width/2+.1285)) for sh in bins[q[0]].get(bk,[]))
                        if not free[q]:continue
                        seg=pcb.SEG(point,pos)
                        if any(sh.Collide(seg,pcb.FromMM(width/2+.1285)) for sh in bins[q[0]].get(bk,[])):continue
                    cost[q]=dd;parents[q]=current;heapq.heappush(queue,(dd,q))
            if found is None:
                print(f'No route {names}, width{width}, states{len(cost)}',flush=True);continue
            route=[found]
            while route[-1] not in starts:route.append(parents[route[-1]])
            route.reverse();corners=[route[0]]
            for i in range(1,len(route)-1):
                if tuple(route[i][k]-route[i-1][k] for k in range(3))!=tuple(route[i+1][k]-route[i][k] for k in range(3)):corners.append(route[i])
            corners.append(route[-1]);signature=(width,diameter,scale,tuple(corners))
            if signature in rejected_routes:continue
            checkpoint=args.output.read_bytes();previous=report;added=[];viapos=[];invalid=False
            for aa,cc in zip(corners,corners[1:]):
                if aa[0]!=cc[0]:
                    x,y=aa[1]/scale,aa[2]/scale
                    if any(math.hypot(x-vx,y-vy)<drill+.255 for vx,vy in viapos):invalid=True;break
                    viapos.append((x,y))
            if invalid:continue
            for index,(aa,cc) in enumerate(zip(corners,corners[1:])):
                if aa[0]!=cc[0]:
                    t=pcb.PCB_VIA(board);t.SetPosition(pcb.VECTOR2I(pcb.FromMM(aa[1]/scale),pcb.FromMM(aa[2]/scale)));t.SetWidth(pcb.FromMM(diameter));t.SetDrill(pcb.FromMM(drill));t.SetViaType(pcb.VIATYPE_THROUGH);t.SetLayerPair(pcb.F_Cu,pcb.B_Cu);t.SetFrontTentingMode(pcb.TENTING_MODE_TENTED);t.SetBackTentingMode(pcb.TENTING_MODE_TENTED)
                else:
                    t=pcb.PCB_TRACK(board);t.SetStart(pcb.VECTOR2I(pcb.FromMM(aa[1]/scale),pcb.FromMM(aa[2]/scale)));t.SetEnd(pcb.VECTOR2I(pcb.FromMM(cc[1]/scale),pcb.FromMM(cc[2]/scale)));t.SetWidth(pcb.FromMM(width));t.SetLayer(copper_layers[aa[0]])
                t.SetNet(board.FindNet('GND'));t.SetLocked(True);board.Add(t);added.append(t.m_Uuid.AsString())
            board.BuildConnectivity();pcb.ZONE_FILLER(board).Fill(board.Zones());pcb.SaveBoard(str(trial_path),board)
            result=subprocess.run([args.kicad_cli,'pcb','drc','--format','json','--severity-all','-o',str(drc_path),str(trial_path)],capture_output=True,text=True)
            trial=json.loads(drc_path.read_text()) if result.returncode in [0,5] and drc_path.exists() else None
            new=[];after_ground=None;after_other=None
            if trial is not None:
                obj={x.m_Uuid.AsString():x for x in list(board.GetTracks())+[d for f in board.GetFootprints() for d in f.Pads()]+list(board.Zones())}
                after_ground=sum(bool(r.get('items')) and all(obj[i['uuid']].GetNetname()=='GND' for i in r['items']) for r in trial['unconnected_items']);after_other=len(trial['unconnected_items'])-after_ground
                new=[v for v in trial['violations'] if (v['type'],tuple(sorted(x['uuid'] for x in v.get('items',[])))) not in baseline]
            foreign_changed=foreign_fill!={(z.m_Uuid.AsString(),layer):z.GetFilledPolysList(layer).Format() for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname()!='GND' and z.GetNetname() not in args.allow_pour_cut for layer in copper_layers if z.IsOnLayer(layer)}
            record={'pads':names,'width_mm':width,'via_diameter_mm':diameter,'via_drill_mm':drill,'path_layer_grid':corners,'path_grid_mm':1/scale,'new_uuids':added,'search_states':len(cost),'before_ground':len(ground_records),'after_ground':after_ground,'after_other':after_other}
            if trial is not None and not new and not foreign_changed and after_ground<len(ground_records) and after_other<=nonground_count:
                args.output.write_bytes(trial_path.read_bytes());report=trial;log['accepted'].append(record);accepted=True
                print(f'Accepted GND repair {names}: {len(ground_records)}->{after_ground}, {len(added)} items',flush=True);break
            record['foreign_filled_copper_changed']=foreign_changed;record['new_violations']=[v['type'] for v in new];log['rejected'].append(record);rejected_routes.add(signature);restart=True;board=pcb.LoadBoard(str(args.output));report=previous;drc_path.write_text(json.dumps(report,indent=2))
            print(f'Rejected GND repair {names}: {record["new_violations"]}, {after_ground} gaps',flush=True)
            # Shapes are owned by the old board; rebuild the graph next round.
            break
    log_path.write_text(json.dumps(log,indent=2)+'\n')
    if restart:continue
    if not accepted:log['stopped_reason']='No validated short GND route found within search limits';break
# Confirm original geometry and poses were never changed.
now={t.m_Uuid.AsString():(t.GetNetname(),t.GetStart().x,t.GetStart().y,t.GetEnd().x,t.GetEnd().y,t.GetLayer(),t.GetWidth(pcb.F_Cu) if isinstance(t,pcb.PCB_VIA) else t.GetWidth()) for t in board.GetTracks()}
assert all(now.get(k)==v for k,v in original.items())
assert poses=={f.GetReference():(f.GetPosition().x,f.GetPosition().y,f.GetOrientationDegrees(),f.GetLayer()) for f in board.GetFootprints()}
assert foreign_fill=={(z.m_Uuid.AsString(),layer):z.GetFilledPolysList(layer).Format() for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname()!='GND' and z.GetNetname() not in args.allow_pour_cut for layer in copper_layers if z.IsOnLayer(layer)}
new_vias=[t for t in board.GetTracks() if isinstance(t,pcb.PCB_VIA) and t.m_Uuid.AsString() not in original]
for via in new_vias:
    point=via.GetPosition();radius=via.GetWidth(pcb.F_Cu)/2
    for f in board.GetFootprints():
        for pad in f.Pads():
            for layer in [pcb.F_Paste,pcb.B_Paste]:
                if pad.IsOnLayer(layer):assert not pad.GetEffectiveShape(layer).Collide(pcb.SEG(point,point),via.GetDrillValue()//2+pcb.FromMM(.10)),(f.GetReference(),pad.GetNumber())
log['remaining_components']=[]
if not complete:
    for root,indexes in sorted(components.items(),key=lambda q:-len(q[1])):
        log['remaining_components'].append({'nodes':len(indexes),'pads':[nodes[i]['name'] for i in indexes if nodes[i]['kind']=='pad']})
assert original_zone_outlines=={z.m_Uuid.AsString():z.Outline().Format() for z in board.Zones()}
log['allowed_pour_cuts']=args.allow_pour_cut;log['pour_changes']=[]
for z in board.Zones():
    for layer in copper_layers:
        key=(z.m_Uuid.AsString(),layer)
        if key not in foreign_polygons:continue
        net,oldpoly=foreign_polygons[key];newpoly=z.GetFilledPolysList(layer)
        if oldpoly.Format()==newpoly.Format():continue
        removed=oldpoly.CloneDropTriangulation();removed.BooleanSubtract(newpoly)
        box=removed.BBox()
        pieces=[]
        for i in range(removed.OutlineCount()):
            piece=removed.UnitSet(i);bb=piece.BBox()
            if piece.Area()/1e12>1e-6:pieces.append({'area_mm2':piece.Area()/1e12,'bounds_mm':[pcb.ToMM(bb.GetLeft()),pcb.ToMM(bb.GetTop()),pcb.ToMM(bb.GetRight()),pcb.ToMM(bb.GetBottom())]})
        log['pour_changes'].append({'net':net,'layer':board.GetLayerName(layer),'area_before_mm2':oldpoly.Area()/1e12,'area_after_mm2':newpoly.Area()/1e12,'filled_components_before':oldpoly.OutlineCount(),'filled_components_after':newpoly.OutlineCount(),'removed_area_mm2':removed.Area()/1e12,'removed_parts_above_1e_6_mm2':pieces,'removed_bounds_mm':[pcb.ToMM(box.GetLeft()),pcb.ToMM(box.GetTop()),pcb.ToMM(box.GetRight()),pcb.ToMM(box.GetBottom())]})
log.update(input_sha256=hashlib.sha256(args.board.read_bytes()).hexdigest(),output_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),non_ground_filled_copper_unchanged=not log['pour_changes'],new_via_pad_collisions=0,new_vias=len(new_vias))
log.update(complete=complete,final_ground_unconnected=len(ground_records),final_other_unconnected=nonground_count,original_items_preserved=len(original),all_poses_unchanged=True,output_verified=True)
log_path.write_text(json.dumps(log,indent=2)+'\n')
for temporary in [trial_path,trial_path.with_suffix('.kicad_pro'),trial_path.with_suffix('.kicad_dru')]:temporary.unlink(missing_ok=True)
print(f'Saved {args.output}: {len(log["accepted"])} repairs, {len(ground_records)} GND gaps remain',flush=True)
if not complete:raise SystemExit(2)
