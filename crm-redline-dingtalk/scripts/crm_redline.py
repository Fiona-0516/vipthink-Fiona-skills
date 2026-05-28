#!/usr/bin/env python3
"""Sanitized CRM redline DingTalk workflow.

Secrets must come from environment variables. This script intentionally does not
store tokens, passwords, webhooks, or case data in the repository.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_AUTH_URL = "https://auth-new.vipthink.cn/iam-sso/v2/auth/admin/token"
DEFAULT_ATTENDANCE_URL = (
    "https://aic-gw.vipthink.cn/api/train/t1/ol-teacher-attendance/teacherCheckWork"
)
DEFAULT_TEACHER_DETAIL_URL = "https://tqs.vipthink.cn/api/teacher/getTeacher"
DEFAULT_TAGS = ["迟到", "早退", "严重早退"]
OUTPUT_COLUMNS = [
    "日期",
    "老师ID",
    "老师姓名",
    "老师昵称",
    "团队",
    "管理归属",
    "异常标签",
    "上课时间",
    "房间号",
    "迟到分钟",
    "早退分钟",
    "管理者填写原因",
    "处理结果",
    "是否已核实",
    "填写时间",
]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def require_env(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def login() -> str:
    data = post_json(
        env("CRM_AUTH_URL", DEFAULT_AUTH_URL),
        {"account": require_env("CRM_ACCOUNT"), "password": require_env("CRM_PASSWORD")},
    )
    token = (data.get("data") or {}).get("token")
    if not token:
        raise RuntimeError(f"CRM login failed: {data.get('info') or data.get('msg') or data}")
    return token


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Origin": "https://crm.vipthink.cn"}


def extract_list(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("list", "rows", "records", "data", "datas"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                nested = extract_list(value)
                if nested:
                    return nested
    return []


def status_labels(row: Dict[str, Any]) -> List[str]:
    value = row.get("status") or row.get("statusList") or row.get("statusName") or ""
    if isinstance(value, list):
        labels = []
        for item in value:
            if isinstance(item, dict):
                labels.append(str(item.get("label") or item.get("name") or item.get("value") or ""))
            else:
                labels.append(str(item))
        return [x for x in labels if x]
    return [x for x in str(value).replace("，", ",").split(",") if x]


def fetch_attendance(token: str, day: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 1
    limit = int(env("CRM_PAGE_LIMIT", "200"))
    url = env("CRM_ATTENDANCE_URL", DEFAULT_ATTENDANCE_URL)
    while True:
        payload = {
            "courseStartTime": f"{day} 00:00:00",
            "courseEndTime": f"{day} 23:59:59",
            "teacherIds": [],
            "teacherGroupId": "",
            "status": None,
            "courseType": None,
            "limit": limit,
            "page": page,
        }
        data = post_json(url, payload, auth_headers(token))
        batch = extract_list(data.get("data", data))
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        page += 1
    return rows


def first_value(row: Dict[str, Any], names: Iterable[str], default: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return default


def normalize_attendance(day: str, row: Dict[str, Any], tags: List[str]) -> Dict[str, str] | None:
    labels = status_labels(row)
    matched = [tag for tag in tags if tag in labels]
    if not matched:
        return None
    return {
        "日期": day,
        "房间号": first_value(row, ["roomId", "roomNo", "roomNum", "classroomId", "liveId"]),
        "上课时间": first_value(row, ["courseStartTime", "startTime", "liveStartTime"]),
        "老师ID": first_value(row, ["teacherId", "teacherID", "id"]),
        "老师姓名": first_value(row, ["teacherName", "realname", "realName"]),
        "老师昵称": first_value(row, ["teacherNickName", "teacherNickname", "nickname"]),
        "团队": "",
        "管理归属": "",
        "异常标签": "、".join(matched),
        "迟到分钟": first_value(row, ["lateTime", "lateMinutes"], "0"),
        "早退分钟": first_value(row, ["leaveEarlyTime", "earlyLeaveMinutes"], "0"),
        "管理者填写原因": "",
        "处理结果": "",
        "是否已核实": "",
        "填写时间": "",
    }


def teacher_detail(token: str, teacher_id: str) -> Dict[str, str]:
    if not teacher_id:
        return {}
    data = post_json(
        env("CRM_TEACHER_DETAIL_URL", DEFAULT_TEACHER_DETAIL_URL),
        {"id": int(teacher_id)},
        auth_headers(token),
    )
    detail = data.get("data") or {}
    oa = detail.get("oaInfo") or {}
    edu = detail.get("eduTeach") or {}
    return {
        "老师ID": str(oa.get("id") or teacher_id),
        "老师姓名": str(oa.get("realname") or ""),
        "老师昵称": str(oa.get("nickname") or oa.get("adminUserNickname") or ""),
        "团队": str(edu.get("groupTxt") or ""),
    }


def enrich_and_filter(token: str, rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    scope = env("TEAM_SCOPE")
    teacher_ids = sorted({row["老师ID"] for row in rows if row.get("老师ID")})
    details: Dict[str, Dict[str, str]] = {}
    for teacher_id in teacher_ids:
        details[teacher_id] = teacher_detail(token, teacher_id)
        time.sleep(float(env("CRM_DETAIL_SLEEP_SECONDS", "0.05")))
    output = []
    for row in rows:
        detail = details.get(row.get("老师ID", ""), {})
        if detail.get("老师姓名"):
            row["老师姓名"] = detail["老师姓名"]
        if detail.get("老师昵称"):
            row["老师昵称"] = detail["老师昵称"]
        row["团队"] = detail.get("团队", row.get("团队", ""))
        if scope and scope not in row["团队"]:
            continue
        parts = [part.strip() for part in row["团队"].split("-") if part.strip()]
        row["管理归属"] = parts[-1] if parts else ""
        output.append(row)
    return output


def write_outputs(rows: List[Dict[str, str]], out_dir: Path) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "redline_filtered.csv"
    tsv_path = out_dir / "registration_rows.tsv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with tsv_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write("\t".join(row.get(col, "").replace("\t", " ").replace("\n", " ") for col in OUTPUT_COLUMNS) + "\n")
    return {"csv": csv_path, "tsv": tsv_path}


def load_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def send_message(text: str) -> None:
    webhook = require_env("DINGTALK_WEBHOOK")
    data = post_json(webhook, {"msgtype": "text", "text": {"content": text}})
    if data.get("errcode") not in (0, None):
        raise RuntimeError(f"DingTalk send failed: {data}")


def summary_text(rows: List[Dict[str, str]]) -> str:
    title = env("MESSAGE_TITLE", "红线异常提醒")
    table_url = env("DINGTALK_TABLE_URL")
    by_tag = Counter(row.get("异常标签", "") for row in rows)
    by_owner: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_owner[row.get("管理归属") or "未匹配管理归属"].append(row)
    lines = [f"【{title}】"]
    if env("TEAM_SCOPE"):
        lines.append(f"范围：{env('TEAM_SCOPE')}")
    lines.append("")
    lines.append(f"共 {len(rows)} 条：" + "，".join(f"{k} {v} 条" for k, v in by_tag.items() if k))
    lines.append("")
    for owner, items in sorted(by_owner.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"{owner}：{len(items)} 条")
        for row in items:
            start = row.get("上课时间", "")
            hhmm = start[11:16] if len(start) >= 16 else start
            lines.append(
                f"- {row.get('老师姓名','')}（{row.get('老师昵称','')}）："
                f"{row.get('异常标签','')}，{hhmm}，房间{row.get('房间号','')}"
            )
        lines.append("")
    lines.append(env("FILL_REMINDER_TEXT", "请相关管理者在 21:00 前填写原因和处理结果。"))
    if table_url:
        lines.append(f"登记表：{table_url}")
    return "\n".join(lines)


def reminder_text(rows: List[Dict[str, str]]) -> str:
    pending = [row for row in rows if not row.get("管理者填写原因", "").strip()]
    table_url = env("DINGTALK_TABLE_URL")
    lines = [f"【红线原因未填写提醒】", f"仍有 {len(pending)} 条未填写原因。", ""]
    by_owner: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in pending:
        by_owner[row.get("管理归属") or "未匹配管理归属"].append(row)
    for owner, items in sorted(by_owner.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"{owner}：{len(items)} 条")
        for row in items:
            lines.append(f"- {row.get('老师姓名','')}：{row.get('异常标签','')}，房间{row.get('房间号','')}")
    if table_url:
        lines.append("")
        lines.append(f"登记表：{table_url}")
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace) -> None:
    token = login()
    tags = [x.strip() for x in env("REDLINE_TAGS", ",".join(DEFAULT_TAGS)).split(",") if x.strip()]
    raw_rows = fetch_attendance(token, args.date)
    redline_rows = [x for row in raw_rows if (x := normalize_attendance(args.date, row, tags))]
    filtered = enrich_and_filter(token, redline_rows)
    paths = write_outputs(filtered, Path(args.out_dir))
    print(json.dumps({"raw": len(raw_rows), "redline": len(redline_rows), "filtered": len(filtered), "outputs": {k: str(v) for k, v in paths.items()}}, ensure_ascii=False, indent=2))


def cmd_send(args: argparse.Namespace) -> None:
    rows = load_rows(Path(args.csv))
    text = summary_text(rows)
    if args.dry_run:
        print(text)
    else:
        send_message(text)
        print("sent")


def cmd_remind(args: argparse.Namespace) -> None:
    rows = load_rows(Path(args.registration_csv))
    text = reminder_text(rows)
    if args.dry_run:
        print(text)
    else:
        send_message(text)
        print("sent")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--date", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    run_p.add_argument("--out-dir", default="./out")
    run_p.set_defaults(func=cmd_run)
    send_p = sub.add_parser("send")
    send_p.add_argument("--csv", required=True)
    send_p.add_argument("--dry-run", action="store_true")
    send_p.set_defaults(func=cmd_send)
    remind_p = sub.add_parser("remind")
    remind_p.add_argument("--registration-csv", required=True)
    remind_p.add_argument("--dry-run", action="store_true")
    remind_p.set_defaults(func=cmd_remind)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
