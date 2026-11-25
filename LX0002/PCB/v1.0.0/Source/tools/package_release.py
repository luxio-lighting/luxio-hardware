"""Package checked JLCPCB inputs and their review evidence without changing CAD."""
from pathlib import Path
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[2]
out = root / 'Export'
board = root / 'Source/LX0002.kicad_pcb'
board_hash = hashlib.sha256(board.read_bytes()).hexdigest()
verification = json.loads((out / 'verification.json').read_text())
mechanical = json.loads((out / 'assembled-export-verification.json').read_text())
assert verification['source_sha256']['Source/LX0002.kicad_pcb'] == board_hash == mechanical['pcb_sha256']
rf = json.loads((out / 'rf-reference-check.json').read_text())
rebuild = json.loads((out / 'rebuild-check.json').read_text())
current = json.loads((out / 'current-path-model/current-review-summary.json').read_text())
rails = json.loads((out / 'current-path-model/3v3-path-review.json').read_text())
assert rf['board_sha256'] == board_hash and rf['status'] == 'sampled_geometry_pass'
assert rebuild['source_sha256'] == board_hash and rebuild['pass']
assert current['board_sha256'] == board_hash and current['successful'] and not current['unconnected']
assert rails['board_sha256'] == board_hash
assert 'PCB SHA256: ' + board_hash in (root / 'Source/current_path_review.txt').read_text()
for filename in ['drc.json', 'erc.json']:
    report = json.loads((out / filename).read_text())
    assert not any(report.get(key) for key in ['violations', 'unconnected_items', 'schematic_parity'])
    assert all(not sheet.get('violations') for sheet in report.get('sheets', []))
for relative, expected in verification['source_sha256'].items():
    assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected, relative
for relative, expected in verification['export_sha256'].items():
    assert hashlib.sha256((out / relative).read_bytes()).hexdigest() == expected, relative
names = ['LX0002-v1.0.0-Gerbers.zip', 'JLCPCB-BOM.csv', 'JLCPCB-CPL.csv',
         'README.txt', 'order-settings.txt', 'schematic.pdf',
         'assembly-top.svg', 'assembly-top.png', 'assembly-bottom.svg', 'assembly-bottom.png',
         'verification.json', 'drc.json', 'erc.json', 'connection-check.json',
         'manufacturing-geometry-check.json', 'circuit-validation.json',
         'rf-reference-check.json', 'rebuild-check.json',
         'current-path-model/current-review-summary.json',
         'current-path-model/3v3-path-review.json']
files = {name: out / name for name in names}
files['first-article-validation.md'] = root / 'Source/first-article-validation.md'
files['power-integrity-review.md'] = root / 'Source/power-integrity-review.md'
files['current_path_review.txt'] = root / 'Source/current_path_review.txt'
files['FH4R2-package-verification.json'] = root / 'Source/libraries/models/FH4R2-package-verification.json'
assert all(path.is_file() for path in files.values()), [str(path) for path in files.values() if not path.is_file()]
manifest = {'pcb_sha256': board_hash, 'status': 'Checked fabrication data; first-article qualification remains',
            'sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}}
archive = out / 'LX0002-v1.0.0-JLCPCB.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
    for name, path in files.items():
        handle.write(path, name)
    handle.writestr('manifest.json', json.dumps(manifest, indent=2) + '\n')
with zipfile.ZipFile(archive) as handle:
    assert handle.testzip() is None
    for name, expected in manifest['sha256'].items():
        assert hashlib.sha256(handle.read(name)).hexdigest() == expected
(out / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(archive)
