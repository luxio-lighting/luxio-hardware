"""Export LX0002 fabrication files after strict ERC, DRC and independent checks.

Run with system Python after routing, refilling zones and saving the board.
This script does not route, refill or modify the PCB. No warning, exclusion,
open connection or schematic mismatch is accepted as a release waiver.
"""
from pathlib import Path
import collections
import csv
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile

root = Path(__file__).resolve().parents[2]
src = root / 'Source'
out = root / 'Export'
out.mkdir(parents=True, exist_ok=True)
cli = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
kicad_python = '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3'
board = src / 'LX0002.kicad_pcb'
schematic = src / 'LX0002.kicad_sch'
mechanical = json.loads((src / 'mechanical.json').read_text())
parts = json.loads((src / 'parts.json').read_text())
source_files = sorted({path for path in src.glob('*.kicad_*') if path.suffix in ['.kicad_pcb', '.kicad_sch', '.kicad_pro', '.kicad_dru']} | {src / name for name in ['parts.json', 'connections.csv', 'placement.json', 'mechanical.json']})
source_hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files if path.is_file()}
for command in [
    [cli, 'pcb', 'drc', '--schematic-parity', '--all-track-errors', '--severity-all', '--format', 'json', '-o', str(out / 'drc.json'), str(board)],
    [cli, 'pcb', 'drc', '--schematic-parity', '--all-track-errors', '--severity-all', '-o', str(out / 'drc.txt'), str(board)],
    [cli, 'sch', 'erc', '--severity-all', '--format', 'json', '-o', str(out / 'erc.json'), str(schematic)],
    [cli, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', str(out / 'netlist.xml'), str(schematic)],
]:
    subprocess.run(command, check=True)
drc = json.loads((out / 'drc.json').read_text())
erc = json.loads((out / 'erc.json').read_text())
assert not drc['unconnected_items'], 'Unrouted connections block fabrication export'
assert not drc.get('schematic_parity'), 'Schematic/PCB mismatch blocks export'
assert not drc['violations'], 'Any DRC error, warning or exclusion blocks fabrication export'
assert not erc.get('violations') and all(not sheet.get('violations') for sheet in erc.get('sheets', [])), 'Any ERC finding blocks fabrication export'
for command in [
    [kicad_python, str(src / 'tools/verify_design.py')],
    [kicad_python, str(src / 'tools/verify_circuit.py')],
]:
    subprocess.run(command, check=True)
geometry = json.loads((out / 'manufacturing-geometry-check.json').read_text())
connections = json.loads((out / 'connection-check.json').read_text())
circuit = json.loads((out / 'circuit-validation.json').read_text())
assert geometry['pass'] and connections['pass'] and circuit['result'] == 'PASS'
assert geometry['board_sha256'] == connections['board_sha256'] == source_hashes['Source/LX0002.kicad_pcb']
assert connections['netlist_sha256'] == circuit['netlist_sha256']

with tempfile.TemporaryDirectory(prefix='.fabrication-staging-', dir=out) as temporary:
    staging = Path(temporary)
    gerbers = staging / 'Gerbers'
    gerbers.mkdir()
    for command in [
        [cli, 'pcb', 'export', 'gerbers', '--layers', 'F.Cu,B.Cu,F.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts', '--use-drill-file-origin', '-o', str(gerbers) + '/', str(board)],
        [cli, 'pcb', 'export', 'drill', '--drill-origin', 'plot', '--excellon-separate-th', '--excellon-units', 'mm', '-o', str(gerbers) + '/', str(board)],
        [cli, 'pcb', 'export', 'pos', '--side', 'front', '--format', 'csv', '--units', 'mm', '--use-drill-file-origin', '--exclude-dnp', '-o', str(staging / 'kicad-positions.csv'), str(board)],
        [cli, 'sch', 'export', 'pdf', '-o', str(staging / 'schematic.pdf'), str(schematic)],
    ]:
        subprocess.run(command, check=True)
    assert {'.gtl', '.gbl', '.gtp', '.gts', '.gbs', '.gm1'} <= {path.suffix for path in gerbers.iterdir()}, 'Missing mandatory Gerber layer'
    assert not any(path.suffix in ['.g1', '.g2', '.gbp'] for path in gerbers.iterdir()), 'Unexpected inner-copper or bottom-paste output'
    drills = sorted(gerbers.glob('*.drl'))
    assert drills, 'Drill files missing'
    for path in drills:
        text = path.read_text()
        assert 'METRIC' in text, 'Expected millimeter Excellon file'
        assert all(float(diameter) >= 0.3 for diameter in re.findall(r'^T\d+C([0-9.]+)', text, re.MULTILINE)), 'Exported drill is smaller than 0.30mm'
    groups = collections.defaultdict(list)
    populated = set()
    for part in parts:
        if part['lcsc'] and not part.get('dnp', False):
            assert part['side'] == 'Top', 'All fitted components must be on top'
            groups[part['value'], part['footprint'], part['lcsc']].append(part['ref'])
            populated.add(part['ref'])
    with (staging / 'JLCPCB-BOM.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #', 'Quantity'])
        for (value, footprint, lcsc), refs in sorted(groups.items(), key=lambda item: item[0][2]):
            writer.writerow([value, ','.join(sorted(refs)), footprint, lcsc, len(refs)])
    with (staging / 'kicad-positions.csv').open() as handle:
        # J1's plated shell stakes require the through-hole footprint attribute;
        # its pin-in-paste placement still belongs in the top assembly job.
        positions = [row for row in csv.DictReader(handle) if row['Ref'] in populated]
    assert len(positions) == len(populated) and {position['Ref'] for position in positions} == populated, 'BOM/CPL reference mismatch'
    assert all(position['Side'].lower() == 'top' for position in positions), 'CPL contains a bottom component'
    with (staging / 'JLCPCB-CPL.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
        for position in positions:
            writer.writerow([position['Ref'], position['PosX'], position['PosY'], 'Top', position['Rot']])
    archive_name = 'LX0002-v1.0.0-Gerbers.zip'
    with zipfile.ZipFile(staging / archive_name, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(gerbers.iterdir()):
            archive.write(path, path.name)
    for name, layers, mirror in [
        ('assembly-top', 'F.Fab,F.SilkS,Edge.Cuts', False),
        ('assembly-bottom', 'B.Fab,B.SilkS,Edge.Cuts', True),
        ('copper-top', 'F.Cu,F.Mask,F.SilkS,Edge.Cuts', False),
        ('copper-bottom', 'B.Cu,B.Mask,B.SilkS,Edge.Cuts', True),
    ]:
        command = [cli, 'pcb', 'export', 'svg', '--layers', layers, '--mode-single', '--page-size-mode', '2', '--exclude-drawing-sheet', '-o', str(staging / (name + '.svg'))]
        if mirror:
            command.append('--mirror')
        command.append(str(board))
        subprocess.run(command, check=True)
        subprocess.run(['/opt/homebrew/bin/rsvg-convert', '-w', '2400', '-o', str(staging / (name + '.png')), str(staging / (name + '.svg'))], check=True)
    for relative, expected in source_hashes.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected, 'Source changed during export: ' + relative
    status = {
        'date': datetime.date.today().isoformat(),
        'status': 'FABRICATION DATA CHECKED; UNBUILT FIRST ARTICLE; NOT PRODUCTION-QUALIFIED',
        'board_mm': mechanical['size_mm'],
        'copper_layers': 2,
        'outer_copper_oz': 1,
        'soldermask': 'black',
        'assembly_side': 'top',
        'assembled_parts': len(populated),
        'bom_lines': len(groups),
        'open_connections': 0,
        'drc_findings_including_exclusions': 0,
        'erc_findings_including_exclusions': 0,
        'schematic_parity_findings': 0,
        'documented_mechanical_flags': 0,
        'minimum_via_drill_mm': connections['minimum_via_drill_mm'],
        'usb_connector_rating': '3A at 5V total, including controller; not an onboard current clamp',
        'source_sha256': source_hashes,
        'export_sha256': {str(path.relative_to(staging)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(staging.rglob('*')) if path.is_file()},
    }
    (staging / 'verification.json').write_text(json.dumps(status, indent=2) + '\n')
    length, width, thickness = mechanical['size_mm']
    (staging / 'README.txt').write_text(f'''LX0002 v1.0.0 — USB-only 5V controller

Upload LX0002-v1.0.0-Gerbers.zip, JLCPCB-BOM.csv and JLCPCB-CPL.csv together.
{length:g} x {width:g}mm, two copper layers, {thickness:g}mm FR-4, black mask,
white silkscreen, 1oz copper on both sides, minimum 0.30mm via drill.
Select TOP-SIDE assembly only: {len(populated)} fitted components.
L104 is DNP; test pads and mounting holes are not assembled.

USB 5V connects directly to LED VCC. There is no external DC input, power-path
diode, source-selection circuit, USB PD or onboard input current limiter.
J1 is DEALON USB-TYPE-C-018/C2927038, rated 3A at 5V total including controller
and strip. Use a suitable regulated 5V adapter and cable. This rating is not
a current clamp or a measured continuous-current thermal qualification.
GPIO16 and GPIO17 have permanently enabled 5V AHCT data buffers.

Release checks require zero ERC/DRC/parity findings including exclusions,
zero open nets, matching BOM/CPL references, top-only assembly, and independent
0.10mm minimum routing-via drill-to-paste clearance. The four USB shell stakes
use their own normal top-side pin-in-paste apertures; they are component pins,
not routing-via exceptions. Both-side tenting is requested for routing vias.
The MCU exposed-pad mask opening exposes its thermal-via tops; these holes
clear the paste windows. Tenting flags do not override component mask openings.

Validate the first assembled boards electrically, thermally, over USB and over
Wi-Fi before a production run. CAD checks do not establish physical qualification.
The USB 3D model is a supplier visualization; manufacturer drawings govern fit.
''')
    if (out / 'Gerbers').exists():
        history = root / 'Assets/review-history/previous-exports'
        history.mkdir(parents=True, exist_ok=True)
        (out / 'Gerbers').rename(history / ('Gerbers-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
    for path in staging.iterdir():
        path.replace(out / path.name)
print('LX0002 fabrication exports complete; physical first-article qualification remains required.')
