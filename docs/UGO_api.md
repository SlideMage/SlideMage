# Uni Graz Online (UGO) API notes

`course_schedule.py` fetches two things from Uni Graz's course-management
system (`online.uni-graz.at`, internally "KFU Online"/CAMPUSonline) to build
the **Admin slides** feature (`qt_admin_slides_dialog.py`): a course's
session list and its title/number/semester/lecturers. Both are REST/JSON
endpoints, keyed by the same course identifier, `pStpSpNr`, which is also
the last path segment of a deck's linked course URL
(`https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516`
→ course ID `1002516`).

Neither endpoint needs a login. That's incidental, not documented or
guaranteed by Uni Graz -- both requests are just the same ones the public
course page makes when nobody is signed in, and either could start
requiring a session at any time.

## 1. Session list -- REST/JSON

```
GET https://online.uni-graz.at/kfu_online/ee/rest/slc.tm.cp/student/courseGroups/firstGroups/<id>
Accept: application/json
```

This is `course_schedule.course_groups_url()` / `fetch_schedule()`, found
the same way as the course-details endpoint below (a Network-tab capture).
The response is `{"courseGroupDtos": [...], "totalCount": <n>}`; each
group has a `name` and its own `appointmentDtos[]`, one per session:
`timestampFrom`/`timestampTo` (ISO datetimes, split into date/start/end by
`parse_schedule()`), `resourceName` (room), `appointmentEventTypeDto.name.value`
(event type, e.g. "Abhaltung"), and `comment` (remark).

An earlier version of this scraped `wbTvw_List.lehrveranstaltung`, the
old server-rendered appointments page, instead -- replaced once this REST
endpoint turned up, since it's the same data without HTML/xpath parsing.

**The REST endpoint groups sessions differently from the old HTML page,
and `parse_schedule()` converts them back.** The HTML page listed the
course's shared sessions under a separate "Standardgruppe" heading and
each group with only its own sessions. The REST endpoint instead lists
every real group with the shared sessions repeated inside it (they're
marked `courseGroupDto.standardgroupFlag: "J"` and `interGroupFlag: "J"`).
For course 1002516:

| Old HTML page | Raw REST response |
| --- | --- |
| Standardgruppe: 6 shared sessions | Gruppe Operations Management: the same 6 (it has none of its own) |
| Gruppe Wirtschaftsinformatik: its own 8 | Gruppe Wirtschaftsinformatik: 6 shared + 8 own = 14 |

`parse_schedule()` pulls every `standardgroupFlag: "J"` session out into
one "Standardgruppe" group, listed first, removing duplicates by
appointment `id` and sorting by start time. Each other group keeps only
its own sessions. A group left with none (Operations Management above)
is kept with no sessions; the Admin slides group picker shows it as
"Gruppe Operations Management (empty)", and its slide says "Keine Termine
verfügbar". The one exception is the standard group itself, if the
response lists it as a group: its `id` equals the shared sessions'
`courseGroupDto.id`, so it isn't repeated as an empty entry next to
"Standardgruppe". What REST returns for a course that has *only* a
standard group hasn't been seen yet; an empty group name falls back to
"Standardgruppe".

`appointmentStatusType` (e.g. `CONFIRMED`) isn't read, as the old page's
status column wasn't either; whether cancelled sessions appear in the
list is untested.

**Truncation:** the endpoint's name, "firstGroups", and its `totalCount`
suggest the group list can be cut short. `parse_schedule()` sets
`CourseSchedule.truncated` when `totalCount` exceeds the number of groups
returned, and the dialog then warns to check the course page; the missing
groups aren't fetched (the call that would page through them hasn't been
captured).

## 2. Course details -- REST/JSON

```
GET https://online.uni-graz.at/kfu_online/ee/rest/slc.tm.cp/student/courses/<id>
Accept: application/json
```

This is `course_schedule.course_data_url()` / `fetch_course_detail()`.

### Why this endpoint, and how it was found

The course *detail* page
(`wbLv.wbShowLVDetail?pStpSpNr=<id>`) -- the one with the "Vortragende*r"
field -- is a client-rendered Angular app, not server-rendered HTML like
the schedule page: `curl`ing it only returns the app shell (a `<script>`
loading screen), so there is nothing in the raw response to parse. Static
analysis of the app's JS bundles didn't reveal the endpoint either: the
detail page uses UGO's generic "legacy mask" renderer, so the client code
has no hardcoded field names or URLs to grep for -- everything is
data-driven at runtime.

The endpoint above was found the only reliable way available: opening the
real page in a browser and reading the Network tab. Loading
`wbLv.wbShowLVDetail?pStpSpNr=1002516` fires (among session/framework
calls) five course-specific `GET` requests:

| Endpoint | Returns |
| --- | --- |
| `/ee/rest/slc.tm.cp/student/courses/<id>` | Course details, including lecturers (used) |
| `/ee/rest/slc.tm.cp/student/courseGroups/firstGroups/<id>` | Course groups and sessions (used, see §1) |
| `/ee/rest/slc.tm.cp/student/courses/<id>/curriculumPositionGroupings` | Curriculum groupings |
| `/ee/rest/slc.cm.curriculumposition/positions/<id>/course/allCurriculumPositions` | All curriculum positions |
| `/ee/rest/slc.xm.exd/exExamOffer?$filter=courseId-eq=<id>&...` | Exam dates |

Only the first two are used; the other three are noted here in case a
future admin slide needs curriculum or exam data -- same host, same auth
behavior (tested unauthenticated for `courses/<id>` and
`courseGroups/firstGroups/<id>` only; the other three weren't checked).

**Without an `Accept: application/json` header, the same URL returns XML**
(`<codata:resources>...`) instead -- both are the same underlying data,
just negotiated content types.

### Response shape

```json
{
  "link": [...],
  "resource": [
    {
      "link": [...],
      "content": {
        "type": "model-slc.tm.cp.student.CpCourseDetailDto",
        "cpCourseDetailDto": {
          "cpCourseDto": { ... }
        }
      }
    }
  ]
}
```

`parse_course_detail()` reads `resource[0].content.cpCourseDetailDto.cpCourseDto`.
A field that repeats across languages (course title, semester name, org
name, event type, ...) is a "langdata" object: `{"value": "<default>",
"translations": {"translation": [{"lang": "de", "value": "..."}, {"lang":
"en", ...}, ...]}}`.

**`.value` depends on the request's `Accept-Language` header** -- with
`Accept-Language: en` the title comes back as `"Bachelor's Course
(Management Science)\t \t"` (stray whitespace included). So
`course_schedule._localized()` never relies on `.value` when a
translation exists: it reads the translation for the deck's language,
falls back to `de`, then to `.value`, and strips whitespace.
`_get_json()` also sends `Accept-Language: de`. `$ctx=lang=EN` in the
query string, which the app uses elsewhere, has no effect on this
endpoint.

The Admin slides follow the deck's `\decklanguage`. An English deck's
title slide uses UGO's own English title and semester (German where UGO
has no English one). Its sessions table gets English headings, and its
group names, event types and fully known remarks are translated from a
fixed word list (`course_schedule.translate_schedule()`, v4.1.0). The
slides are named `<id>-EN-...` instead of `<id>-DE-...`.

The course's languages of instruction (`CourseDetail.languages`, main one
first) are only used for a check: if the deck's language isn't among
them, the dialog shows a warning, but inserting still works. The typical
cause is a deck with no `\decklanguage` line, which counts as English,
for a course taught in German. A mismatch isn't an error, because it's
often deliberate (English slides for a German-taught course) and a course
can list several languages. Only `"DE"` has been seen from this endpoint
so far.

Both parsers raise `ValueError` for any response that doesn't have the
expected shape, including a single malformed session or lecturer, and
treat `null` lists and text fields as empty. Both fetches reject a
redirect away from `online.uni-graz.at`.

Fields available on `cpCourseDto` (used by this module marked ✓):

| Field | Meaning |
| --- | --- |
| `id` | Numeric course ID (same as `pStpSpNr`) |
| `courseNumber.courseNumber` ✓ | LV number, e.g. `"355.001"` |
| `courseTitle` ✓ | Title (langdata) |
| `courseTypeDto` | Type code (`"KS"`), name ("Kurs"/"Course") |
| `courseLanguageDtos[]` ✓ | Language(s) of instruction (`languageDto.key`, e.g. `"DE"`), `mainLanguage` flag |
| `ectsCredits` | ECTS points |
| `courseNormConfigs[]` | Workload unit, e.g. `"1"` Semesterstunde (SSt) |
| `semesterDto.semesterDesignation` ✓ | Full semester name, e.g. "Wintersemester 2026/27" |
| `semesterDto.shortName` | Short form, e.g. "2026 W" |
| `semesterDto.semesterType` | `"W"`/`"S"` |
| `semesterDto.startOfAcademicSemester` / `endOfAcademicSemester` | Date range |
| `lectureships[]` ✓ | One per instructor -- see below |
| `displayMoreLectureships` | `true` if `lectureships[]` was truncated -- see caveat below |
| `organisationResponsibleDto` | Responsible institute: name (langdata), link to its own org page |
| `registrationAvailable`, `registrationInfo`, `registrationInfoStatus`, `registeredConfigType` | Registration status |
| `identityCodeId`, `eLearningActive`, `lvCreditsEnabled` | Misc flags, not slide material |

Each `lectureships[]` entry:

| Field | Meaning |
| --- | --- |
| `identityLibDto.firstName` / `lastName` ✓ | Instructor name |
| `identityLibDto.gender`, `genderNrForTitle` | Used by UGO for salutation forms, not read here |
| `identityLibDto.businessCardLink.href` | Public profile page for that person |
| `teachingFunction.name` ✓ | Role, e.g. "Vortragende*r" (lecturer), "Mitwirkende*r" (contributor) |

### Known caveat: `displayMoreLectureships`

This flag means the course has more instructors than `lectureships[]`
lists. It hasn't come up on any course tested so far (2 lecturers, flag
`false`), so `parse_course_detail()` doesn't check it or fetch the rest.
If a course with `displayMoreLectureships: true` turns up, the missing
names are presumably behind a separate (unknown, not yet captured) paginated
call -- worth another Network-tab capture rather than guessing.

## Using a different course

Both endpoints take the same `pStpSpNr`/course ID -- swap it in either URL
to inspect another course manually, e.g.:

```bash
curl -H "Accept: application/json" \
  "https://online.uni-graz.at/kfu_online/ee/rest/slc.tm.cp/student/courses/<id>"
curl -H "Accept: application/json" \
  "https://online.uni-graz.at/kfu_online/ee/rest/slc.tm.cp/student/courseGroups/firstGroups/<id>"
```
