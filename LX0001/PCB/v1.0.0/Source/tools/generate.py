"""Generate the editable prototype schematic and PCB from the reviewed connection table.
Run with KiCad's bundled Python. No online dependencies.
"""
from pathlib import Path
import re, json, uuid, copy, math, csv, shutil, sys
import pcbnew as pcb
io=pcb.PCB_IO_KICAD_SEXPR()
ROOT=Path(__file__).resolve().parents[2]
HW=ROOT/'Source'
mechanical=json.loads((HW/'mechanical.json').read_text())

KICAD=Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport')
JLC=Path('/Users/emile/Downloads/JLCPCB-KiCad-Library-2026.09.21')
NS=uuid.UUID('f9fd0691-178b-47cd-b2d8-5ed5c8b1c941')
def uid(s): return str(uuid.uuid5(NS,s))
def parse(s):
    stack=[]; result=[]
    for t in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+',s):
        if t=='(':
            child=[]
            (stack[-1] if stack else result).append(child); stack.append(child)
        elif t==')': stack.pop()
        else: stack[-1].append(t)
    return result[0]
def dump(x): return '('+' '.join(dump(v) if isinstance(v,list) else str(v) for v in x)+')'
def children(x,key): return [v for v in x if isinstance(v,list) and v[0]==key]
def get(x,key): return next((v for v in x if isinstance(v,list) and v[0]==key),None)
def q(x): return json.dumps(str(x),ensure_ascii=False)
libs={}
def symbol(lib,name):
    if lib not in libs:
        p=HW/'libraries'/f'{lib}.kicad_sym'
        if not p.exists():p=JLC/'symbols/JLCPCB-Extended.kicad_sym' if lib=='JLCPCB' else KICAD/'symbols'/f'{lib}.kicad_sym'
        libs[lib]={json.loads(v[1]):v for v in children(parse(p.read_text()),'symbol')}
    s=copy.deepcopy(libs[lib][name]); ext=get(s,'extends')
    if ext:
        base=symbol(lib,json.loads(ext[1])); old=json.loads(base[1]); s.remove(ext)
        for v in children(base,'symbol'):
            v[1]=q(json.loads(v[1]).replace(old+'_',name+'_')); s.append(v)
        for key in ['pin_names','pin_numbers']:
            if get(base,key) and not get(s,key): s.append(get(base,key))
    return s
# Custom component only where KiCad has no exact symbol.
custom={}
for name,pins in {'TPS22965DSGR': [('1','VIN','power_in','L'),('2','VIN','passive','L'),('3','ON','input','L'),('4','VBIAS','power_in','L'),('5','GND','power_in','B'),('6','CT','passive','R'),('7','VOUT','passive','R'),('8','VOUT','power_out','R'),('9','EP','passive','B')], 'LMR51410YFDBVR': [('1','CB','passive','R'),('2','GND','power_in','B'),('3','FB','input','R'),('4','EN','input','L'),('5','VIN','power_in','L'),('6','SW','power_out','R')], 'RFECA3216060A1T': [('1','FEED','passive','L'),('2','TUNE','passive','R'),('3','GND','passive','B')]}.items():
    body=['symbol',q(name),['pin_names',['offset','0.8']],['in_bom','yes'],['on_board','yes'],['property',q('Reference'),q('U'),['at','0','8','0'],['effects',['font',['size','1.27','1.27']]]],['property',q('Value'),q(name),['at','0','10','0'],['effects',['font',['size','1.27','1.27']]]]]
    draw=['symbol',q(name+'_0_1'),['rectangle',['start','-6.35','6.35'],['end','6.35','-6.35'],['stroke',['width','0.254'],['type','default']],['fill',['type','background']]]]
    pp=['symbol',q(name+'_1_1')]; counters={'L':0,'R':0}
    for num,label,typ,side in pins:
        if side=='B': x,y,a=0,-8.89,90
        else: x,y,a=(-8.89 if side=='L' else 8.89),2.54-counters[side]*2.54,(0 if side=='L' else 180); counters[side]+=1
        pp.append(['pin',typ,'line',['at',str(x),str(y),str(a)],['length','2.54'],['name',q(label),['effects',['font',['size','1.0','1.0']]]],['number',q(num),['effects',['font',['size','1.0','1.0']]]]])
    body += [draw,pp]; custom[name]=body
parts=[]
for file in ['core_parts.json','io_parts.json','power_parts.json']:
    parts += json.loads((HW/file).read_text())
assert len({p['ref'] for p in parts})==len(parts), 'Duplicate designators'
for p in parts:
    p['uuid']=uid(p['ref'])
    if 'group' not in p:
        r=p['ref']
        p['group']='mcu' if r=='U1' else 'rf' if r in ['ANT1','C114','C115','C116','L102','L103','L104'] else 'flash' if r=='U10' or r in ['C108','C109','C110'] or (r.startswith('R1') and int(r[1:])>=104) else 'core'
    if p['ref']=='J2':p['place']=[6.5,10,270]
    if p['ref']=='J3':p['place']=[53.5,5.75,90];p['pins']={'1':'DATA16_OUT','2':'GND'}
    if p['ref']=='J4':p['place']=[53.5,14.25,90];p['pins']={'1':'VSYS','2':'DATA17_OUT'}
placement=json.loads((HW/'placement.json').read_text()) if (HW/'placement.json').exists() else {}
for p in parts:
    if p['ref'] in placement:
        p['place']=placement[p['ref']][:3]
        if len(placement[p['ref']])>3:p['side']=placement[p['ref']][3]
cache={}
for p in parts:
    lib,name=p['libname'].split(':',1)
    s=copy.deepcopy(custom[name]) if lib=='LX0001' else symbol(lib,name)
    if p['ref']=='J1':
        for unit in children(s,'symbol'):
            for pin in children(unit,'pin'):
                if get(pin,'number')[1]=='"S1"':get(pin,'number')[1]='"SH"'
    s[1]=q(p['libname']);cache[p['libname']]=s
flag=symbol('power','PWR_FLAG');flag[1]=q('power:PWR_FLAG');cache['power:PWR_FLAG']=flag
rootid=uid('schematic')
group_info={
 'mcu':('ESP32-S3 / no PSRAM',['GND'], 'Bare ESP32-S3, 4 MB external quad-SPI flash. GPIO16 / GPIO17 drive 5 V buffers.\nGPIO18 senses the shared BOOT button through an isolation diode.'),
 'core':('MCU power, straps and 40 MHz clock',['+3V3','VDD3P3_RF'], '3.3 V power, local bypassing, boot straps and 40 MHz crystal.\nGPIO45 and GPIO46 pulled LOW. Boot recovery: hold SW1 and pulse EN low.'),
 'flash':('4 MB flash and SPI termination',['VDD_SPI'], 'W25Q32JVSSIQ, 32 Mbit = 4 MB, no PSRAM.\nVDD_SPI is the ESP32 flash supply. R105 reserves clock-series tuning.'),
 'rf':('2.4 GHz ceramic antenna and RF matching',[], 'Walsin RFECA3216060A1T. Preserve the 8 x 3 mm edge clearance on ALL copper layers.\nRF matching values are initial values; tune on assembled PCB in final enclosure.'),
 'usb':('USB-C data and passive 5 V input',['USB_5V'], 'USB 2.0 device / 5 V sink; no PD. Separate 5.1k CC pull-downs.\nNo current negotiation or onboard USB current limiter; use a suitably rated 5 V adapter.'),
 'power':('Automatic wired priority',['DC_FUSED','VSYS'], '5-24 V regulated wired supply has hardware priority over USB.\nReverse-blocking paths isolate sources. Design target 5 A continuous wired output.'),
 'regulators':('3.3 V buck and 5 V logic boost',['+5V_DATA'], '3.3 V buck from VSYS; boost 3.3 V to 4.99 V for AHCT buffers only.\nStrip output follows selected input voltage; no 12/24 V boost from USB.'),
 'outputs':('Two 5 V data outputs and strip terminals',[], 'GPIO16 / GPIO17 -> AHCT buffers -> 100-ohm series resistors.\nBuffers always enabled in hardware; 100k input pull-downs hold data low during reset.'),
 'button':('Centered BOOT / GPIO18 button',[], 'SW1 pulls BOOT and GPIO18 low through separate Schottky diodes.\nFirmware uses GPIO18 as an input. BOOT must be held low during reset for download.'),
 'test':('Production and recovery test pads',[], 'Test-point map for recovery, power rails and data.\nUse common ground. Power selection and data enables need no firmware control.')}
# Split larger sections across A3 pages, keeping the MCU alone for readable pin names.
groups=[]
for slug,(title,flags,note) in group_info.items():
    refs=[p['ref'] for p in parts if p['group']==slug]
    for start in range(0,len(refs),16):
        sub=slug if start==0 else slug+'_'+str(start//16+1)
        groups.append((sub,title+(' (continued)' if start else ''),refs[start:start+16],flags if start==0 else [],note))
root=['(kicad_sch (version 20250114) (generator "eeschema")',f'(uuid "{rootid}") (paper "A3")','(title_block (title "LX0001 digital LED controller") (date "2026-11-11") (rev "1.0.0") (company "Luxio"))','(lib_symbols)']
for gi,(slug,title,refs,flags,note) in enumerate(groups):
    sid=uid('sheet-'+slug);fid=uid('file-'+slug);path='/'+rootid+'/'+sid
    sx=20+(gi%4)*95;sy=48+(gi//4)*62
    root.append(f'(sheet (at {sx} {sy}) (size 85 40) (stroke (width 0.254) (type default)) (fill (color 0 0 0 0)) (uuid "{sid}") (property "Sheetname" {q(title)} (at {sx} {sy-2} 0) (effects (font (size 1.0 1.0)) (justify left bottom))) (property "Sheetfile" "{slug}.kicad_sch" (at {sx} {sy+42} 0) (effects (font (size 1.0 1.0)) (justify left top))) (instances (project "LX0001" (path "/{rootid}" (page "{gi+2}")))))')
    used={next(p['libname'] for p in parts if p['ref']==r) for r in refs}|{'power:PWR_FLAG'}
    out=['(kicad_sch (version 20250114) (generator "eeschema")',f'(uuid "{fid}") (paper "A3")',f'(title_block (title {q(title)}) (date "2026-11-11") (rev "1.0.0") (company "Luxio"))','(lib_symbols '+'\n'.join(dump(cache[k]) for k in sorted(used))+')']
    for pi,ref in enumerate(refs):
        p=next(p for p in parts if p['ref']==ref);p['sheet_path']=path
        x,y=(182.88,137.16) if ref=='U1' else (50.8+(pi%4)*91.44,60.96+(pi//4)*50.8)
        if ref=='J1':y-=12.7
        p['sch']=[x,y];s=cache[p['libname']];pins=[]
        for unit in children(s,'symbol'):pins+=children(unit,'pin')
        # All selected functional symbols are single-unit symbols.
        props={'Reference':ref,'Value':p['value'],'Footprint':p['footprint'],'LCSC':p['lcsc']}
        if p.get('datasheet'):props['Datasheet']=p['datasheet']
        out.append(f'(symbol (lib_id {q(p["libname"])}) (at {x} {y} 0) (unit 1) (in_bom {"yes" if p["lcsc"] else "no"}) (on_board yes) (dnp {"yes" if p.get("dnp") else "no"}) (uuid "{p["uuid"]}")')
        for j,(key,val) in enumerate(props.items()):
            # Keep text beside vertical leads and above horizontal diodes.
            # Left justification prevents long part values crossing the lead.
            prop_x=x;prop_justify=''
            prop_y=y-(66.04 if ref=='U1' else 15.24)+j*2.54
            if ref=='J1':
                prop_y=y-22.86+j*2.54
            elif ref[0] in 'RCLF':
                prop_x=x+5.08;prop_y=y-2+j*2.54;prop_justify=' (justify left)'
            elif ref[0]=='D':
                prop_y=y-7.62+j*2.54
            elif ref[0]=='Q':
                prop_x=x+7.62;prop_y=y-12.7+j*2.54;prop_justify=' (justify left)'
            elif ref[0]=='U' and ref!='U1':
                prop_x=x+12.7;prop_justify=' (justify left)'
            out.append(f'(property {q(key)} {q(val)} (at {prop_x} {prop_y} 0) (effects (font (size 1.1 1.1))'+prop_justify+(' (hide yes)' if j>1 else '')+'))')
        for pin in pins:out.append(f'(pin {get(pin,"number")[1]} (uuid "{uid(ref+get(pin,"number")[1])}"))')
        out.append(f'(instances (project "LX0001" (path "{path}" (reference "{ref}") (unit 1)))))')
        done=set()
        for pin in pins:
            num=json.loads(get(pin,'number')[1]);at=get(pin,'at');px=x+float(at[1]);py=y-float(at[2]);angle=float(at[3]);coord=(round(px,5),round(py,5))
            if coord in done:continue
            done.add(coord);net=p['pins'].get(num)
            if net:
                ex,ey=round(px-math.cos(math.radians(angle))*5.08,5),round(py+math.sin(math.radians(angle))*5.08,5)
                out.append(f'(wire (pts (xy {px} {py}) (xy {ex} {ey})) (stroke (width 0.1524) (type default)) (uuid "{uid(ref+num+"wire")}"))')
                out.append(f'(global_label {q(net)} (shape input) (at {ex} {ey} {angle}) (effects (font (size 0.9 0.9)) (justify '+('left' if angle in [180,270] else 'right')+f')) (uuid "{uid(ref+num+"label")}"))')
            elif pin[1]!='no_connect':out.append(f'(no_connect (at {px} {py}) (uuid "{uid(ref+num+"nc")}"))')
    for i,net in enumerate(flags):
        x,y=50.8+i*91.44,264.16;ref='#FLG'+str(gi)+str(i)
        out.append(f'(symbol (lib_id "power:PWR_FLAG") (at {x} {y} 0) (unit 1) (in_bom no) (on_board no) (uuid "{uid(ref)}") (property "Reference" "{ref}" (at {x} {y} 0) (effects (font (size 1 1)) (hide yes))) (property "Value" "PWR_FLAG" (at {x} {y-5.08} 0) (effects (font (size 1 1)))) (instances (project "LX0001" (path "{path}" (reference "{ref}") (unit 1)))))')
        out.append(f'(global_label {q(net)} (shape input) (at {x} {y} 0) (effects (font (size 1 1)) (justify right)) (uuid "{uid(ref+"net")}"))')
    out.append(f'(text {q(note)} (at 20 20 0) (effects (font (size 1.3 1.3)) (justify left)) (uuid "{uid(slug+"note")}"))')
    out.append('(embedded_fonts no))');(HW/f'{slug}.kicad_sch').write_text('\n'.join(out))
root.append(f'(text "60 x 20 mm / 4 copper layers / black solder mask / 5 A at 24 V design target\\n4 MB flash, no PSRAM. USB powers 5 V strips only. Wired input has priority.\\nInitial fabrication design: assembled electrical, thermal and RF validation required." (at 20 20 0) (effects (font (size 1.4 1.4)) (justify left)) (uuid "{uid("rootnotes")}"))')
root.append('(sheet_instances (path "/" (page "1"))) (embedded_fonts no))');(HW/'LX0001.kicad_sch').write_text('\n'.join(root))
# One cached library per namespace avoids loading external symbol libraries.
for lib in sorted({p['libname'].split(':')[0] for p in parts}|{'power'}):
    entries=[dump(v).replace(q(k),q(k.split(':',1)[1]),1) for k,v in cache.items() if k.startswith(lib+':')]
    (HW/'libraries'/f'{lib}.kicad_sym').write_text('(kicad_symbol_lib (version 20250114) (generator "kicad_symbol_editor")\n'+'\n'.join(entries)+'\n)')
(HW/'sym-lib-table').write_text('(sym_lib_table (version 7)\n'+''.join(f'(lib (name "{lib}") (type "KiCad") (uri "${{KIPRJMOD}}/libraries/{lib}.kicad_sym") (options "") (descr "Project-local symbol cache"))\n' for lib in sorted({p['libname'].split(':')[0] for p in parts}|{'power'}))+')\n')
# Local footprint copies; no global KiCad library changes.
for p in parts:
    lib,name=p['footprint'].split(':')
    dst=HW/'libraries'/f'{lib}.pretty';dst.mkdir(exist_ok=True)
    if lib!='LX0001' and not (dst/(name+'.kicad_mod')).exists():shutil.copyfile(KICAD/'footprints'/f'{lib}.pretty'/(name+'.kicad_mod'),dst/(name+'.kicad_mod'))
fp_libs=sorted({p['footprint'].split(':')[0] for p in parts}|{'MountingHole'})
(HW/'fp-lib-table').write_text('(fp_lib_table (version 7)\n'+''.join(f'(lib (name "{lib}") (type "KiCad") (uri "${{KIPRJMOD}}/libraries/{lib}.pretty") (options "") (descr "Project-local footprint"))\n' for lib in fp_libs)+')\n')
(HW/'parts.json').write_text(json.dumps(parts,indent=2)+'\n')
with (HW/'connections.csv').open('w') as f:
    w=csv.writer(f);w.writerow(['Reference','Value','Pin','Net'])
    for p in parts:
        for pin,net in p['pins'].items():w.writerow([p['ref'],p['value'],pin,net])
if not (HW/'LX0001.kicad_pro').exists():
    pro={'meta':{'filename':'LX0001.kicad_pro','version':1},'net_settings':{'classes':[{'name':'Default','clearance':0.127,'track_width':0.15,'via_diameter':0.6,'via_drill':0.3,'diff_pair_width':0.3,'diff_pair_gap':0.15,'diff_pair_via_gap':0.25}],'meta':{'version':3}},'board':{'design_settings':{'rules':{'min_clearance':0.127,'min_track_width':0.127,'min_via_diameter':0.45,'min_through_hole_diameter':0.3,'min_via_annular_width':0.075,'min_hole_clearance':0.25,'min_copper_edge_clearance':0.3,'min_silk_clearance':0.1}}}}
    (HW/'LX0001.kicad_pro').write_text(json.dumps(pro,indent=2)+'\n')
print('Generated',len(parts),'parts and',len(groups)+1,'schematic sheets')
if '--board' not in sys.argv:sys.exit(0)
board=pcb.BOARD();board.SetCopperLayerCount(4)
nets={}
for i,name in enumerate(sorted({n for p in parts for n in p['pins'].values()}),1):
    net=pcb.NETINFO_ITEM(board,name,i);board.Add(net);nets[name]=net
for p in parts:
    lib,name=p['footprint'].split(':');fp=io.FootprintLoad(str(HW/'libraries'/f'{lib}.pretty'),name)
    assert fp,p['footprint']
    fp.SetReference(p['ref']);fp.SetValue(p['value']);fp.SetFPID(pcb.LIB_ID(lib,name));fp.SetPath(pcb.KIID_PATH(p['sheet_path']+'/'+p['uuid']))
    board.Add(fp)
    x,y,rot=p['place'];fp.SetPosition(pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y)))
    if p.get('side')=='Bottom':fp.Flip(fp.GetPosition(),False)
    fp.SetOrientationDegrees(rot);fp.Value().SetVisible(False)
    fp.Reference().SetLayer(pcb.B_Fab if p.get('side')=='Bottom' else pcb.F_Fab);fp.Reference().SetTextSize(pcb.VECTOR2I(700000,700000));fp.Reference().SetTextThickness(120000)
    if not p['lcsc']:fp.SetAttributes(fp.GetAttributes()|pcb.FP_EXCLUDE_FROM_POS_FILES|pcb.FP_EXCLUDE_FROM_BOM)
    if p.get('dnp'):fp.SetAttributes(fp.GetAttributes()|pcb.FP_DNP)
    for pad in fp.Pads():
        if pad.GetNumber() in p['pins']:pad.SetNet(nets[p['pins'][pad.GetNumber()]])
for ref,(x,y) in mechanical['mounting_holes'].items():
    lib='MountingHole';name='MountingHole_2.2mm_M2'
    d=HW/'libraries'/f'{lib}.pretty';d.mkdir(exist_ok=True);shutil.copyfile(KICAD/'footprints'/f'{lib}.pretty'/(name+'.kicad_mod'),d/(name+'.kicad_mod'))
    fp=io.FootprintLoad(str(d),name);fp.SetReference(ref);fp.SetFPID(pcb.LIB_ID(lib,name));fp.SetPosition(pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y)));fp.Reference().SetLayer(pcb.F_Fab);fp.Value().SetVisible(False);board.Add(fp)
    keep=pcb.ZONE(board);keep.SetIsRuleArea(True);ls=pcb.LSET();ls.AddLayer(pcb.F_Cu);ls.AddLayer(pcb.B_Cu);keep.SetLayerSet(ls);keep.SetDoNotAllowTracks(True);keep.SetDoNotAllowVias(True);keep.SetDoNotAllowZoneFills(True);keep.SetDoNotAllowPads(False);keep.SetDoNotAllowFootprints(False);keep.SetZoneName('M2 screw clearance')
    outline=keep.Outline();outline.NewOutline()
    for a in range(0,360,10):outline.Append(pcb.FromMM(x+2.3*math.cos(math.radians(a))),pcb.FromMM(y+2.3*math.sin(math.radians(a))))
    board.Add(keep)
for a,b in [((0,0),(60,0)),((60,0),(60,20)),((60,20),(0,20)),((0,20),(0,0))]:
    e=pcb.PCB_SHAPE();e.SetShape(pcb.SHAPE_T_SEGMENT);e.SetStart(pcb.VECTOR2I(pcb.FromMM(a[0]),pcb.FromMM(a[1])));e.SetEnd(pcb.VECTOR2I(pcb.FromMM(b[0]),pcb.FromMM(b[1])));e.SetLayer(pcb.Edge_Cuts);e.SetWidth(50000);board.Add(e)
# Antenna radiator zone: deliberate manufacturer feed/ground fingers on top only.
keep=pcb.ZONE(board);keep.SetIsRuleArea(True);ls=pcb.LSET();ls.AddLayer(pcb.B_Cu);keep.SetLayerSet(ls);keep.SetDoNotAllowTracks(True);keep.SetDoNotAllowVias(True);keep.SetDoNotAllowZoneFills(True);keep.SetDoNotAllowPads(True);keep.SetZoneName('RFECA antenna bottom no copper');poly=keep.Outline();poly.NewOutline()
for x,y in mechanical['antenna_clearance']:poly.Append(pcb.FromMM(x),pcb.FromMM(y))
board.Add(keep)
keep=pcb.ZONE(board);keep.SetIsRuleArea(True);keep.SetLayer(pcb.F_Cu);keep.SetDoNotAllowTracks(False);keep.SetDoNotAllowVias(True);keep.SetDoNotAllowZoneFills(True);keep.SetDoNotAllowPads(False);keep.SetZoneName('RFECA antenna top no ground pour');poly=keep.Outline();poly.NewOutline()
for x,y in mechanical['antenna_clearance']:poly.Append(pcb.FromMM(x),pcb.FromMM(y))
board.Add(keep)
keep=pcb.ZONE(board);keep.SetIsRuleArea(True);keep.SetLayer(pcb.B_Cu);keep.SetDoNotAllowTracks(True);keep.SetDoNotAllowVias(False);keep.SetDoNotAllowZoneFills(False);keep.SetDoNotAllowPads(True);keep.SetDoNotAllowFootprints(False);keep.SetZoneName('Continuous RF reference ground - no signal routing');poly=keep.Outline();poly.NewOutline()
for x,y in [(14.2,3),(19,3),(19,8.4),(14.2,8.4)]:poly.Append(pcb.FromMM(x),pcb.FromMM(y))
board.Add(keep)
board.GetDesignSettings().SetAuxOrigin(pcb.VECTOR2I(0,20000000))
board.GetTitleBlock().SetTitle('LX0001 digital LED controller');board.GetTitleBlock().SetRevision('1.0.0');board.GetTitleBlock().SetDate('2026-11-11');board.GetTitleBlock().SetCompany('Luxio')
io.SaveBoard(str(HW/'LX0001.kicad_pcb'),board)
print('Generated initial 60 x 20 mm board placement; routing is a separate step')
