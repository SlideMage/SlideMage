"""Test the research's mylatexformat approach against the actual manual preamble.

Run only outside timed benchmarks. Retains diagnostic output even on failure.
"""
import json
import argparse
import re
import os
from pathlib import Path
import subprocess
import time
from slidemage import deck_scan, project

parser = argparse.ArgumentParser(__doc__)
parser.add_argument("--scope", choices=("full", "class"), default="full")
args = parser.parse_args()
root = project.transitional_context().root
out = root / '.build' / ('format-probe-' + args.scope)
out.mkdir(parents=True, exist_ok=True)
deck = next(d for d in deck_scan.scan_decks(project.transitional_context()) if d.name == 'slidemage-manual')
source = root / 'decks' / '_slidemage_format_probe.tex'
preamble = deck.preamble_text
if args.scope == 'class':
    preamble = re.sub(r'(\\documentclass(?:\[[^\]]*\])?\{[^}]*\})', lambda m: m[0] + '\n\\csname endofdump\\endcsname\n', preamble, count=1)
source.write_text(preamble + '\n\\slide{1jh-EN-Title-Slide}\n\\end{document}\n')
env = dict(os.environ)
env['TEXINPUTS'] = os.pathsep.join([str(root), str(Path(__file__).resolve().parents[2] / 'latex'), env.get('TEXINPUTS', '')])
cmd = ['lualatex', '-ini', '-interaction=nonstopmode', '-halt-on-error', '-recorder',
       '-jobname=manual-preview', f'-output-directory={out}', '&lualatex', 'mylatexformat.ltx', str(source)]
start = time.perf_counter()
proc = subprocess.run(cmd, cwd=root/'decks', env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
(out/'dump-output.txt').write_text(proc.stdout)
result = dict(dump_seconds=time.perf_counter()-start, dump_returncode=proc.returncode)
if proc.returncode == 0:
    start = time.perf_counter()
    proc = subprocess.run(['lualatex', f'-fmt={out}/manual-preview.fmt', '-interaction=nonstopmode', '-halt-on-error', f'-output-directory={out}', str(source)], cwd=root/'decks', env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out/'restore-output.txt').write_text(proc.stdout)
    result.update(restore_seconds=time.perf_counter()-start, restore_returncode=proc.returncode)
(out/'result.json').write_text(json.dumps(result, indent=2))
source.unlink()
print(result)
