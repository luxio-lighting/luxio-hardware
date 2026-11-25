"""Package only mutually consistent, verified enclosure exports."""
from pathlib import Path
from hashlib import sha256
import json
import re
import zipfile

root = Path(__file__).resolve().parents[3]
case = root / 'Enclosure/v1.0.0/Export/Case'
build = json.loads((case / 'verification.json').read_text())
assert build['coordinates']['pcb_reference_transform_determinant'] == 1
assert build['coordinates']['pcb_reference_available'], 'Final PCB reference is required'
assert build['final_pcb_overlay_verified'], 'Final PCB overlay check has not passed'

mechanical = json.loads((case / 'Validation/mechanical-review.json').read_text())
assert mechanical['physical_handedness']['pass']
assert mechanical['results']['nominal_collision_check_pass']
for filename, digest in mechanical['source_hashes_sha256'].items():
    assert sha256((root / filename).read_bytes()).hexdigest() == digest, filename

sketchup = json.loads((case / 'sketchup-verification.json').read_text())
for filename, digest in sketchup['source_stl_sha256'].items():
    assert sha256((case / filename).read_bytes()).hexdigest() == digest, filename
for model in sketchup['models']:
    assert model['saved_and_reloaded'] and model['unchanged_face_edge_counts_and_bounds']
    assert sha256((case / model['file']).read_bytes()).hexdigest() == model['sha256']
for filename, record in sketchup['renders'].items():
    assert sha256((case / filename).read_bytes()).hexdigest() == record['sha256'], filename

slicing = json.loads((case / 'Validation/slice-verification.json').read_text())
assert not slicing['supports_enabled']
for name, part in slicing['parts'].items():
    assert sha256((case / (name + '.stl')).read_bytes()).hexdigest() == part['stl_sha256']
    assert not part['whole_floating_islands'] and not part['slicer_warning']

portable = json.loads((case / 'Validation/portable-3mf.json').read_text())
assert sha256((case / portable['file']).read_bytes()).hexdigest() == portable['sha256']
assert portable['bambu_cli_import']['succeeded']
for name, part in portable['models'].items():
    assert sha256((case / (name + '.stl')).read_bytes()).hexdigest() == part['stl_sha256']

for target in re.findall(r'\]\(([^)]+)\)', (case / 'README.md').read_text()):
    assert (case / target).exists(), target
files = sorted(f for f in case.rglob('*') if f.is_file()
               and not any(part.startswith('.') for part in f.relative_to(case).parts)
               and f.name != 'SHA256SUMS.txt')
manifest = case / 'SHA256SUMS.txt'
manifest.write_text(''.join(sha256(f.read_bytes()).hexdigest() + '  ' +
                            str(f.relative_to(case)) + '\n' for f in files))
archive = case.parent / 'LX0002-case.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in files + [manifest]:
        z.write(f, Path('LX0002-case') / f.relative_to(case))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for f in files + [manifest]:
        assert z.read(str(Path('LX0002-case') / f.relative_to(case))) == f.read_bytes()
print(f'Verified and packaged {len(files) + 1} files: {archive}')
