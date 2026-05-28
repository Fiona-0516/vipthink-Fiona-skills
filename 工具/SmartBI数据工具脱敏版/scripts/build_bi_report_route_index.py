#!/usr/bin/env python3
"""Build an enriched read-only BI route index from local SmartBI profile files."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from query_bi_profiles import (
    DEFAULT_FILTERS,
    DEFAULT_MAP,
    DEFAULT_PROFILES,
    SAFE_BOUNDARY,
    WEAK_BOUNDARIES,
    compact_path,
    filter_summary,
    load_object,
    report_columns,
    report_filters,
    source_role,
)


DEFAULT_OUT = Path("outputs/bi_catalog_registry/bi_report_route_index_current.json")
DEFAULT_REPORT = Path("outputs/bi_catalog_registry/bi_report_route_join_report_current.md")
DEFAULT_REPORT_ID_REGISTRY = Path("outputs/bi_catalog_registry/smartbi_report_id_registry_current.json")
CORE_REPORT_NAMES = [
    "投放FB链路指标--素材维度",
    "海外投放FB渠道日监控",
    "投放FB链路类型日监控",
    "FB港澳-非港澳测试报表",
    "投放全链路目标达成数据-跨月",
]


def smartbi_profile_path(identity: dict[str, Any]) -> str:
    parts = [str(part) for part in identity.get("path") or [] if part]
    if parts and parts[0] == "益智业务线":
        return "分析报表/平台业务线/" + "/".join(parts)
    return "分析报表/" + "/".join(parts)


def build_filter_index(filter_inventory: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in filter_inventory.get("filters") or []:
        if not isinstance(item, dict):
            continue
        report = item.get("report")
        if report:
            index[str(report)].append(item)
    return dict(index)


def build_business_index(kb_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for module in kb_map.get("modules") or []:
        if not isinstance(module, dict):
            continue
        module_id = str(module.get("id") or "")
        module_title = str(module.get("title") or "")
        for report in module.get("reports") or []:
            if not isinstance(report, dict) or not report.get("name"):
                continue
            current = index.setdefault(
                str(report["name"]),
                {
                    "business_modules": [],
                    "metric_hits": set(),
                    "field_groups": set(),
                    "query_metrics": set(),
                    "query_dimensions": set(),
                },
            )
            current["business_modules"].append({"id": module_id, "title": module_title})
            current["metric_hits"].update(str(item) for item in report.get("metric_hits") or [] if item)
            current["field_groups"].update(str(item) for item in (report.get("field_groups") or {}).keys() if item)
            query_fields = report.get("query_fields") or {}
            current["query_metrics"].update(str(item) for item in query_fields.get("metrics") or [] if item)
            current["query_dimensions"].update(str(item) for item in query_fields.get("dimensions") or [] if item)
    for value in index.values():
        for key in ("metric_hits", "field_groups", "query_metrics", "query_dimensions"):
            value[key] = sorted(value[key])
    return index


def build_registry_indexes(registry: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_path: dict[str, dict[str, Any]] = {}
    by_alias: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in registry.get("reports") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        alias = str(item.get("alias") or item.get("name") or "")
        if path:
            by_path[path] = item
        if alias:
            by_alias[alias].append(item)
    return by_path, dict(by_alias)


def match_registry(
    report_name: str,
    profile_path: str,
    registry_by_path: dict[str, dict[str, Any]],
    registry_by_alias: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str, float, list[dict[str, Any]]]:
    direct = registry_by_path.get(profile_path)
    if direct:
        return direct, "path", 1.0, []
    candidates = registry_by_alias.get(report_name, [])
    if len(candidates) == 1:
        return candidates[0], "alias", 0.82, []
    if len(candidates) > 1:
        return None, "ambiguous_alias", 0.0, candidates
    return None, "unmatched", 0.0, []


def risk_flags(
    profile_report: dict[str, Any],
    registry_item: dict[str, Any] | None,
    filters: list[dict[str, Any]],
    match_type: str,
) -> list[str]:
    flags: list[str] = []
    identity = profile_report.get("identity") or {}
    export = profile_report.get("export") or {}
    report_type = str(identity.get("type") or "")
    registry_type = str((registry_item or {}).get("type") or "")
    if match_type.startswith("unmatched") or match_type.startswith("ambiguous"):
        flags.append(match_type)
    if export.get("last_status") != "pass":
        flags.append("profile_export_not_pass")
    if registry_type and registry_type != "SPREADSHEET_REPORT":
        flags.append(f"registry_type_{registry_type}")
    if report_type in {"dashboard", "monitor", "funnel", "cohort", "report"}:
        flags.append("inspect_workbook_shape_before_analysis")
    if not filters:
        flags.append("no_profile_filters")
    if any(item.get("learning_boundary") != SAFE_BOUNDARY for item in filters):
        flags.append("has_filter_safety_limits")
    if any(item.get("learning_boundary") in WEAK_BOUNDARIES for item in filters):
        flags.append("manual_or_default_only_filter")
    return sorted(set(flags))


def build_task_draft(row: dict[str, Any]) -> dict[str, Any] | None:
    report_id = row.get("report_id")
    if not report_id:
        return None
    if row.get("registry_report_type") != "SPREADSHEET_REPORT":
        return None
    task_name = task_name_for_route(str(row["report_name"]), str(report_id))
    return {
        "task": task_name,
        "dry_run_only": True,
        "command": f"python3 scripts/smartbi_cli.py run --config <CONFIG_WITH_THIS_TASK> --task {task_name} --dry-run --json",
        "config_task": {
            "enabled": True,
            "description": f"{row['report_name']}，由 BI route index 生成的取数草稿；执行前必须 dry-run 和人工确认筛选器。",
            "report": {
                "id": report_id,
                "path": row.get("smartbi_path") or "",
                "type": row.get("registry_report_type") or "SPREADSHEET_REPORT",
            },
            "filters": {
                "mode": "default",
                "overrides": [],
                "extra_params": [],
            },
            "output": {
                "type": "file",
                "dir": "outputs/bi_exports/{task}/{run_date}",
            },
        },
    }


def task_name_for_route(report_name: str, report_id: str) -> str:
    slug = "".join(ch.lower() if ch.isascii() and (ch.isalnum() or ch == "_") else "_" for ch in report_name)
    slug = "_".join(part for part in slug.split("_") if part)
    suffix = report_id[-8:].lower()
    if slug:
        return f"bi_route_{slug}_{suffix}"
    return f"bi_route_{suffix}"


def build_route_index(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    profiles = load_object(args.profiles, "profiles")
    filters = load_object(args.filters, "filters")
    kb_map = load_object(args.map, "map")
    registry = load_object(args.registry, "registry")
    filter_index = build_filter_index(filters)
    business_index = build_business_index(kb_map)
    registry_by_path, registry_by_alias = build_registry_indexes(registry)

    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    match_counts: Counter[str] = Counter()

    for key, report in (profiles.get("reports") or {}).items():
        if not isinstance(report, dict):
            continue
        identity = report.get("identity") or {}
        report_name = str(identity.get("name") or key)
        profile_path = compact_path(identity.get("path"))
        smartbi_path = smartbi_profile_path(identity)
        registry_item, match_type, confidence, candidates = match_registry(
            report_name,
            smartbi_path,
            registry_by_path,
            registry_by_alias,
        )
        match_counts[match_type] += 1
        if match_type == "unmatched":
            unmatched.append({"report_name": report_name, "smartbi_path": smartbi_path})
        if match_type == "ambiguous_alias":
            ambiguous.append(
                {
                    "report_name": report_name,
                    "smartbi_path": smartbi_path,
                    "candidates": [
                        {"id": item.get("id"), "path": item.get("path"), "type": item.get("type")}
                        for item in candidates[:8]
                    ],
                }
            )

        report_filter_items = filter_index.get(report_name, report_filters(report))
        business = business_index.get(report_name, {})
        export_status = str((report.get("export") or {}).get("last_status") or "")
        profile_type = str(identity.get("type") or "")
        role = source_role(profile_type, export_status, report_columns(report, limit=12), report_filter_items)
        row = {
            "report_name": report_name,
            "profile_path": profile_path,
            "smartbi_path": smartbi_path,
            "report_id": registry_item.get("id") if registry_item else None,
            "report_type": profile_type,
            "registry_report_type": registry_item.get("type") if registry_item else None,
            "export_status": export_status,
            "sample_columns": report_columns(report, limit=args.columns),
            "filter_summary": filter_summary(report_filter_items),
            "business_modules": business.get("business_modules", [])[:8],
            "metric_hits": business.get("metric_hits", [])[:20],
            "field_groups": business.get("field_groups", [])[:20],
            "query_metrics": business.get("query_metrics", [])[:20],
            "query_dimensions": business.get("query_dimensions", [])[:20],
            "match_type": match_type,
            "match_confidence": confidence,
            "risk_flags": risk_flags(report, registry_item, report_filter_items, match_type),
            "source_role": role["role"],
            "source_reason": role["reason"],
        }
        row["dry_run_plan"] = build_task_draft(row)
        rows.append(row)

    total = len(rows)
    matched = sum(1 for row in rows if row.get("report_id"))
    summary = {
        "profiles_total": total,
        "registry_report_id_total": len([item for item in registry.get("reports") or [] if item.get("id")]),
        "matched_total": matched,
        "match_rate": round(matched / total, 4) if total else 0,
        "matched_by_path": match_counts.get("path", 0),
        "matched_by_alias": match_counts.get("alias", 0),
        "unmatched_total": len(unmatched),
        "ambiguous_total": len(ambiguous),
        "match_type_counts": dict(sorted(match_counts.items())),
    }
    index = {
        "schema_version": "bi-report-route-index-p0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_files": {
            "profiles": str(args.profiles),
            "filters": str(args.filters),
            "map": str(args.map),
            "registry": str(args.registry),
        },
        "summary": summary,
        "reports": rows,
    }
    join_report = {
        "summary": summary,
        "unmatched_examples": unmatched[:30],
        "ambiguous_examples": ambiguous[:20],
        "core_reports": core_report_status(rows),
    }
    return index, join_report


def core_report_status(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {row["report_name"]: row for row in rows}
    status = []
    for name in CORE_REPORT_NAMES:
        row = by_name.get(name)
        status.append(
            {
                "report_name": name,
                "matched": bool(row and row.get("report_id")),
                "report_id": row.get("report_id") if row else None,
                "match_type": row.get("match_type") if row else "missing_from_profile",
                "match_confidence": row.get("match_confidence") if row else 0,
                "risk_flags": row.get("risk_flags") if row else ["missing_from_profile"],
            }
        )
    return status


def write_join_report(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# BI Report Route Join Report P0",
        "",
        "## Summary",
        "",
        f"- 总 profile 数: {summary['profiles_total']}",
        f"- registry report_id 数: {summary['registry_report_id_total']}",
        f"- 匹配数量 / 匹配率: {summary['matched_total']} / {summary['match_rate']:.2%}",
        f"- path 匹配数量: {summary['matched_by_path']}",
        f"- alias/name 匹配数量: {summary['matched_by_alias']}",
        f"- 未匹配数量: {summary['unmatched_total']}",
        f"- 歧义匹配数量: {summary['ambiguous_total']}",
        "",
        "## 投放相关核心表",
        "",
        "| 报表 | 是否匹配 | report_id | match_type | confidence | risk_flags |",
        "|---|---:|---|---|---:|---|",
    ]
    for item in payload["core_reports"]:
        lines.append(
            "| {report_name} | {matched} | {report_id} | {match_type} | {match_confidence} | {risk_flags} |".format(
                report_name=item["report_name"],
                matched="yes" if item["matched"] else "no",
                report_id=item["report_id"] or "",
                match_type=item["match_type"],
                match_confidence=item["match_confidence"],
                risk_flags=", ".join(item["risk_flags"] or []),
            )
        )
    lines.extend(["", "## Unmatched Examples", ""])
    for item in payload["unmatched_examples"]:
        lines.append(f"- {item['report_name']} -> {item['smartbi_path']}")
    lines.extend(["", "## Ambiguous Examples", ""])
    if payload["ambiguous_examples"]:
        for item in payload["ambiguous_examples"]:
            lines.append(f"- {item['report_name']} -> {len(item['candidates'])} candidates")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- 本产物只读生成，不导出 Excel，不下载报表数据。",
            "- `dry_run_plan` 只用于生成 SmartBI CLI dry-run 配置草稿，真实导出必须另行确认。",
            "- `SPREADSHEET_REPORT` / dashboard / monitor 类候选必须先检查 workbook shape，不能直接当底表。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build enriched BI report route index from local profile JSON files.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--filters", type=Path, default=DEFAULT_FILTERS)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REPORT_ID_REGISTRY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--join-report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--columns", type=int, default=16)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    index, report = build_route_index(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    args.join_report.parent.mkdir(parents=True, exist_ok=True)
    write_join_report(args.join_report, report)
    result = {
        "status": "ok",
        "index": str(args.out),
        "join_report": str(args.join_report),
        "summary": index["summary"],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
