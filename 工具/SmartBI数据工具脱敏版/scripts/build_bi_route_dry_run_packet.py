#!/usr/bin/env python3
"""Build a reviewable BI route dry-run packet from a business question.

Read-only guarantees:
- does not log into SmartBI
- does not export Excel
- does not download report data
- does not write to ad-system projects

The packet contains candidate reports, a recommended dry-run task, filter risks,
human confirmation questions, and a SmartBI CLI config draft that can be checked
with validate_smartbi_config.py before any export is considered.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from validate_smartbi_config import validate_config


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "outputs" / "bi_catalog_registry" / "bi_report_route_index_current.json"
DEFAULT_OUT_DIR = ROOT / "outputs" / "bi_catalog_registry" / "dry_run_packets"


def slugify(value: str) -> str:
    ascii_slug = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    if ascii_slug:
        return ascii_slug[:72]
    return "bi_route_packet"


def query_candidates(query: str, metrics: list[str], limit: int, registry: Path) -> list[dict[str, Any]]:
    command = [
        "python3",
        "scripts/query_bi_profiles.py",
        "--registry",
        str(registry),
        "--query",
        query,
        "--limit",
        str(limit),
        "--json",
    ]
    for metric in metrics:
        command.extend(["--metric", metric])
    payload = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
    return payload.get("results") or []


def can_dry_run(candidate: dict[str, Any]) -> bool:
    plan = candidate.get("dry_run_plan") or {}
    task = plan.get("config_task") or {}
    report = task.get("report") or {}
    return bool(
        candidate.get("report_id")
        and candidate.get("match_confidence", 0) >= 0.8
        and report.get("type") == "SPREADSHEET_REPORT"
    )


def needs_human_confirmation(candidate: dict[str, Any]) -> bool:
    filter_summary = candidate.get("filter_summary") or {}
    risk_flags = set(candidate.get("risk_flags") or [])
    return bool(
        filter_summary.get("weak_or_manual", 0)
        or "has_filter_safety_limits" in risk_flags
        or "manual_or_default_only_filter" in risk_flags
        or "inspect_workbook_shape_before_analysis" in risk_flags
    )


def confirmation_questions(candidate: dict[str, Any] | None) -> list[str]:
    if not candidate:
        return ["没有可 dry-run 的候选表，需要人工指定 SmartBI 报表或修复 route index。"]
    questions = [
        "确认业务时间窗口：开始日期、结束日期或快照日期是什么？",
        "确认区域/渠道/平台口径：是否需要限定台湾、港澳/非港澳、FB 或素材类型？",
    ]
    filter_summary = candidate.get("filter_summary") or {}
    unsafe = filter_summary.get("unsafe_examples") or []
    for item in unsafe[:4]:
        label = item.get("label") or "未命名筛选器"
        boundary = item.get("learning_boundary") or "unknown"
        questions.append(f"筛选器「{label}」是 {boundary}，是否保持默认值「{item.get('default_value', '')}」？")
    if "inspect_workbook_shape_before_analysis" in set(candidate.get("risk_flags") or []):
        questions.append("该候选可能是格式化 workbook/pivot，是否先做 workbook shape inspection 再分析？")
    return questions


def summarize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_name": candidate.get("name"),
        "report_id": candidate.get("report_id"),
        "smartbi_path": candidate.get("smartbi_path"),
        "report_type": candidate.get("type"),
        "registry_type": candidate.get("registry_type"),
        "match_confidence": candidate.get("match_confidence"),
        "score": candidate.get("score"),
        "matched": candidate.get("matched"),
        "sample_columns": candidate.get("sample_columns"),
        "metric_hits": candidate.get("metric_hits"),
        "filter_summary": candidate.get("filter_summary"),
        "risk_flags": candidate.get("risk_flags"),
        "can_enter_dry_run": can_dry_run(candidate),
        "needs_human_confirmation": needs_human_confirmation(candidate),
        "dry_run_plan": candidate.get("dry_run_plan"),
    }


def select_recommended(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if can_dry_run(candidate):
            return candidate
    return candidates[0] if candidates else None


def build_packet(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any] | None]:
    candidates = query_candidates(args.query, args.metric or [], args.limit, args.registry)
    recommended = select_recommended(candidates)
    config = None
    config_validation = {"status": "not_available", "errors": ["no dry-run candidate"]}
    if recommended and can_dry_run(recommended):
        plan = recommended.get("dry_run_plan") or {}
        task_name = plan.get("task")
        config_task = plan.get("config_task")
        if task_name and config_task:
            config = {"version": 1, "tasks": {task_name: config_task}}
            errors = validate_config(config)
            config_validation = {"status": "ok" if not errors else "error", "errors": errors}

    packet = {
        "schema_version": "bi-route-dry-run-packet-p2",
        "query": args.query,
        "metrics": args.metric or [],
        "route_index": str(args.registry),
        "boundary": {
            "mode": "read_only_packet",
            "no_smartbi_export": True,
            "no_excel_download": True,
            "no_ad_platform_login": True,
            "requires_human_confirmation_before_export": True,
        },
        "recommended_report": summarize_candidate(recommended) if recommended else None,
        "top_candidates": [summarize_candidate(item) for item in candidates[: args.limit]],
        "human_confirmation_questions": confirmation_questions(recommended),
        "dry_run_config": config,
        "dry_run_config_validation": config_validation,
        "decision": decision(config_validation, recommended),
    }
    return packet, config


def decision(config_validation: dict[str, Any], recommended: dict[str, Any] | None) -> dict[str, Any]:
    if not recommended:
        return {"status": "blocked", "reason": "no candidate report returned"}
    if not can_dry_run(recommended):
        return {
            "status": "blocked",
            "reason": "recommended report cannot enter SmartBI CLI dry-run; likely SIMPLE_REPORT or missing config draft",
        }
    if config_validation.get("status") != "ok":
        return {"status": "blocked", "reason": "dry-run config draft failed offline validation"}
    if needs_human_confirmation(recommended):
        return {
            "status": "dry_run_ready_after_human_confirmation",
            "reason": "route and config are valid, but filters/workbook shape need human confirmation",
        }
    return {"status": "dry_run_ready", "reason": "route and config are valid for SmartBI CLI dry-run only"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a reviewable BI route dry-run packet.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--metric", action="append", default=[])
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    out = args.out
    if out is None:
        out = DEFAULT_OUT_DIR / f"{slugify(args.query)}.json"
    if not out.is_absolute():
        out = ROOT / out
    packet, config = build_packet(args)
    out.parent.mkdir(parents=True, exist_ok=True)
    packet["packet_path"] = str(out)
    if config:
        config_path = out.with_suffix(".smartbi_config.json")
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        packet["dry_run_config_path"] = str(config_path)
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "status": "ok",
        "packet": str(out),
        "dry_run_config": packet.get("dry_run_config_path"),
        "decision": packet["decision"],
        "config_validation": packet["dry_run_config_validation"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
