# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The languages SlideMage knows, and the languages of a project.

The table has a code (ISO 639-1, lower case), the English and the native name, and the default PDF language
tag. `project_languages(ctx)` reads the project's own list from .slidemage/project.json, which is shared with
the project:

    "languages": {"main": "en", "secondary": ["de", "fr"]}

Every project states its languages. A project from before the key existed gets it when SlideMage opens it
(`migrate`): English as the main language, German as the secondary one if the project uses German anywhere, no
secondary language otherwise (`infer`). In slide file names the codes are upper case (`FR`); `mult` is reserved for
multilingual slides and is not a language. No Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import project
from .deck_settings import LANGUAGE_RE
from .fileio import read_json
from .project import ProjectContext

KEY = "languages"


@dataclass(frozen=True)
class Language:
    code: str
    english: str
    native: str
    pdf_tag: str


TABLE: tuple[Language, ...] = tuple(Language(*row) for row in (
    ("en", "English", "English", "en-US"),
    ("de", "German", "Deutsch", "de-DE"),
    ("fr", "French", "français", "fr-FR"),
    ("es", "Spanish", "español", "es-ES"),
    ("it", "Italian", "italiano", "it-IT"),
    ("pt", "Portuguese", "português", "pt-PT"),
    ("nl", "Dutch", "Nederlands", "nl-NL"),
    ("pl", "Polish", "polski", "pl-PL"),
    ("cs", "Czech", "čeština", "cs-CZ"),
    ("sk", "Slovak", "slovenčina", "sk-SK"),
    ("sl", "Slovenian", "slovenščina", "sl-SI"),
    ("hr", "Croatian", "hrvatski", "hr-HR"),
    ("sr", "Serbian", "српски", "sr-RS"),
    ("hu", "Hungarian", "magyar", "hu-HU"),
    ("ro", "Romanian", "română", "ro-RO"),
    ("bg", "Bulgarian", "български", "bg-BG"),
    ("el", "Greek", "Ελληνικά", "el-GR"),
    ("tr", "Turkish", "Türkçe", "tr-TR"),
    ("ru", "Russian", "русский", "ru-RU"),
    ("uk", "Ukrainian", "українська", "uk-UA"),
    ("da", "Danish", "dansk", "da-DK"),
    ("sv", "Swedish", "svenska", "sv-SE"),
    ("no", "Norwegian", "norsk", "nb-NO"),
    ("fi", "Finnish", "suomi", "fi-FI"),
    ("is", "Icelandic", "íslenska", "is-IS"),
    ("et", "Estonian", "eesti", "et-EE"),
    ("lv", "Latvian", "latviešu", "lv-LV"),
    ("lt", "Lithuanian", "lietuvių", "lt-LT"),
    ("ga", "Irish", "Gaeilge", "ga-IE"),
    ("mt", "Maltese", "Malti", "mt-MT"),
    ("ca", "Catalan", "català", "ca-ES"),
    ("eu", "Basque", "euskara", "eu-ES"),
    ("gl", "Galician", "galego", "gl-ES"),
    ("ar", "Arabic", "العربية", "ar-SA"),
    ("he", "Hebrew", "עברית", "he-IL"),
    ("fa", "Persian", "فارسی", "fa-IR"),
    ("hi", "Hindi", "हिन्दी", "hi-IN"),
    ("zh", "Chinese", "中文", "zh-CN"),
    ("ja", "Japanese", "日本語", "ja-JP"),
    ("ko", "Korean", "한국어", "ko-KR"),
    ("vi", "Vietnamese", "Tiếng Việt", "vi-VN"),
    ("th", "Thai", "ไทย", "th-TH"),
    ("id", "Indonesian", "Bahasa Indonesia", "id-ID"),
    ("ms", "Malay", "Bahasa Melayu", "ms-MY"),
))
_BY_CODE = {language.code: language for language in TABLE}


def get(code: str) -> Language | None:
    """The table's entry for `code` (any case), None for a code it does not have."""
    return _BY_CODE.get(code.lower())


def name(code: str) -> str:
    """The English name of the language; an unknown code is its own name."""
    language = get(code)
    return language.english if language else code


def pdf_tag(code: str) -> str:
    """The default PDF language tag of the language ("fr-FR"); an unknown code is its own tag."""
    language = get(code)
    return language.pdf_tag if language else code


@dataclass(frozen=True)
class Languages:
    main: str
    secondary: tuple[str, ...] = ()

    @property
    def lower(self) -> tuple[str, ...]:
        """Every language, main first, as stored."""
        return (self.main, *self.secondary)

    @property
    def codes(self) -> tuple[str, ...]:
        """Every language, main first, as slide file names write them ("EN", "DE", "FR")."""
        return tuple(code.upper() for code in self.lower)

    def as_json(self) -> dict:
        """What project.json stores under the key."""
        return {"main": self.main, "secondary": list(self.secondary)}




def _valid(code) -> bool:
    return isinstance(code, str) and len(code) == 2 and code.isascii() and code.isalpha() and code.islower()


def _parse(value) -> Languages | None:
    """The list in project.json; None for a missing or malformed key. A repeated code counts once."""
    if not isinstance(value, dict) or not _valid(value.get("main")):
        return None
    secondary = value.get("secondary", [])
    if not isinstance(secondary, list):
        return None
    main = value["main"]
    return Languages(main, tuple(dict.fromkeys(c for c in secondary if _valid(c) and c != main)))


def _slides_use_german(ctx: ProjectContext) -> bool:
    return any(path.name.split("-", 2)[1:2] == ["DE"] for path in ctx.slides_dir.glob("*.tex"))


def _decks_use_german(ctx: ProjectContext) -> bool:
    return any(match.group(1).strip().lower() == "de"
               for folder in (ctx.decks_dir, ctx.archive_dir) for path in folder.glob("*.tex")
               for match in LANGUAGE_RE.finditer(path.read_text(encoding="utf-8", errors="replace")))


def _descriptions_use_german(ctx: ProjectContext) -> bool:
    images = read_json(ctx.media_dir / "alt-text.json").get("images")
    german = ("short_de", "long_de", "source_de", "takeaway_default_de")
    return any(isinstance(image, dict) and (any(image.get(key) for key in german) or any(
        isinstance(use, dict) and use.get("takeaway_de") for use in (image.get("used_on") or {}).values()))
        for image in (images.values() if isinstance(images, dict) else ()))


def infer(ctx: ProjectContext) -> Languages:
    """The languages of a project that has not stated them, as SlideMage worked before the key existed: English
    is the main language, German the secondary one if any slide file is tagged DE, any deck sets `\\decklanguage[de]`,
    any image description has German text or the project has a German form of address; no secondary language
    otherwise. Reads the project's files."""
    german = ("de_address" in project.read_project_json(ctx.root) or _slides_use_german(ctx)
              or _decks_use_german(ctx) or _descriptions_use_german(ctx))
    return Languages("en", ("de",) if german else ())


# project.json path -> ((modification time, size) or None for no file, the languages): the render keys ask for
# every unit. A project without the key is inferred once and then kept, until the file changes.
_cache: dict[str, tuple[tuple[int, int] | None, Languages]] = {}


def project_languages(ctx: ProjectContext) -> Languages:
    """The project's languages, main first: the key in project.json, or what `infer` finds for a project that has
    none (nothing is written: `migrate` does that when the project is opened). Read again when project.json
    changes."""
    path = ctx.root / project.PROJECT_INFO_PATH
    try:
        info = path.stat()
        stamp = (info.st_mtime_ns, info.st_size)
    except OSError:
        stamp = None
    cached = _cache.get(str(path))
    if cached is None or cached[0] != stamp:
        found = _parse(project.read_project_json(ctx.root).get(KEY)) or infer(ctx)
        cached = _cache[str(path)] = (stamp, found)
    return cached[1]


def migrate(ctx: ProjectContext) -> None:
    """Write the languages key into a project that has none, with what `infer` finds, keeping the other keys.
    Called once when a project is opened; a project folder that cannot be written keeps working with the inferred
    languages."""
    data = project.read_project_json(ctx.root)
    if KEY in data:
        return
    found = infer(ctx)
    try:
        set_project_languages(ctx, found.main, found.secondary)
    except OSError:
        pass


def set_project_languages(ctx: ProjectContext, main: str, secondary: list[str] | tuple[str, ...]) -> None:
    """Write the project's languages (lower case codes, `main` not among `secondary`), keeping the other keys."""
    value = _parse({"main": main, "secondary": list(secondary)})
    if value is None:
        raise ValueError(f"not a language code: {main!r}")
    data = project.read_project_json(ctx.root)
    data[KEY] = value.as_json()
    project.write_project_json(ctx.root, data)
    _cache.pop(str(ctx.root / project.PROJECT_INFO_PATH), None)
