"""Run fresh copper-loss meshes on a frozen, filled LX0002 PCB without editing it.

Use ordinary Python3 for orchestration. KiCad Python extracts geometry; the
CAD environment provides SciPy for the sparse conductance solve. The resulting
report is an electrical loss estimate, not a temperature/current qualification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--board', type=Path, default=root/'Source/LX0002.kicad_pcb')
parser.add_argument('--evidence-dir', type=Path, default=root/'Export/current-path-model')
parser.add_argument('--report', type=Path, default=root/'Source/current_path_review.txt')
parser.add_argument('--kicad-python', default='/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3')
parser.add_argument('--solver-python', default='/Users/emile/Git/@luxio-lighting/.tools/cadquery-venv/bin/python')
args = parser.parse_args()
args.evidence_dir.mkdir(parents=True, exist_ok=True)
board_hash = hashlib.sha256(args.board.read_bytes()).hexdigest()
tools = root/'Source/tools'
cases = [('usb-all-0p1', '.10', []), ('usb-all-0p05', '.05', []), ('usb-positive-0p025', '.025', ['--nets', 'USB_5V'])]
for label, resolution, net_args in cases:
    command = [args.kicad_python, str(tools/'current_path_mesh.py'), str(args.board), '--resolution', resolution, '--output', str(args.evidence_dir/(label+'-mesh.json'))] + net_args
    print('Extracting', label, flush=True)
    subprocess.run(command, check=True)
    assert hashlib.sha256(args.board.read_bytes()).hexdigest() == board_hash, 'Board changed during extraction'
with ThreadPoolExecutor(max_workers=2) as executor:
    futures = []
    for label, resolution, net_args in cases:
        for plating in [25, 20, 18]:
            stem = label+'-'+str(plating)+'um'
            command = [args.solver_python, str(tools/'current_path_solve_sparse.py'), str(args.evidence_dir/(label+'-mesh.json')), '--board', str(args.board), '--current-a', '3', '--copper-um', '35', '--board-thickness-mm', '1.6', '--via-plating-um', str(plating), '--report', str(args.evidence_dir/(stem+'-estimate.txt')), '--json-output', str(args.evidence_dir/(stem+'-results.json'))]
            futures.append((stem, executor.submit(subprocess.run, command, check=True, capture_output=True, text=True)))
    for stem, future in futures:
        result = future.result()
        print('Solved', stem, result.stdout.strip(), flush=True)
assert hashlib.sha256(args.board.read_bytes()).hexdigest() == board_hash, 'Board changed during solve'
subprocess.run([args.solver_python, str(tools/'review_current_paths_adaptive.py'), '--board', str(args.board), '--evidence-dir', str(args.evidence_dir), '--report', str(args.report)], check=True)
print('Finished current-path review for', board_hash, flush=True)
