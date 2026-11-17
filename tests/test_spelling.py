# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The dictionary checker (spelling/, docs/plans/ai-spellchecker.md step 2, test 5).

No real download: German is checked against a tiny Hunspell dictionary in tests/fixtures/spelling/ (a compound
rule and two endings), the word lists are written here, and downloads come from a local server."""
from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import json
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from slidemage import project
from slidemage.spelling import catalogue, dictionaries, settings
from slidemage.spelling.catalogue import DictFile, Dictionary
from slidemage.spelling.checker import SpellingUnavailable, checkable
from slidemage.spelling.dictionary_checker import DictionaryChecker

FIXTURES = Path(__file__).with_name("fixtures") / "spelling"
ROOT = Path(__file__).resolve().parents[1]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _AT(language: str) -> str:
    """German in de-AT; the test catalogue's English is a word list without variants."""
    return {"de": "AT"}.get(language, "")


class _Server:
    """Serves `files` (path -> bytes). A path in `truncate` sends its full Content-Length but only half the body."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.truncate: set[str] = set()
        self.requests: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(self.path)
                data = outer.files.get(self.path)
                if data is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data[:len(data) // 2] if self.path in outer.truncate else data)
                except OSError:
                    pass
                if self.path in outer.truncate:
                    self.close_connection = True

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


def _wordlist(words: dict[str, int]) -> bytes:
    return gzip.compress(json.dumps(words).encode("utf-8"), mtime=0)


EN_WORDS = {"the": 1000, "ten": 50, "tea": 40, "receive": 30, "relieve": 10, "don't": 20, "colour": 5, "slide": 25,
            "internationalization": 1}


def _entries(server: _Server) -> dict[str, Dictionary]:
    """A catalogue of a German (Hunspell) and an English (word list) dictionary served by `server`."""
    aff = (FIXTURES / "de_TEST.aff").read_bytes()
    dic = (FIXTURES / "de_TEST.dic").read_bytes()
    en = _wordlist(EN_WORDS)
    server.files.update({"/de_AT_frami.aff": aff, "/de_AT_frami.dic": dic, "/en.json.gz": en})
    german = tuple(DictFile(name, f"{server.url}/{name}", len(data), _sha(data))
                   for name, data in (("de_AT_frami.aff", aff), ("de_AT_frami.dic", dic)))
    return {
        "de_AT": Dictionary("de_AT", "de", "hunspell", "the German (Austria) dictionary", german),
        "en": Dictionary("en", "en", "wordlist", "the English dictionary",
                         (DictFile("en.json.gz", f"{server.url}/en.json.gz", len(en), _sha(en)),)),
    }


@pytest.fixture
def checker(server, tmp_path):
    c = DictionaryChecker(base=tmp_path / "dicts", variant=_AT, entries=_entries(server))
    assert c.prepare("de") and c.prepare("en")
    return c


# -- which words are looked up ---------------------------------------------------------------------------------

@pytest.mark.parametrize("word, expected", [
    ("house", True), ("House", True), ("Häuser", True), ("don't", True), ("don’t", True),
    ("a", False), ("PDF", False), ("OECD", False), ("SlideMage", False), ("iPhone", False), ("''", False),
])
def test_checkable(word, expected):
    assert checkable(word) is expected


# -- German: Hunspell --------------------------------------------------------------------------------------------

def test_german_knows_compounds_and_endings(checker):
    words = ["Nachfrageüberhang", "Nachfrage", "Vorlesung", "Vorlesungen", "Haus", "Hause", "Jänner", "Straße",
             "Studierende"]
    assert checker.unknown("de", words) == set()


def test_german_unknown_words(checker):
    words = ["Vorlesnug", "Strasse", "überhang", "Studirende", "Nachfrageüberhang"]
    assert checker.unknown("de", words) == {"Vorlesnug", "Strasse", "überhang", "Studirende"}


def test_german_suggestions_best_first(checker):
    assert next(checker.suggest("de", "Vorlesnug")) == "Vorlesung"
    assert "Studierende" in list(checker.suggest("de", "Studirende"))


def test_names_and_capitals_are_never_unknown(checker):
    assert checker.unknown("de", ["SlideMage", "PDF", "x"]) == set()
    assert checker.unknown("en", ["SlideMage", "OECD"]) == set()


# -- other languages: word lists -------------------------------------------------------------------------------

def test_word_list_ignores_case_and_reads_typographic_apostrophes(checker):
    assert checker.unknown("en", ["The", "the", "don't", "don’t", "Slide", "colour"]) == set()
    assert checker.unknown("en", ["teh", "Recieve", "the"]) == {"teh", "Recieve"}


def test_word_list_suggestions_keep_the_capital_and_go_by_frequency(checker):
    assert list(checker.suggest("en", "Teh"))[:3] == ["The", "Ten", "Tea"]
    assert next(checker.suggest("en", "recieve")) == "receive"
    assert next(checker.suggest("en", "internationalizaton")) == "internationalization"


def test_answers_are_cached(checker, monkeypatch):
    from slidemage.spelling import dictionary_checker

    calls = []
    real = dictionary_checker._is_known
    monkeypatch.setattr(dictionary_checker, "_is_known", lambda *a: calls.append(a[2]) or real(*a))
    checker.unknown("en", ["teh", "the"])
    checker.unknown("en", ["teh", "the", "tea"])
    assert calls == ["teh", "the", "tea"]


def test_unsupported_language_and_not_prepared(server, tmp_path):
    c = DictionaryChecker(base=tmp_path, variant=_AT, entries=_entries(server))
    assert c.languages() == {"de", "en"}
    assert c.prepare("xx") is False and c.dictionary_for("xx") is None
    with pytest.raises(SpellingUnavailable):
        c.unknown("en", ["the"])
    assert not c.is_ready("en")


# -- the German variant -------------------------------------------------------------------------------------------

def test_variant_settings_default_to_austria_and_america_and_persist():
    assert settings.german_variant() == "AT" and settings.english_variant() == "US"
    assert settings.variant("fr") == ""
    assert settings.store_path().parent == project.config_dir()
    settings.set_german_variant("CH")
    settings.set_english_variant("GB")
    assert settings.german_variant() == "CH" and settings.variant("EN") == "GB"
    with pytest.raises(ValueError):
        settings.set_german_variant("BE")
    with pytest.raises(ValueError):
        settings.set_variant("fr", "FR")
    settings.store_path().write_text('{"de_variant": "XX", "en_variant": "AU"}', encoding="utf-8")
    assert settings.german_variant() == "AT" and settings.english_variant() == "US"


def test_the_german_variant_stored_before_v0_17_20_is_still_read():
    settings.store_path().parent.mkdir(parents=True, exist_ok=True)
    settings.store_path().write_text('{"german_variant": "DE"}', encoding="utf-8")
    assert settings.german_variant() == "DE"
    settings.set_german_variant("CH")
    assert json.loads(settings.store_path().read_text(encoding="utf-8")) == {"de_variant": "CH"}


def test_the_variant_picks_the_dictionary_at_each_call(tmp_path):
    chosen = {"de": "AT", "en": "GB"}
    c = DictionaryChecker(base=tmp_path, variant=lambda language: chosen.get(language, ""))
    assert c.dictionary_for("de").key == "de_AT" and c.dictionary_for("en").key == "en_GB"
    chosen.update(de="DE", en="US")
    assert c.dictionary_for("DE").key == "de_DE"
    assert c.dictionary_for("de").files[1].name == "de_DE_frami.dic"
    assert [f.name for f in c.dictionary_for("en").files] == ["en_US.aff", "en_US.dic"]
    assert c.dictionary_for("en").engine == "hunspell" and c.dictionary_for("fr").engine == "wordlist"


def test_the_checker_reads_the_settings_by_default(tmp_path):
    assert DictionaryChecker(base=tmp_path).dictionary_for("en").key == "en_US"
    settings.set_english_variant("GB")
    assert DictionaryChecker(base=tmp_path).dictionary_for("en").key == "en_GB"


# -- the catalogue -------------------------------------------------------------------------------------------------

def test_catalogue_is_pinned():
    assert set(catalogue.supported_languages()) == {"de", "en", *catalogue.PYSPELLCHECKER_LANGUAGES}
    used = {f.name for entry in catalogue.CATALOGUE.values() for f in entry.files}
    assert used == set(catalogue.FILES)
    for entry in catalogue.CATALOGUE.values():
        for f in entry.files:
            assert re.fullmatch(r"[0-9a-f]{64}", f.sha256) and f.size > 0
            assert f.url.startswith("https://raw.githubusercontent.com/")
            commit = catalogue.LIBREOFFICE_COMMIT if entry.engine == "hunspell" else catalogue.PYSPELLCHECKER_COMMIT
            assert f"/{commit}/" in f.url
    assert catalogue.dictionary_for("de", "CH").key == "de_CH" and catalogue.dictionary_for("EN").key == "en_US"
    assert catalogue.dictionary_for("en", "US").label == "the English (United States) dictionary"
    assert catalogue.dictionary_for("de", "XX").key == "de_AT"          # an unknown variant: the default
    assert catalogue.dictionary_for("xx") is None and catalogue.dictionary_for("fr").key == "fr"
    english = catalogue.dictionary_for("en", "GB").files[1]
    assert english.url.endswith(f"/{catalogue.LIBREOFFICE_COMMIT}/en/en_GB.dic")
    assert sorted(catalogue.hunspell_files()) == sorted(name for name in catalogue.FILES if "json" not in name)


def test_the_pinned_word_lists_are_those_of_the_pinned_pyspellchecker():
    pin = f'"pyspellchecker=={catalogue.PYSPELLCHECKER_VERSION}"'
    assert pin in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert importlib.metadata.version("pyspellchecker") == catalogue.PYSPELLCHECKER_VERSION
    import spellchecker

    resources = Path(spellchecker.__file__).parent / "resources"
    for code in catalogue.PYSPELLCHECKER_LANGUAGES:
        data = (resources / f"{code}.json.gz").read_bytes()
        assert (len(data), _sha(data)) == catalogue.FILES[f"{code}.json.gz"], code


def test_the_build_leaves_the_word_lists_out():
    spec = (ROOT / "packaging" / "slidemage.spec").read_text(encoding="utf-8")
    assert "spellchecker/resources" in spec


# -- the download ----------------------------------------------------------------------------------------------------

def test_download_installs_and_reports_progress(server, tmp_path):
    entry = _entries(server)["de_AT"]
    seen = []
    target = dictionaries.ensure(entry, lambda done, total, message: seen.append((done, total, message)),
                                 base=tmp_path)
    assert sorted(p.name for p in target.iterdir()) == ["de_AT_frami.aff", "de_AT_frami.dic"]
    assert dictionaries.installed(entry, tmp_path)
    assert seen[-1][0] == seen[-1][1] == entry.size
    assert seen[0][2] == "Downloading the German (Austria) dictionary (1 MB)…"
    server.requests.clear()
    dictionaries.ensure(entry, base=tmp_path)
    assert server.requests == []          # intact files are not fetched again


def test_a_wrong_hash_is_refused_and_leaves_nothing(server, tmp_path):
    entry = _entries(server)["en"]
    server.files["/en.json.gz"] = _wordlist({"tampered": 1}).ljust(entry.size, b"\0")[:entry.size]
    with pytest.raises(SpellingUnavailable, match="not the file SlideMage expects"):
        dictionaries.ensure(entry, base=tmp_path)
    assert list((tmp_path / "en").iterdir()) == []


def test_a_wrong_size_is_refused_before_the_body(server, tmp_path):
    entry = _entries(server)["en"]
    server.files["/en.json.gz"] += b"more"
    with pytest.raises(SpellingUnavailable, match="newer SlideMage"):
        dictionaries.ensure(entry, base=tmp_path)
    assert list((tmp_path / "en").iterdir()) == []


def test_an_interrupted_download_leaves_nothing_and_a_retry_works(server, tmp_path):
    entry = _entries(server)["de_AT"]
    server.truncate.add("/de_AT_frami.dic")
    with pytest.raises(SpellingUnavailable, match="could not be downloaded|not the file"):
        dictionaries.ensure(entry, base=tmp_path)
    left = sorted(p.name for p in (tmp_path / "de_AT").iterdir())
    assert left == ["de_AT_frami.aff"]    # the intact first file stays; no .part, no half .dic
    server.truncate.clear()
    server.requests.clear()
    dictionaries.ensure(entry, base=tmp_path)
    assert server.requests == ["/de_AT_frami.dic"]
    assert dictionaries.installed(entry, tmp_path)


def test_a_damaged_file_and_a_stale_part_are_replaced(server, tmp_path):
    entry = _entries(server)["en"]
    dictionaries.ensure(entry, base=tmp_path)
    (tmp_path / "en" / "en.json.gz").write_bytes(b"broken")
    (tmp_path / "en" / "en.json.gz.part-deadbeef").write_bytes(b"left by a crash")
    assert not dictionaries.installed(entry, tmp_path)
    dictionaries.ensure(entry, base=tmp_path)
    assert [p.name for p in (tmp_path / "en").iterdir()] == ["en.json.gz"]
    assert dictionaries.installed(entry, tmp_path)


def test_no_server_gives_a_message(tmp_path):
    entry = Dictionary("en", "en", "wordlist", "the English dictionary",
                       (DictFile("en.json.gz", "http://127.0.0.1:9/en.json.gz", 10, "0" * 64),))
    with pytest.raises(SpellingUnavailable, match="^The English dictionary could not be downloaded: "):
        dictionaries.ensure(entry, base=tmp_path, timeout=2)
    entry = Dictionary("en", "en", "wordlist", "the English dictionary",
                       (DictFile("en.json.gz", "file:///etc/passwd", 10, "0" * 64),))
    with pytest.raises(SpellingUnavailable, match="not an http"):
        dictionaries.ensure(entry, base=tmp_path)


def test_prepare_downloads_once_and_says_so(server, tmp_path):
    c = DictionaryChecker(base=tmp_path, variant=_AT, entries=_entries(server))
    assert c.needs_download("en") and not c.needs_download("xx")
    messages = []
    assert c.prepare("en", lambda done, total, message: messages.append(message))
    assert messages[0].startswith("Downloading the English dictionary") and messages[-1].startswith("Loading")
    assert c.is_ready("en") and not c.needs_download("en")
    server.requests.clear()
    assert c.prepare("en") and server.requests == []


def test_the_default_folder_is_this_machines_cache():
    assert dictionaries.folder(catalogue.CATALOGUE["fr"]) == project.cache_dir() / "dictionaries" / "fr"
    assert dictionaries.folder(catalogue.CATALOGUE["en_GB"]) == project.cache_dir() / "dictionaries" / "en_GB"


def test_a_file_that_does_not_load_is_reported(server, tmp_path):
    entries = _entries(server)
    bad = _wordlist({}).replace(b"\x1f\x8b", b"xx", 1)   # not gzip any more
    server.files["/en.json.gz"] = bad
    entries["en"] = Dictionary("en", "en", "wordlist", "the English dictionary",
                               (DictFile("en.json.gz", f"{server.url}/en.json.gz", len(bad), _sha(bad)),))
    c = DictionaryChecker(base=tmp_path, variant=_AT, entries=entries)
    with pytest.raises(SpellingUnavailable, match="^The English dictionary could not be loaded"):
        c.prepare("en")
    assert not c.is_ready("en")


def test_real_files_when_the_pinned_lists_are_installed(tmp_path):
    """The real French list from the installed pyspellchecker, checked like a download (no network)."""
    import spellchecker

    source = Path(spellchecker.__file__).parent / "resources" / "fr.json.gz"
    entry = catalogue.CATALOGUE["fr"]
    (tmp_path / "fr").mkdir()
    shutil.copy(source, tmp_path / "fr" / "fr.json.gz")
    c = DictionaryChecker(base=tmp_path)
    assert not c.needs_download("fr") and c.prepare("fr")
    assert c.unknown("fr", ["Le", "renard", "diapositive", "renrad"]) == {"renrad"}
    assert entry.size == source.stat().st_size
