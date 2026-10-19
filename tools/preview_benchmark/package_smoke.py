# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke an actual frozen SlideMage executable and its persistent raster child."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from slidemage import preview_raster


def run(binary, output):
    import pymupdf
    output.mkdir(parents=True, exist_ok=False)
    pdf = output / 'probe.pdf'
    with pymupdf.open() as doc:
        for text in ('First reveal', 'Last reveal'):
            doc.new_page(width=320, height=180).insert_text((20, 30), text)
        doc.save(pdf)
    help_result = subprocess.run([str(binary), '--help'], capture_output=True, text=True, timeout=60)
    assert help_result.returncode == 0 and '--project' in help_result.stdout, help_result.stderr
    requests = [dict(op='pdf_images', path=str(pdf), start=1, count=2, dpi=130),
                dict(op='sequence', pdf=base64.b64encode(pdf.read_bytes()).decode('ascii'))]
    child = subprocess.run([str(binary), '--preview-raster'],
                           input=''.join(json.dumps(item) + '\n' for item in requests),
                           capture_output=True, text=True, timeout=60)
    assert child.returncode == 0, child.stderr
    replies = [json.loads(line) for line in child.stdout.splitlines()]
    assert len(replies) == 2 and all(reply['ok'] for reply in replies), child.stdout
    expected = preview_raster.document(pdf, 'pdf_images', 1, 2, 130)
    assert [base64.b64decode(item) for item in replies[0]['images']] == expected['images']
    assert replies[1]['signature'] == preview_raster.sequence(pdf.read_bytes())['signature']
    result = dict(binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  help=True, persistent_raster_requests=2, page_images_equal=True,
                  full_sequence_equal=True)
    (output / 'results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.binary.resolve(), args.output.resolve())
