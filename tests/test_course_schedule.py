"""Uni Graz course schedule parsing and LaTeX rendering tests."""
from __future__ import annotations

from io import BytesIO

import pytest

from slidemage.course_schedule import (
    CourseGroup,
    CourseSchedule,
    CourseSession,
    fetch_schedule,
    parse_schedule,
    render_group_table,
    schedule_url,
)


COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
SCHEDULE_URL = "https://online.uni-graz.at/kfu_online/wbTvw_List.lehrveranstaltung?pStpSpNr=1002516"
HTML = b"""<!doctype html><meta charset="utf-8"><table id="tabLvTermine">
<caption>355.001 Management &amp; Science</caption><tbody>
<tr class="coTableGR1"><td colspan="8"><span>Standardgruppe</span></td></tr>
<tr><td>Mo</td><td>05.10.2026</td><td>09:00</td><td>10:00</td>
<td><a>SR 15.37 &amp; A</a></td><td>Abhaltung</td><td>fix</td><td>Vorbesprechung</td></tr>
<tr class="coTableGR1"><td colspan="8">Gruppe Wirtschaftsinformatik</td></tr>
<tr><td>Di</td><td>06.10.2026</td><td>08:30</td><td>10:00</td>
<td>HS 01</td><td>Pr\xc3\xbcfung</td><td>fix</td><td>R&amp;D 50% #1 _x_ {y} ~ ^ \\end</td></tr>
</tbody></table>"""


def test_parse_official_table_shape_and_multiple_groups():
    schedule = parse_schedule(HTML, SCHEDULE_URL)

    assert schedule.title == "355.001 Management & Science"
    assert [group.name for group in schedule.groups] == [
        "Standardgruppe", "Gruppe Wirtschaftsinformatik",
    ]
    first = schedule.groups[0].sessions[0]
    assert first == CourseSession(
        date="05.10.2026", start="09:00", end="10:00",
        location="SR 15.37 & A", event="Abhaltung", remark="Vorbesprechung",
    )
    assert schedule.groups[1].sessions[0].event == "Prüfung"


def test_parser_handles_empty_or_missing_table():
    assert parse_schedule("<html><body>none</body></html>", SCHEDULE_URL) == CourseSchedule("", ())
    empty = parse_schedule('<table id="tabLvTermine"><caption>Empty</caption><tbody></tbody></table>', SCHEDULE_URL)
    assert empty == CourseSchedule("Empty", ())


@pytest.mark.parametrize("bad_url", [
    "http://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1",
    "https://example.org/?pStpSpNr=1",
    "https://online.uni-graz.at/?pStpSpNr=abc",
    "https://online.uni-graz.at/?pStpSpNr=1&pStpSpNr=2",
])
def test_schedule_url_validates_course_url(bad_url):
    with pytest.raises(ValueError):
        schedule_url(bad_url)
    assert schedule_url(COURSE_URL) == SCHEDULE_URL


def test_renderer_escapes_latex_special_characters():
    group = parse_schedule(HTML, SCHEDULE_URL).groups[1]
    rendered = render_group_table(CourseSchedule("", (group,)), group)

    assert r"R\&D 50\% \#1 \_x\_ \{y\} \textasciitilde{} \textasciicircum{} \textbackslash{}end" in rendered
    assert r"\begin{tabular}" in rendered
    assert r"\toprule" in rendered
    assert r"\textbf{Gruppe Wirtschaftsinformatik}\par" in rendered
    assert "06.10.2026 & 08:30--10:00 & HS 01" in rendered


def test_renderer_handles_empty_group():
    assert render_group_table(CourseSchedule("", ()), CourseGroup("None & One", ())) == r"\small \textbf{None \& One}\par Keine Termine verfügbar."


def test_fetch_uses_schedule_url_and_redirect_target(monkeypatch):
    requested = []

    class Response(BytesIO):
        def geturl(self):
            return "https://online.uni-graz.at/kfu_online/wbTermin_list.wbLehrveranstaltung?pStpSpNr=1002516"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_urlopen(url, timeout):
        requested.append((url, timeout))
        return Response(HTML)

    monkeypatch.setattr("slidemage.course_schedule.urlopen", fake_urlopen)
    schedule = fetch_schedule(COURSE_URL)
    assert requested == [(SCHEDULE_URL, 15)]
    assert schedule.groups[0].name == "Standardgruppe"
