import os
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "example"

# Must be set before any slidemage module computes PROJECT_ROOT at import.
os.environ["SLIDEMASTER_PROJECT"] = str(EXAMPLE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
