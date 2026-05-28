# API And Field Notes

This reference is intentionally sanitized. It contains endpoint shapes and field rules only.

## Login

`POST CRM_AUTH_URL`

Body:

```json
{
  "account": "from CRM_ACCOUNT",
  "password": "from CRM_PASSWORD"
}
```

Token path: `data.token`.

## Attendance

`POST CRM_ATTENDANCE_URL`

Headers:

```text
Authorization: Bearer <token>
Content-Type: application/json
```

Body:

```json
{
  "courseStartTime": "YYYY-MM-DD 00:00:00",
  "courseEndTime": "YYYY-MM-DD 23:59:59",
  "teacherIds": [],
  "teacherGroupId": "",
  "status": null,
  "courseType": null,
  "limit": 200,
  "page": 1
}
```

Paginate until the response returns fewer than `limit` rows or no rows.

Important: use the `status` label array/string to decide redline tags. Do not infer the final count from minute fields alone.

## Teacher Detail

`POST CRM_TEACHER_DETAIL_URL`

Body:

```json
{"id": 12345}
```

Useful paths:

- `data.oaInfo.id`
- `data.oaInfo.realname`
- `data.oaInfo.nickname`
- `data.eduTeach.groupTxt`

`groupTxt` is the full team path. For management ownership, split by `-` and take the last non-empty segment.

## DingTalk Robot

`POST DINGTALK_WEBHOOK`

Body:

```json
{
  "msgtype": "text",
  "text": {"content": "message"}
}
```

Robot webhooks can send messages only. They cannot read DingTalk docs or verify whether a registration table cell is filled.
