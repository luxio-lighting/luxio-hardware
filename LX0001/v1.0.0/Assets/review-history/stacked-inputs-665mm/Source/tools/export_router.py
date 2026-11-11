from pathlib import Path
import pcbnew as p
root=Path(__file__).resolve().parents[1];b=p.LoadBoard(str(root/'LX0001.kicad_pcb'))
nc=b.GetDesignSettings().m_NetSettings.GetDefaultNetclass();nc.SetViaDiameter(p.FromMM(.6));nc.SetViaDrill(p.FromMM(.3));nc.SetTrackWidth(p.FromMM(.15));nc.SetClearance(p.FromMM(.15))
f=Path('/tmp/lx0001.dsn');assert p.ExportSpecctraDSN(b,str(f));s=f.read_text();a=s.index('    (class kicad_default');e=s.index('\n  )\n  (wiring',a)
nets={n.GetNetname() for n in b.GetNetInfo().NetsByNetcode().values() if n.GetNetname()}
heavy={'GND','DC_IN','DC_FUSED','VSYS','LED_VCC'};power={'+3V3','VDD_SPI','VDD3P3_RF','USB_5V','USB_LIMITED','+5V_DATA'};usb={'USB_DM','USB_DP','USB_DM_CONN','USB_DP_CONN'}
critical={'RF_CHIP','RF_50','ANT_TUNE','XTAL_P','XTAL_P_CRYSTAL','XTAL_N','BUCK_BST','BUCK_SW','BOOST_SW'}
classes=''
for name,nn,w in [('signals',nets-heavy-power-usb-critical,150),('power',power,200),('usb',usb,200),('heavy',heavy,600),('critical',critical,150)]:
 classes+='    (class '+name+' '+' '.join('"'+n+'"' for n in sorted(nn))+' (circuit (use_via "Via[0-1]_600:300_um")) (rule (width '+str(w)+') (clearance 150)))\n'
s=s[:a]+classes.rstrip()+s[e:]
# KiCad exports raw zone outlines, which overlap across priority levels. The
# router cannot resolve these priorities. Preserve fixed copper spines instead;
# refill the original KiCad zones after importing the routed session.
while '\n    (plane ' in s:
 a=s.index('\n    (plane ');e=a+1;depth=0;quoted=False;escape=False
 while e<len(s):
  c=s[e]
  if quoted:
   if escape:escape=False
   elif c=='\\':escape=True
   elif c=='"':quoted=False
  elif c=='"':quoted=True
  elif c=='(':depth+=1
  elif c==')':
   depth-=1
   if depth==0:break
  e+=1
 s=s[:a]+s[e+1:]
# The router adds its 0.15 mm clearance to this 0.15 mm inset, retaining the
# project's 0.30 mm copper-to-board-edge clearance. Fabrication outline stays put.
s=s.replace('(path pcb 0  60000 -20000  0 -20000  0 0  60000 0  60000 -20000)',
 '(path pcb 0  59850 -19850  150 -19850  150 -150  59850 -150  59850 -19850)')
f.write_text(s)
print('Exported',len(nets),'nets; overlapping raw plane outlines removed')
