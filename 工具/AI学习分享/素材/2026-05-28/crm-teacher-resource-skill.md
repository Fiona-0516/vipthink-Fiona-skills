---
name: crm-teacher-resources
description: Use when querying VIPThink CRM formal-class teacher resource availability, matching no-class slots to available teachers, or producing teacher nickname/art-name availability summaries from the CRM read-only getTeacherResources endpoint.
---

# CRM Teacher Resources

Use this skill to query whether formal-class time slots have teachers who can take a new class pairing.

Safety boundary:
- Only call read-only teacher resource endpoints.
- Do not click or call submit/save/confirm/schedule/enroll/group-intention APIs.
- If a workflow needs to submit intent or create/schedule a class, stop at preview and ask for explicit approval.

## Endpoint

Default endpoint:

```text
GET https://ems.vipthink.cn/gateway/route__jw/api/grades_v2/getTeacherResources
```

Headers:

```text
authorization: Bearer <CRM_TOKEN>
content-type: application/json;charset=UTF-8
```

Query parameters:

- `date`: class date, `YYYY-MM-DD`
- `cycles`: JSON string, e.g. `[{"week":4,"hour":8,"minute":0}]`
- `cateId`: course stage id
- `stepId`: usually same as `cateId` for the formal-class stage
- `classEndTime`: optional

Response field notes:
- `code=200` usually means resource data exists.
- `code=201` usually means no available teacher.
- Teacher display name is usually `name`.
- Teacher art name is `nick`.
- Teacher id is usually `id` or `teacherId`.

## Course Stage IDs

English formal class:

```text
S1=3282
S2=3283
S3=3284
S4=3285
S5=3286
S6=3287
S7=3288
```

For other languages/stages, prefer the project helper `src/crm_query.py::resolve_class_query()`.

## Script

Use `scripts/query_teacher_resources.ps1` for deterministic queries.

Examples:

```powershell
powershell -ExecutionPolicy Bypass -File skills\crm-teacher-resources\scripts\query_teacher_resources.ps1 -Date 2026-05-28 -Week 4 -Hour 8 -Minute 0
```

```powershell
powershell -ExecutionPolicy Bypass -File skills\crm-teacher-resources\scripts\query_teacher_resources.ps1 -WeekStart 2026-05-25 -Hour 8 -Minute 0 -GroupByDay
```

The script reads token from `capture/crm_token.json` by default and prints only teacher names/art names, never the token.

## Matching Workflow

When handling a user scheduling need:

1. Query existing classes first by language/stage/time; return classes with seats.
2. If no suitable class exists, query teacher resources for the requested slots.
3. Present available teacher art names grouped by day/time/stage.
4. Do not submit grouping intent until the CRM intent endpoint and approval are confirmed.
