# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The languages SlideMage knows, and the languages of a project.

The table has a code (ISO 639-1, lower case), the English and the native name, and the default PDF language
tag. `project_languages(ctx)` reads the project's own list from .slidemage/project.json, which is shared with
the project:

    "languages": {"main": "en", "secondary": ["de", "fr"]}

A project without the key has English as its main and German as its secondary language, and nothing is written
until the user changes them (`is_default`). In slide file names the codes are upper case (`FR`); `mult` is
reserved for multilingual slides and is not a language. No Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import project
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


DEFAULT = Languages(main="en", secondary=("de",))


def _valid(code) -> bool:
    return isinstance(code, str) and len(code) == 2 and code.isascii() and code.isalpha() and code.islower()


def _parse(value) -> Languages:
    """The list in project.json; the default for a missing or malformed key. A repeated code counts once."""
    if not isinstance(value, dict) or not _valid(value.get("main")):
        return DEFAULT
    secondary = value.get("secondary", [])
    if not isinstance(secondary, list):
        return DEFAULT
    main = value["main"]
    return Languages(main, tuple(dict.fromkeys(c for c in secondary if _valid(c) and c != main)))


# project.json path -> ((modification time, size), what it said): the render keys ask for every unit.
_cache: dict[str, tuple[tuple[int, int], Languages]] = {}


def project_languages(ctx: ProjectContext) -> Languages:
    """The project's languages, main first; read again when project.json has changed."""
    path = ctx.root / project.PROJECT_INFO_PATH
    try:
        info = path.stat()
    except OSError:
        return DEFAULT
    stamp = (info.st_mtime_ns, info.st_size)
    cached = _cache.get(str(path))
    if cached is None or cached[0] != stamp:
        cached = _cache[str(path)] = (stamp, _parse(project.read_project_json(ctx.root).get(KEY)))
    return cached[1]


def set_project_languages(ctx: ProjectContext, main: str, secondary: list[str] | tuple[str, ...]) -> None:
    """Write the project's languages (lower case codes, `main` not among `secondary`), keeping the other keys."""
    value = _parse({"main": main, "secondary": list(secondary)})
    if value.main != main:
        raise ValueError(f"not a language code: {main!r}")
    data = project.read_project_json(ctx.root)
    data[KEY] = {"main": value.main, "secondary": list(value.secondary)}
    project.write_project_json(ctx.root, data)
    _cache.pop(str(ctx.root / project.PROJECT_INFO_PATH), None)


def is_default(ctx: ProjectContext) -> bool:
    """Whether the project has the languages of a project that never changed them: SlideMage then writes
    exactly what it always wrote."""
    return project_languages(ctx) == DEFAULT
