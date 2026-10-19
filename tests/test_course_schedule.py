# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Uni Graz course-groups/course-detail REST parsing and LaTeX rendering."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from slidemage.course_schedule import (
    CourseDetail,
    CourseGroup,
    CourseSchedule,
    CourseSession,
    Lecturer,
    course_data_url,
    course_groups_url,
    fetch_course_detail,
    fetch_schedule,
    parse_course_detail,
    parse_schedule,
    render_group_table,
    render_title_slide,
    translate_schedule,
    translate_to_english,
)


COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
GROUPS_URL = "https://online.uni-graz.at/kfu_online/ee/rest/slc.tm.cp/student/courseGroups/firstGroups/1002516"
COURSE_DATA_URL = "https://online.uni-graz.at/kfu_online/ee/rest/slc.tm.cp/student/courses/1002516"

GROUPS_JSON = json.dumps({
    "totalCount": 2,
    "courseGroupDtos": [
        {
            "name": "Standardgruppe",
            "appointmentDtos": [{
                "timestampFrom": {"value": "2026-10-05T09:00:00"},
                "timestampTo": {"value": "2026-10-05T10:00:00"},
                "resourceName": "SR 15.37 & A",
                "appointmentEventTypeDto": {"name": {"value": "Abhaltung"}},
                "comment": "Vorbesprechung",
            }],
        },
        {
            "name": "Gruppe Wirtschaftsinformatik",
            "appointmentDtos": [{
                "timestampFrom": {"value": "2026-10-06T08:30:00"},
                "timestampTo": {"value": "2026-10-06T10:00:00"},
                "resourceName": "HS 01",
                "appointmentEventTypeDto": {"name": {"value": "Prüfung"}},
                "comment": "R&D 50% #1 _x_ {y} ~ ^ \\end",
            }],
        },
    ],
}).encode()

COURSE_DATA_JSON = json.dumps({
    "resource": [{
        "content": {
            "cpCourseDetailDto": {
                "cpCourseDto": {
                    "courseNumber": {"courseNumber": "355.001"},
                    "courseTitle": {"value": "Bachelorkurs (Management Science)"},
                    "semesterDto": {"semesterDesignation": {"value": "Wintersemester 2026/27"}},
                    "lectureships": [
                        {
                            "identityLibDto": {"firstName": "Andreas", "lastName": "Darmann"},
                            "teachingFunction": {"name": "Vortragende*r"},
                        },
                        {
                            "identityLibDto": {"firstName": "Jürgen", "lastName": "Fleiß"},
                            "teachingFunction": {"name": "Vortragende*r"},
                        },
                    ],
                },
            },
        },
    }],
}).encode()


@pytest.mark.parametrize("total_count", [2, 3])
def test_parse_course_groups_shape_and_multiple_groups(total_count):
    payload = json.loads(GROUPS_JSON)
    payload["totalCount"] = total_count
    schedule = parse_schedule(json.dumps(payload))
    assert schedule.truncated is (total_count > 2)
    assert parse_schedule(json.dumps({"courseGroupDtos": []})) == CourseSchedule(())

    assert [group.name for group in schedule.groups] == [
        "Standardgruppe", "Gruppe Wirtschaftsinformatik",
    ]
    first = schedule.groups[0].sessions[0]
    assert first == CourseSession(
        date="05.10.2026", start="09:00", end="10:00",
        location="SR 15.37 & A", event="Abhaltung", remark="Vorbesprechung",
    )
    assert schedule.groups[1].sessions[0].event == "Prüfung"


def appointment(start, end, comment, *, shared=False, appointment_id=None):
    return {
        "id": appointment_id,
        "courseGroupDto": {"standardgroupFlag": "J" if shared else "N"},
        "timestampFrom": {"value": start},
        "timestampTo": {"value": end},
        "resourceName": "SR 15.37",
        "appointmentEventTypeDto": {"name": {"value": "Abhaltung"}},
        "comment": comment,
    }


def test_shared_sessions_become_their_own_standard_group():
    # Shape of the real response: the shared sessions are repeated in every
    # group, and "Operations Management" has none of its own.
    shared_a = appointment("2026-10-05T09:00:00", "2026-10-05T10:00:00", "Vorbesprechung", shared=True, appointment_id=1)
    shared_b = appointment("2026-10-14T10:15:00", "2026-10-14T12:00:00", "Shared 2", shared=True, appointment_id=2)
    own = appointment("2026-10-06T08:30:00", "2026-10-06T10:00:00", "WI only")
    schedule = parse_schedule(json.dumps({"totalCount": 2, "courseGroupDtos": [
        {"name": "Gruppe Operations Management", "appointmentDtos": [shared_a, shared_b]},
        {"name": "Gruppe Wirtschaftsinformatik", "appointmentDtos": [shared_a, own, shared_b]},
    ]}))

    assert [(group.name, [s.remark for s in group.sessions]) for group in schedule.groups] == [
        ("Standardgruppe", ["Vorbesprechung", "Shared 2"]),
        ("Gruppe Operations Management", []),
        ("Gruppe Wirtschaftsinformatik", ["WI only"]),
    ]
    assert not schedule.truncated


def test_listed_standard_group_is_not_repeated_as_an_empty_group():
    shared = appointment("2026-10-05T09:00:00", "2026-10-05T10:00:00", "Shared", shared=True, appointment_id=1)
    shared["courseGroupDto"]["id"] = 7
    schedule = parse_schedule(json.dumps({"courseGroupDtos": [
        {"id": 7, "name": "Standardgruppe", "appointmentDtos": [shared]},
    ]}))
    assert [(group.name, len(group.sessions)) for group in schedule.groups] == [("Standardgruppe", 1)]


def test_parser_tolerates_null_fields():
    schedule = parse_schedule(json.dumps({"courseGroupDtos": [
        {"name": "G", "appointmentDtos": None},
        {"name": "H", "appointmentDtos": [{
            "timestampFrom": {"value": "2026-10-05T09:00:00"},
            "timestampTo": {"value": "2026-10-05T10:00:00"},
            "courseGroupDto": None,
            "resourceName": None, "appointmentEventTypeDto": None, "comment": None,
        }]},
    ]}).encode())
    assert [group.name for group in schedule.groups] == ["G", "H"]
    assert schedule.groups[0].sessions == ()
    assert schedule.groups[1].sessions[0] == CourseSession("05.10.2026", "09:00", "10:00", "", "", "")


@pytest.mark.parametrize("kind", ["schedule", "appointment", "detail", "lecturer"])
def test_parsers_report_malformed_responses_as_value_error(kind):
    payload = {}
    if kind == "appointment":
        payload = {"courseGroupDtos": [{"name": "G", "appointmentDtos": [{}]}]}
    elif kind == "lecturer":
        payload = json.loads(COURSE_DATA_JSON)
        payload["resource"][0]["content"]["cpCourseDetailDto"]["cpCourseDto"]["lectureships"] = [{}]
    parser = parse_schedule if kind in ("schedule", "appointment") else parse_course_detail
    with pytest.raises(ValueError):
        parser(json.dumps(payload))


@pytest.mark.parametrize("language", ["de", "en"])
def test_course_detail_uses_requested_translation_and_german_fallback(language):
    payload = json.loads(COURSE_DATA_JSON)
    course = payload["resource"][0]["content"]["cpCourseDetailDto"]["cpCourseDto"]
    course["courseTitle"] = {"value": "Bachelor's Course\t \t", "translations": {"translation": [
        {"lang": "de", "value": " Bachelorkurs "}, {"lang": "en", "value": "Bachelor's Course\t \t"},
    ]}}
    if language == "en":
        course["courseTitle"]["value"] = "Bachelorkurs"
    if language == "de":
        course["semesterDto"]["semesterDesignation"] = {"value": "Winter semester 2026/27 "}
        course["lectureships"] = None
    else:
        course["semesterDto"]["semesterDesignation"] = {"value": "Wintersemester 2026/27", "translations": {
            "translation": [{"lang": "de", "value": "Wintersemester 2026/27"}, {"lang": "en"}],
        }}
    detail = parse_course_detail(json.dumps(payload), language)
    if language == "de":
        assert detail.title == "Bachelorkurs"
        assert detail.semester == "Winter semester 2026/27"
        assert detail.lecturers == ()
    else:
        assert detail.title == "Bachelor's Course"
        # No English semester name: falls back to German.
        assert detail.semester == "Wintersemester 2026/27"


def test_fetch_rejects_redirect_to_another_host(monkeypatch):
    class Response(BytesIO):
        def geturl(self):
            return "https://example.org/elsewhere"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr("slidemage.course_schedule.urlopen", lambda request, timeout: Response(GROUPS_JSON))
    with pytest.raises(RuntimeError, match="redirected"):
        fetch_schedule(COURSE_URL)


@pytest.mark.parametrize("bad_url", [
    "http://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1",
    "https://example.org/?pStpSpNr=1",
    "https://online.uni-graz.at/?pStpSpNr=abc",
    "https://online.uni-graz.at/?pStpSpNr=1&pStpSpNr=2",
])
def test_urls_validate_course_url(bad_url):
    with pytest.raises(ValueError):
        course_groups_url(bad_url)
    with pytest.raises(ValueError):
        course_data_url(bad_url)


def test_renderer_escapes_latex_special_characters():
    group = parse_schedule(GROUPS_JSON).groups[1]
    rendered = render_group_table(group)

    assert r"R\&D 50\% \#1 \_x\_ \{y\} \textasciitilde{} \textasciicircum{} \textbackslash{}end" in rendered
    assert r"\begin{gothamtable}[gap=4pt]{p{.13\linewidth}" in rendered
    assert r"\end{gothamtable}" in rendered
    assert r"\toprule" in rendered
    assert r"\textbf{Gruppe Wirtschaftsinformatik}\par" in rendered
    assert "06.10.2026 & 08:30--10:00 & HS 01" in rendered


def test_renderer_handles_empty_group():
    assert render_group_table(CourseGroup("None & One", ())) == r"\small \textbf{None \& One}\par Keine Termine verfügbar."


def test_english_rendering_and_translation():
    schedule = translate_schedule(parse_schedule(GROUPS_JSON))
    assert [group.name for group in schedule.groups] == [
        "Standard group", "Group Wirtschaftsinformatik"]
    first = schedule.groups[0].sessions[0]
    assert (first.event, first.remark, first.location) == (
        "Class", "Preliminary meeting", "SR 15.37 & A")
    rendered = render_group_table(schedule.groups[1], "en")
    assert r"\textbf{Date} & \textbf{Time} & \textbf{Location} & \textbf{Session}" in rendered
    assert r"HS 01 & Exam — R\&D" in rendered
    empty = render_group_table(CourseGroup("X", ()), "en")
    assert empty.endswith("No sessions available.")


def test_translation_is_whole_word_only():
    assert translate_to_english("Übungsgruppe 2") == "Übungsgruppe 2"
    assert translate_to_english("Gruppe 2 und Gruppe 3") == "Group 2 and Group 3"
    assert translate_to_english("Fragestunde") == "Q&A session"
    assert translate_to_english("Raum und Zeit tba", whole_only=True) == "Raum und Zeit tba"
    assert translate_to_english("Prüfung 1 entfällt", whole_only=True) == "Exam 1 cancelled"


@pytest.mark.parametrize("fetch, source, url, expected", [
    (fetch_schedule, GROUPS_JSON, GROUPS_URL, "Standardgruppe"),
    (fetch_course_detail, COURSE_DATA_JSON, COURSE_DATA_URL, "Bachelorkurs (Management Science)"),
])
def test_fetch_uses_the_course_endpoint_and_german_json(monkeypatch, fetch, source, url, expected):
    requested = []

    class Response(BytesIO):
        def geturl(self):
            return requested[-1][0]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_urlopen(request, timeout):
        requested.append((request.full_url, request.get_header("Accept"),
                          request.get_header("Accept-language"), timeout))
        return Response(source)

    monkeypatch.setattr("slidemage.course_schedule.urlopen", fake_urlopen)
    result = fetch(COURSE_URL)
    assert requested == [(url, "application/json", "de", 15)]
    name = result.groups[0].name if isinstance(result, CourseSchedule) else result.title
    assert name == expected


def test_parse_course_detail_shape():
    detail = parse_course_detail(COURSE_DATA_JSON)

    assert detail == CourseDetail(
        number="355.001", title="Bachelorkurs (Management Science)",
        semester="Wintersemester 2026/27",
        lecturers=(
            Lecturer("Andreas", "Darmann", "Vortragende*r"),
            Lecturer("Jürgen", "Fleiß", "Vortragende*r"),
        ),
    )


def test_render_title_slide_escapes_and_joins_selected_lecturers():
    detail = parse_course_detail(COURSE_DATA_JSON)
    rendered = render_title_slide(detail, detail.lecturers[:1])
    assert rendered == r"\titleframe{Bachelorkurs (Management Science)}{Andreas Darmann\\Wintersemester 2026/27}"


def test_parse_course_detail_reads_languages_of_instruction_main_first():
    payload = json.loads(COURSE_DATA_JSON)
    course = payload["resource"][0]["content"]["cpCourseDetailDto"]["cpCourseDto"]
    assert parse_course_detail(json.dumps(payload)).languages == ()
    course["courseLanguageDtos"] = [
        {"languageDto": {"key": "EN"}, "mainLanguage": False},
        {"languageDto": {"key": "DE"}, "mainLanguage": True},
        {"languageDto": None},
    ]
    assert parse_course_detail(json.dumps(payload)).languages == ("de", "en")
