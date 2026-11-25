import pcbnew as p,json,hashlib,pathlib,collections,argparse
source=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description="Compare rebuilt native copper, pads, reference areas and labels with the released PCB")
parser.add_argument("--rebuilt-board",required=True,type=pathlib.Path)
parser.add_argument("--drc-report",required=True,type=pathlib.Path)
parser.add_argument("--output",type=pathlib.Path,default=source.parent/"Export/rebuild-check.json")
args=parser.parse_args()
files=[source/'LX0002.kicad_pcb',args.rebuilt_board]
results=[];boards=[]
for path in files:
 b=p.LoadBoard(str(path));boards.append(b);tracks=[];pads=[];areas=[];labels=[]
 for t in b.GetTracks():
  if isinstance(t,p.PCB_VIA):tracks.append(('via',t.GetNetname(),t.GetPosition().x,t.GetPosition().y,t.GetWidth(p.F_Cu),t.GetDrillValue(),t.IsTented(p.F_Cu),t.IsTented(p.B_Cu)))
  else:
   ends=sorted([(t.GetStart().x,t.GetStart().y),(t.GetEnd().x,t.GetEnd().y)])
   tracks.append(('track',t.GetNetname(),int(t.GetLayer()),t.GetWidth(),*ends))
 for f in b.GetFootprints():
  for a in f.Pads():
   pads.append((f.GetReference(),a.GetNumber(),a.GetNetname(),a.GetPosition().x,a.GetPosition().y,a.GetSize().x,a.GetSize().y,a.GetOrientationDegrees(),int(a.GetShape()),int(a.GetAttribute()),a.GetDrillSize().x,a.GetDrillSize().y,a.GetRoundRectRadiusRatio(),tuple(a.GetLayerSet().Seq())))
 for z in b.Zones():
  if z.GetIsRuleArea():
   sh=z.Outline();o=sh.Outline(0);areas.append((z.GetZoneName(),tuple(z.GetLayerSet().Seq()),tuple((o.CPoint(i).x,o.CPoint(i).y) for i in range(o.PointCount())),z.GetDoNotAllowTracks(),z.GetDoNotAllowVias(),z.GetDoNotAllowPads(),z.GetDoNotAllowZoneFills()))
 for t in b.GetDrawings():
  if isinstance(t,p.PCB_TEXT):labels.append((t.GetText(),int(t.GetLayer()),t.GetPosition().x,t.GetPosition().y,t.GetTextSize().x,t.GetTextSize().y,t.GetTextThickness(),t.GetTextAngle().AsDegrees(),t.IsMirrored()))
 results.append({'tracks':sorted(tracks),'pads':sorted(pads),'reference_areas':sorted(areas),'labels':sorted(labels)})
differences={}
for kind in results[0]:
 a=collections.Counter(results[0][kind]);b=collections.Counter(results[1][kind]);differences[kind]={'source_only':list((a-b).elements()),'rebuild_only':list((b-a).elements())}
drc=json.loads(args.drc_report.read_text())
report={'source_board':str(files[0]),'source_sha256':hashlib.sha256(files[0].read_bytes()).hexdigest(),'rebuilt_board':str(files[1]),'rebuilt_sha256':hashlib.sha256(files[1].read_bytes()).hexdigest(),'counts':{k:len(v) for k,v in results[0].items()},'differences':differences,'native_rebuild_drc_counts':{k:len(drc.get(k,[])) for k in ['violations','unconnected_items','schematic_parity']}}
report['pass']=not any(v for d in differences.values() for v in d.values()) and not any(report['native_rebuild_drc_counts'].values())
print(json.dumps(report,indent=2))
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2)+'\n')
assert report['pass'], 'Rebuilt physical geometry or strict native DRC differs'
