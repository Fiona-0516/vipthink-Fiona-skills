---
name: crm-redline-dingtalk
description: Automate CRM teacher attendance redline workflows for DingTalk: log in with environment-provided CRM credentials, fetch teacher attendance exceptions, match teacher teams from the CRM teacher roster, filter to a configured business scope, prepare DingTalk registration-table rows, and send morning or reminder messages to DingTalk robots. Use when the user asks to push CRM late/early-leave/serious-early-leave data, maintain a redline registration table, match teacher teams or management ownership, or run the daily 10:00/21:00 redline notification flow.
---

# CRM Redline DingTalk

Use this skill to run the redline attendance workflow without hardcoding secrets.

## Safety Rules

- Never commit or print real CRM passwords, tokens, DingTalk robot webhooks, access tokens, table links with private IDs, teacher personal data exports, or generated case data.
- Read secrets from environment variables or a local ignored `.env` file only.
- Treat DingTalk robot webhooks as write-only credentials.
- Confirm before sending production DingTalk messages unless the user explicitly provides the production webhook and asks to push.
- Keep raw exports and dated case files out of Git.

## Default Business Logic

- Attendance source: CRM attendance API.
- Exception tags: `迟到`, `早退`, `严重早退`.
- Filter by `status` labels, not by `lateTime > 0` or `leaveEarlyTime > 0`.
- Team source: CRM teacher roster detail API `/api/teacher/getTeacher`.
- Team filter: configure `TEAM_SCOPE`, for example `海外直播业务线-海外益智教学中心`.
- Management owner: final segment of the full team path, split on `-`.
- Registration table columns:
  `日期, 老师ID, 老师姓名, 老师昵称, 团队, 管理归属, 异常标签, 上课时间, 房间号, 迟到分钟, 早退分钟, 管理者填写原因, 处理结果, 是否已核实, 填写时间`.

## Workflow

1. Load configuration from environment variables.
2. Log in to CRM with `CRM_ACCOUNT` and `CRM_PASSWORD`.
3. Fetch attendance rows for the target date.
4. Keep rows whose status labels intersect with `REDLINE_TAGS`.
5. Fetch teacher detail for unique teacher IDs and fill full team path.
6. Filter rows where team contains `TEAM_SCOPE`.
7. Set `管理归属` to the last team path segment.
8. Generate registration-table TSV/CSV.
9. Send DingTalk summary grouped by `管理归属`.
10. For 21:00 reminders, read the registration table/export and list rows where `管理者填写原因` is empty.

## Scripts

Use `scripts/crm_redline.py` for reusable CLI execution.

Common examples:

```bash
export CRM_ACCOUNT='...'
export CRM_PASSWORD='...'
export DINGTALK_WEBHOOK='<dingtalk robot webhook>'
export TEAM_SCOPE='海外直播业务线-海外益智教学中心'

python scripts/crm_redline.py run --date 2026-05-27 --out-dir ./out
python scripts/crm_redline.py send --csv ./out/redline_filtered.csv
python scripts/crm_redline.py remind --registration-csv ./out/redline_filtered.csv
```

Optional environment variables:

- `REDLINE_TAGS`: comma-separated labels. Default: `迟到,早退,严重早退`.
- `DINGTALK_TABLE_URL`: registration table URL to include in messages.
- `CRM_AUTH_URL`: default `https://auth-new.vipthink.cn/iam-sso/v2/auth/admin/token`.
- `CRM_ATTENDANCE_URL`: default `https://aic-gw.vipthink.cn/api/train/t1/ol-teacher-attendance/teacherCheckWork`.
- `CRM_TEACHER_DETAIL_URL`: default `https://tqs.vipthink.cn/api/teacher/getTeacher`.

## Validation

Before production use:

- Run with a historical date and inspect the generated CSV.
- Confirm count by tag and count by management owner.
- Confirm DingTalk payload text does not expose passwords or tokens.
- Send to a test robot first, then production.
