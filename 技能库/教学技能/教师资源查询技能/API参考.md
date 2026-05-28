# CRM Teacher Resource API Reference

## Read-only Endpoint

`GET https://ems.vipthink.cn/gateway/route__jw/api/grades_v2/getTeacherResources`

This endpoint was found in the CRM frontend bundle and used by the class edit teacher selector. It checks teachers available for a proposed formal-class time cycle.

## Parameters

```json
{
  "date": "2026-05-28",
  "cycles": "[{\"week\":4,\"hour\":8,\"minute\":0}]",
  "cateId": 3282,
  "stepId": 3282
}
```

`week` uses ISO-like CRM numbering:

```text
1=Monday
2=Tuesday
3=Wednesday
4=Thursday
5=Friday
6=Saturday
7=Sunday
```

## English Stage IDs

```json
{
  "S1": 3282,
  "S2": 3283,
  "S3": 3284,
  "S4": 3285,
  "S5": 3286,
  "S6": 3287,
  "S7": 3288
}
```

## Teacher Fields

Known useful fields:

```text
id
teacherId
name
nick
code
duration
teacherGradeStr
teacherOverseaGradeStr
overseaStr
```

`nick` is the teacher art name used in scheduling summaries.
