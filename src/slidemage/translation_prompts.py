"""Per-(model, source language, target language) translation prompt
configuration -- lets the Settings dialog tune exactly how
alt_draft.ModelTranslationBackend talks to a given Ollama model, since
different models expect very different prompt shapes: a dedicated MT
model (e.g. sun_leaf/HY-MT) wants a short, plain instruction with an
exact blank-line count before the text; a general instruction-tuned
model (e.g. translategemma) may want a longer, more explicit one.

Two levels of fallback when resolving a prompt (get_effective_prompt()):
a model+pair-specific entry if one exists, else the single **default**
prompt (also user-editable, 2026-08-25 direct instruction -- initially
set to the translategemma:27b prompt, since that one reads as a solid
general-purpose instruction unlikely to be specific to any one model),
else a last-resort hardcoded fallback for a completely fresh install
that has never had a default set at all.

Tracked in git (unlike SlideMage's own UI preferences -- see
ui/kit/theme.py's dark-mode QSettings use, a deliberately different, per-
machine store) since this is genuinely project config: which models
translate this project's content, and exactly how, is worth sharing/
versioning the same way Slidemaster.bib or slide_ids.csv are, not left
as one machine's own throwaway local state.

On-disk shape (media/alt-text.json-style: plain nested dict, human-
readable, hand-editable in a pinch):

    {
      "default": {"prompt": "...", "blank_lines": 2},
      "models": {
        "sun_leaf/HY-MT:7b": {
          "en": {"de": {"prompt": "Translate...", "blank_lines": 1}}
        }
      }
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .deck_scan import PROJECT_ROOT

# Lives in the project's .slidemage/ folder, so shared prompts travel with
# the project (this file is meant to be committed).
STORE_PATH = PROJECT_ROOT / ".slidemage" / "translation_prompts.json"

# Nested-dict shape for the "models" section: {model: {source_lang:
# {target_lang: PromptConfig}}}.
ModelPromptStore = dict[str, dict[str, dict[str, "PromptConfig"]]]

# Last-resort fallback (2026-08-25) -- only reached when get_default_prompt()
# itself returns None, i.e. a fresh install where nobody has set a default
# prompt yet. Mirrors this project's own original TRANSLATION_SYSTEM_PROMPT
# wording, reshaped into the single-message form every configured prompt
# now uses (see PromptConfig.build_message).
_FALLBACK_DEFAULT = None  # set below, after PromptConfig is defined


@dataclass
class PromptConfig:
    prompt: str
    # Blank lines between `prompt` and the text to translate -- e.g. 1 for
    # "prompt line, one blank line, then the text", 2 for "...two blank
    # lines...". The whole thing is sent as a single message (no separate
    # system-role turn): some models tested here respond far more
    # reliably to one self-contained instruction+text block than to a
    # system/user split (see alt_draft.py's own history note on why the
    # combined-JSON, system-prompt approach was abandoned for the default
    # backend).
    blank_lines: int = 1

    def build_message(self, text: str) -> str:
        separator = "\n" * (self.blank_lines + 1)
        return f"{self.prompt}{separator}{text}"


_FALLBACK_DEFAULT = PromptConfig(
    prompt=(
        "You translate short image descriptions from a university finance "
        "course into German. Translate the following text faithfully into "
        "German -- not a rewrite, not a summary. If it contains a Markdown "
        "table, keep the table structure and numbers exactly as they are "
        "and translate only the surrounding prose and column headers. "
        "Output only the German translation, nothing else."
    ),
    blank_lines=1,
)


def _load_raw() -> dict:
    if not STORE_PATH.is_file():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _config_from_dict(cfg: dict) -> PromptConfig:
    return PromptConfig(prompt=cfg.get("prompt", ""), blank_lines=int(cfg.get("blank_lines", 1)))


def load_prompts() -> ModelPromptStore:
    raw = _load_raw().get("models", {})
    result: ModelPromptStore = {}
    for model, by_source in raw.items():
        result[model] = {}
        for source, by_target in by_source.items():
            result[model][source] = {}
            for target, cfg in by_target.items():
                result[model][source][target] = _config_from_dict(cfg)
    return result


def _save(default: Optional[PromptConfig], prompts: ModelPromptStore) -> None:
    raw: dict = {}
    if default is not None:
        raw["default"] = {"prompt": default.prompt, "blank_lines": default.blank_lines}
    raw["models"] = {
        model: {
            source: {
                target: {"prompt": cfg.prompt, "blank_lines": cfg.blank_lines}
                for target, cfg in by_target.items()
            }
            for source, by_target in by_source.items()
            if by_target
        }
        for model, by_source in prompts.items()
        if by_source
    }
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def save_prompts(prompts: ModelPromptStore) -> None:
    _save(get_default_prompt(), prompts)


def get_prompt(model: str, source_lang: str, target_lang: str) -> Optional[PromptConfig]:
    """The exact model+pair entry only -- None if nothing is configured
    for it specifically, even if a default prompt exists. Use
    get_effective_prompt() for "what should actually be sent"."""
    return load_prompts().get(model, {}).get(source_lang, {}).get(target_lang)


def set_prompt(model: str, source_lang: str, target_lang: str, config: PromptConfig) -> None:
    prompts = load_prompts()
    prompts.setdefault(model, {}).setdefault(source_lang, {})[target_lang] = config
    _save(get_default_prompt(), prompts)


def delete_prompt(model: str, source_lang: str, target_lang: str) -> bool:
    """True if a config was actually found and removed."""
    prompts = load_prompts()
    by_target = prompts.get(model, {}).get(source_lang, {})
    if target_lang not in by_target:
        return False
    del by_target[target_lang]
    if not by_target:
        del prompts[model][source_lang]
    if not prompts[model]:
        del prompts[model]
    _save(get_default_prompt(), prompts)
    return True


def list_configs() -> list[tuple[str, str, str, PromptConfig]]:
    """Every (model, source_lang, target_lang, config) currently stored,
    for the Settings dialog's own list view -- the default prompt is not
    included here, it has its own dedicated field in that dialog."""
    out: list[tuple[str, str, str, PromptConfig]] = []
    for model, by_source in sorted(load_prompts().items()):
        for source, by_target in sorted(by_source.items()):
            for target, cfg in sorted(by_target.items()):
                out.append((model, source, target, cfg))
    return out


def get_default_prompt() -> Optional[PromptConfig]:
    """The user-set default prompt, or None if nobody has set one yet
    (get_effective_prompt() falls back further, to _FALLBACK_DEFAULT, in
    that case -- this function itself stays a plain, honest "what's
    actually stored")."""
    raw = _load_raw().get("default")
    return _config_from_dict(raw) if raw else None


def set_default_prompt(config: PromptConfig) -> None:
    _save(config, load_prompts())


def effective_default_prompt() -> PromptConfig:
    """The prompt used for a model/language pair with no entry of its own:
    the user's default, else the hardcoded last-resort one."""
    return get_default_prompt() or _FALLBACK_DEFAULT


def get_effective_prompt(model: str, source_lang: str, target_lang: str) -> PromptConfig:
    """What ModelTranslationBackend should actually send: the exact
    model+pair entry if one exists, else the user's own default prompt,
    else a hardcoded last-resort default for a fresh install that has
    never configured anything at all. Always returns something usable --
    unlike get_prompt(), never None."""
    return get_prompt(model, source_lang, target_lang) or effective_default_prompt()
