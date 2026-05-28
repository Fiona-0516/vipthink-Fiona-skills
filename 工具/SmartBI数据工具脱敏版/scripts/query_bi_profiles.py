#!/usr/bin/env python3
"""Query local SmartBI profile maps without logging into BI.

This is a read-only routing helper. It turns the three generated profile files
into candidate report recommendations, plus filter safety notes. It does not
download reports, call SmartBI, or generate executable export configs because
the current profile files do not include SmartBI report ids.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_DIR = ROOT / "inputs" / "bi_knowledge_maps" / "current"
DEFAULT_PROFILES = DEFAULT_KNOWLEDGE_DIR / "report_profiles_v2.json"
DEFAULT_FILTERS = DEFAULT_KNOWLEDGE_DIR / "filter_learning_inventory.json"
DEFAULT_MAP = DEFAULT_KNOWLEDGE_DIR / "kb_bi_business_data_map.json"
DEFAULT_REGISTRY = ROOT / "outputs" / "bi_catalog_registry" / "bi_report_route_index_current.json"

SAFE_BOUNDARY = "writable_or_format_learned"
WEAK_BOUNDARIES = {
    "default_only_safe_no_write",
    "manual_business_value_required",
    "neighbor_option_mismatch",
    "ui_limited_keep_default",
}


def load_object(path: Path, label: str) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return data


def normalize(text: object) -> str:
    return str(text or "").lower()


def compact_path(parts: object) -> str:
    if isinstance(parts, list):
        return " / ".join(str(part) for part in parts if part)
    return str(parts or "")


def smartbi_profile_path(parts: object) -> str:
    if isinstance(parts, list):
        cleaned = [str(part) for part in parts if part]
        if cleaned and cleaned[0] == "益智业务线":
            return "分析报表/平台业务线/" + "/".join(cleaned)
        return "分析报表/" + "/".join(cleaned)
    return "分析报表/" + str(parts or "")


def report_columns(report: dict[str, Any], limit: int | None = None) -> list[str]:
    schema = report.get("schema") or {}
    columns = schema.get("columns") or []
    names = [str(column.get("name") or "") for column in columns if isinstance(column, dict) and column.get("name")]
    return names if limit is None else names[:limit]


def report_filters(report: dict[str, Any]) -> list[dict[str, Any]]:
    filters = report.get("filters") or []
    return [item for item in filters if isinstance(item, dict)]


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
            if not isinstance(report, dict):
                continue
            name = report.get("name")
            if not name:
                continue
            current = index.setdefault(
                str(name),
                {
                    "modules": [],
                    "metric_hits": set(),
                    "field_groups": set(),
                    "query_metrics": set(),
                    "query_dimensions": set(),
                },
            )
            current["modules"].append({"id": module_id, "title": module_title})
            current["metric_hits"].update(str(x) for x in report.get("metric_hits") or [] if x)
            current["field_groups"].update(str(x) for x in (report.get("field_groups") or {}).keys() if x)
            query_fields = report.get("query_fields") or {}
            current["query_metrics"].update(str(x) for x in query_fields.get("metrics") or [] if x)
            current["query_dimensions"].update(str(x) for x in query_fields.get("dimensions") or [] if x)
    for value in index.values():
        for key in ("metric_hits", "field_groups", "query_metrics", "query_dimensions"):
            value[key] = sorted(value[key])
    return index


def build_registry_index(registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not registry:
        return {}
    index: dict[str, dict[str, Any]] = {}
    if registry.get("schema_version") == "bi-report-route-index-p0":
        for item in registry.get("reports") or []:
            if not isinstance(item, dict):
                continue
            path = item.get("smartbi_path")
            if path:
                index[str(path)] = item
    else:
        for item in registry.get("reports") or []:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if path:
                index[str(path)] = item
    return index


def registry_report_id(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    value = item.get("report_id") or item.get("id")
    return str(value) if value else None


def registry_report_type(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    value = item.get("registry_report_type") or item.get("type")
    return str(value) if value else None


def registry_match_confidence(item: dict[str, Any] | None) -> float:
    if not item:
        return 0.0
    value = item.get("match_confidence")
    if isinstance(value, (int, float)):
        return float(value)
    return 1.0 if registry_report_id(item) else 0.0


def registry_match_type(item: dict[str, Any] | None) -> str:
    if not item:
        return "unmatched"
    return str(item.get("match_type") or "path")


def build_dry_run_plan(row: dict[str, Any]) -> dict[str, Any] | None:
    report_id = row.get("report_id")
    if not report_id:
        return None
    if row.get("registry_type") != "SPREADSHEET_REPORT":
        return None
    task_name = task_name_for_route(str(row["name"]), str(report_id))
    return {
        "task": task_name,
        "dry_run_only": True,
        "command": f"python3 scripts/smartbi_cli.py run --config <CONFIG_WITH_THIS_TASK> --task {task_name} --dry-run --json",
        "config_task": {
            "enabled": True,
            "description": f"{row['name']}，由 BI route index 生成的取数草稿；执行前必须 dry-run 和人工确认筛选器。",
            "report": {
                "id": report_id,
                "path": row.get("smartbi_path") or "",
                "type": row.get("registry_type") or "SPREADSHEET_REPORT",
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
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", report_name).strip("_").lower()
    suffix = report_id[-8:].lower()
    if slug:
        return f"bi_route_{slug}_{suffix}"
    return f"bi_route_{suffix}"


def next_step_for_registry(item: dict[str, Any] | None) -> str:
    if not registry_report_id(item):
        return "candidate_only_missing_report_id"
    if registry_report_type(item) == "SPREADSHEET_REPORT":
        return "ready_for_config_draft"
    return "report_id_ready_but_cli_run_unsupported_type"


def tokenize_query(query: str) -> list[str]:
    pieces = [part.strip() for part in re.split(r"[\s,，/|]+", query or "") if part.strip()]
    return pieces


def compact_match_text(value: object) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "")).lower()


def cjk_match_text(value: object) -> str:
    return re.sub(r"[^\u4e00-\u9fff]+", "", str(value or ""))


def filter_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    boundary_counts = Counter(str(item.get("learning_boundary") or "") for item in items)
    unsafe = [
        {
            "label": item.get("normalized_label") or item.get("label") or "",
            "type": item.get("control_type") or "",
            "semantic": item.get("semantic") or "",
            "gap_status": item.get("gap_status") or "",
            "learning_boundary": item.get("learning_boundary") or "",
            "default_value": item.get("default_value") or "",
        }
        for item in items
        if item.get("learning_boundary") != SAFE_BOUNDARY
    ]
    return {
        "total": total,
        "safe": boundary_counts.get(SAFE_BOUNDARY, 0),
        "weak_or_manual": sum(boundary_counts.get(item, 0) for item in WEAK_BOUNDARIES),
        "auto_ignore": boundary_counts.get("auto_ignore_artifact", 0),
        "unsafe_examples": unsafe[:6],
    }


def source_role(report_type: str, status: str, columns: list[str], filters: list[dict[str, Any]]) -> dict[str, str]:
    if status != "pass":
        return {"role": "blocked_candidate", "reason": "profile export failed; re-probe before use"}
    if report_type in {"detail"}:
        return {"role": "raw_detail_candidate", "reason": "detail reports are usually closest to row-level data"}
    if report_type in {"dashboard", "monitor", "report", "funnel", "cohort"}:
        return {"role": "workbook_candidate", "reason": "likely formatted or aggregated; inspect workbook shape before analysis"}
    if not columns and not filters:
        return {"role": "needs_probe", "reason": "profile has limited schema/filter evidence"}
    return {"role": "unknown_candidate", "reason": "type is not enough to decide source role"}


def score_report(
    name: str,
    report: dict[str, Any],
    business: dict[str, Any] | None,
    raw_query: str,
    query_terms: list[str],
    modules: list[str],
    metrics: list[str],
) -> tuple[int, list[str]]:
    identity = report.get("identity") or {}
    columns = report_columns(report)
    filters = report_filters(report)
    path_text = compact_path(identity.get("path"))
    business = business or {}
    metric_hits = business.get("metric_hits") or []
    query_metrics = business.get("query_metrics") or []
    query_dimensions = business.get("query_dimensions") or []
    module_hits = business.get("modules") or []

    haystacks = {
        "name": name,
        "path": path_text,
        "columns": " ".join(columns),
        "filters": " ".join(str(item.get("label") or item.get("name") or "") for item in filters),
        "metrics": " ".join(metric_hits + query_metrics),
        "dimensions": " ".join(query_dimensions),
        "modules": " ".join(str(item.get("id") or "") + " " + str(item.get("title") or "") for item in module_hits),
    }
    normalized = {key: normalize(value) for key, value in haystacks.items()}

    score = 0
    reasons: list[str] = []
    compact_query = compact_match_text(raw_query)
    cjk_query = cjk_match_text(raw_query)
    if compact_query and compact_query in compact_match_text(name):
        score += 90
        reasons.append("full_query:name")
    elif cjk_query and len(cjk_query) >= 6 and cjk_query in cjk_match_text(name):
        score += 80
        reasons.append("cjk_query:name")
    if compact_query and compact_query in compact_match_text(path_text):
        score += 55
        reasons.append("full_query:path")
    elif cjk_query and len(cjk_query) >= 6 and cjk_query in cjk_match_text(path_text):
        score += 45
        reasons.append("cjk_query:path")

    weights = {
        "name": 10,
        "path": 6,
        "columns": 5,
        "filters": 4,
        "metrics": 7,
        "dimensions": 5,
        "modules": 8,
    }
    for term in query_terms:
        low = normalize(term)
        compact_term = compact_match_text(term)
        cjk_term = cjk_match_text(term)
        if len(compact_term) >= 6 and compact_term in compact_match_text(name):
            score += 80
            reasons.append(f"{term}:strong_name")
        elif len(cjk_term) >= 6 and cjk_term in cjk_match_text(name):
            score += 70
            reasons.append(f"{term}:strong_name")
        if len(compact_term) >= 6 and compact_term in compact_match_text(path_text):
            score += 45
            reasons.append(f"{term}:strong_path")
        elif len(cjk_term) >= 6 and cjk_term in cjk_match_text(path_text):
            score += 35
            reasons.append(f"{term}:strong_path")
        for key, text in normalized.items():
            if low and low in text:
                score += weights[key]
                reasons.append(f"{term}:{key}")

    for module in modules:
        low = normalize(module)
        if low and low in normalized["modules"]:
            score += 16
            reasons.append(f"{module}:module")

    for metric in metrics:
        low = normalize(metric)
        if low and (low in normalized["metrics"] or low in normalized["columns"]):
            score += 14
            reasons.append(f"{metric}:metric")

    status = (report.get("export") or {}).get("last_status")
    if status == "pass":
        score += 2
    if report_filters(report):
        score += 1
    return score, sorted(set(reasons))


def query_reports(args: argparse.Namespace) -> dict[str, Any]:
    profiles = load_object(args.profiles, "profiles")
    filter_inventory = load_object(args.filters, "filters")
    kb_map = load_object(args.map, "map")
    registry = load_object(args.registry, "registry") if args.registry and args.registry.exists() else None
    filter_index = build_filter_index(filter_inventory)
    business_index = build_business_index(kb_map)
    registry_index = build_registry_index(registry)

    query_terms = tokenize_query(args.query)
    metrics = args.metric or []
    modules = args.module or []
    if not query_terms and not metrics and not modules:
        query_terms = ["投放"]

    rows: list[dict[str, Any]] = []
    for name, report in (profiles.get("reports") or {}).items():
        if not isinstance(report, dict):
            continue
        identity = report.get("identity") or {}
        profile_path = smartbi_profile_path(identity.get("path"))
        registry_item = registry_index.get(profile_path)
        report_type = str(identity.get("type") or "")
        status = str((report.get("export") or {}).get("last_status") or "")
        if args.type and report_type != args.type:
            continue
        if args.status and status != args.status:
            continue

        business = business_index.get(str(identity.get("name") or name))
        score, reasons = score_report(str(identity.get("name") or name), report, business, args.query, query_terms, modules, metrics)
        if score <= 0 and (args.query or args.metric or args.module):
            continue

        columns = report_columns(report, limit=args.columns)
        filters = filter_index.get(str(identity.get("name") or name), report_filters(report))
        role = source_role(report_type, status, columns, filters)
        row = {
                "name": identity.get("name") or name,
                "path": compact_path(identity.get("path")),
                "smartbi_path": profile_path,
                "report_id": registry_report_id(registry_item),
                "registry_type": registry_report_type(registry_item),
                "match_type": registry_match_type(registry_item),
                "match_confidence": registry_match_confidence(registry_item),
                "type": report_type,
                "status": status,
                "score": score,
                "matched": reasons,
                "source_role": role["role"],
                "source_reason": role["reason"],
                "filter_summary": filter_summary(filters),
                "sample_columns": columns,
                "business_modules": business.get("modules", [])[:4] if business else [],
                "metric_hits": business.get("metric_hits", [])[:12] if business else [],
                "risk_flags": registry_item.get("risk_flags", []) if registry_item else [],
                "next_step": next_step_for_registry(registry_item),
            }
        row["dry_run_plan"] = registry_item.get("dry_run_plan") if registry_item and registry_item.get("dry_run_plan") else build_dry_run_plan(row)
        rows.append(row)

    rows.sort(key=lambda item: (-int(item["score"]), item["status"] != "pass", item["name"]))
    rows = rows[: args.limit]
    return {
        "status": "ok",
        "inputs": {
            "profiles": str(args.profiles),
            "filters": str(args.filters),
            "map": str(args.map),
            "registry": str(args.registry) if args.registry else None,
            "registry_loaded": bool(registry_index),
            "query": args.query,
            "modules": modules,
            "metrics": metrics,
        },
        "summary": {
            "profiles_reports": (profiles.get("summary") or {}).get("reports"),
            "matched": len(rows),
            "note": "Results include report_id and dry_run_plan when a route index or report_id registry is provided.",
        },
        "results": rows,
    }


def print_text(result: dict[str, Any]) -> None:
    summary = result["summary"]
    print(f"Matched {summary['matched']} candidate reports")
    print(summary["note"])
    print()
    for index, row in enumerate(result["results"], start=1):
        print(f"{index}. {row['name']}  score={row['score']}")
        print(f"   path: {row['path']}")
        if row.get("report_id"):
            print(f"   report_id: {row['report_id']} ({row.get('registry_type') or 'unknown'})")
            print(f"   match: {row.get('match_type')} confidence={row.get('match_confidence')}")
        print(f"   type/status: {row['type'] or 'unknown'} / {row['status'] or 'unknown'}")
        print(f"   role: {row['source_role']} - {row['source_reason']}")
        if row["matched"]:
            print(f"   matched: {', '.join(row['matched'][:10])}")
        if row["metric_hits"]:
            print(f"   metrics: {', '.join(row['metric_hits'])}")
        print(f"   filters: total={row['filter_summary']['total']} safe={row['filter_summary']['safe']} weak/manual={row['filter_summary']['weak_or_manual']}")
        if row["filter_summary"]["unsafe_examples"]:
            examples = "; ".join(
                f"{item['label']}[{item['learning_boundary']}]" for item in row["filter_summary"]["unsafe_examples"][:3]
            )
            print(f"   filter risks: {examples}")
        if row["sample_columns"]:
            print(f"   sample columns: {', '.join(row['sample_columns'][:10])}")
        if row.get("report_id"):
            print("   next: can draft SmartBI CLI config; still dry-run before export")
            plan = row.get("dry_run_plan") or {}
            if plan.get("command"):
                print(f"   dry-run: {plan['command']}")
        else:
            print("   next: candidate only; resolve report_id from catalog before SmartBI CLI export")
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query local SmartBI profile maps and recommend candidate reports.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--filters", type=Path, default=DEFAULT_FILTERS)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="Optional report_id registry JSON.")
    parser.add_argument("--query", default="", help="Business question, keyword, report name, field, or path fragment.")
    parser.add_argument("--module", action="append", help="Business module id/title, such as 02-growth or 09-regions.")
    parser.add_argument("--metric", action="append", help="Metric keyword, such as ROI2, 消耗, 约课率.")
    parser.add_argument("--type", help="Report type filter, such as detail/report/monitor/funnel/dashboard.")
    parser.add_argument("--status", help="Export status filter, such as pass/fail.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--columns", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = query_reports(args)
    except Exception as error:
        payload = {"status": "error", "error": str(error)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"query failed: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
