"""Record the ordered stackup/colors and synchronize local preview models."""
from pathlib import Path
import pcbnew as p
root=Path(__file__).resolve().parents[1]
board=root/'LX0001.kicad_pcb'
b=p.LoadBoard(str(board))
for fp in b.GetFootprints():
 lib=fp.GetFPID().GetLibNickname();name=fp.GetFPID().GetLibItemName()
 if lib not in ['LX0001','Core']:continue
 original=p.FootprintLoad(str(root/'libraries'/f'{lib}.pretty'),name)
 if original and original.Models():
  fp.Models().clear()
  for model in original.Models():fp.Models().push_back(model)
p.SaveBoard(str(board),b)
s=board.read_text()
if '(stackup' in s:
 start=s.index('(stackup');end=start;depth=0
 for end in range(start,len(s)):
  if s[end]=='(':depth+=1
  elif s[end]==')':
   depth-=1
   if depth==0:break
 s=s[:start]+s[end+1:]
s=s.replace('\t(setup\n','''\t(setup
        (stackup
            (layer "F.SilkS" (type "Top Silk Screen") (color "White"))
            (layer "F.Paste" (type "Top Solder Paste"))
            (layer "F.Mask" (type "Top Solder Mask") (color "Black") (thickness 0.01))
            (layer "F.Cu" (type "copper") (thickness 0.035))
            (layer "dielectric 1" (type "prepreg") (thickness 0.2104) (material "7628") (epsilon_r 4.4) (loss_tangent 0.02))
            (layer "In1.Cu" (type "copper") (thickness 0.0152))
            (layer "dielectric 2" (type "core") (thickness 1.065) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
            (layer "In2.Cu" (type "copper") (thickness 0.0152))
            (layer "dielectric 3" (type "prepreg") (thickness 0.2104) (material "7628") (epsilon_r 4.4) (loss_tangent 0.02))
            (layer "B.Cu" (type "copper") (thickness 0.035))
            (layer "B.Mask" (type "Bottom Solder Mask") (color "Black") (thickness 0.01))
            (layer "B.Paste" (type "Bottom Solder Paste"))
            (layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))
            (copper_finish "ENIG")
            (dielectric_constraints yes)
        )
''',1)
board.write_text(s)
print('Applied black mask, white silk, ENIG and JLC04161H-7628 four-layer stackup')
