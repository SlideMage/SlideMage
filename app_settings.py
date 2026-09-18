"""Local SlideMage UI preferences -- dark mode, plus (2026-08-25,
direct instruction) the last-picked drafting/translation models
(qt_transcript_tab.py's "drafting_model"/"translation_model" keys, read
back by _populate_models()/_populate_translation_models() to preselect
whichever was last used, if it's still installed). A plain JSON file
living inside SlideMage/ itself, not the Windows registry (2026-08-25,
direct instruction, replacing an earlier QSettings-based design used for
one day: "I want everything pertaining to SlideMage to be saved in its
proper folder, and for the app to work as long as that folder is
synched"). This project's entire folder already lives in a synced
location (D:\\uniCLOUD\\...); a registry entry is tied to one specific
PC's own registry and would NOT travel with the folder to another machine
the way a plain file inside it does.

Gitignored (see .gitignore) -- unlike translation_prompts.py's own store,
this is a personal UI preference, not project content worth version-
controlling or diffing on every toggle, but it still needs to physically
sit inside the synced folder tree for the cloud-sync client itself (not
git) to carry it across machines -- same category as dist/SlideMage.exe
(git-ignored, not sync-ignored; see .gitignore's own comment on that).

STORE_PATH is resolved from deck_scan.PROJECT_ROOT, not
Path(__file__).resolve().parent (2026-08-26, direct report -- both this
and translation_prompts.py's own store were found empty on every launch
of the compiled exe). deck_scan.py's own _find_project_root() already
documents why: PyInstaller's one-file build extracts to a fresh temp
directory on every launch and deletes it on exit, so `__file__` inside a
frozen exe points into that throwaway location, not the real,
persistent SlideMage/ folder next to the actual .exe on disk -- a
save "worked" (no error) but landed somewhere that no longer existed by
the next launch, and a load right after just found nothing there yet.
Never hit this running un-frozen (`python -m SlideMage`), which is
almost certainly why it passed every headless test this session -- none
of them ran from the actual compiled exe.
"""
from __future__ import annotations

import json
from typing import Any

from .deck_scan import PROJECT_ROOT

STORE_PATH = PROJECT_ROOT / "SlideMage" / "app_settings.json"


def load() -> dict[str, Any]:
    if not STORE_PATH.is_file():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save(settings: dict[str, Any]) -> None:
    STORE_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set(key: str, value: Any) -> None:
    settings = load()
    settings[key] = value
    save(settings)
