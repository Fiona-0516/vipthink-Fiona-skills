#!/usr/bin/env python3
"""Probe a SmartBI report before export.

This script answers the operational question: what type of report is this, can
it be safely exported, and what guardrails should the caller use?
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from smartbi_browser_export import SmartbiBrowserExportError, parse_filter_json, probe_simple_report_with_browser
from smartbi_cli import SmartbiError, inspect_report, login_client, resolve_catalog_path


RAW_SOURCE_TYPES = {"SIMPLE_REPORT"}
EXPORTABLE_WORKBOOK_TYPES = {"SPREADSHEET_REPORT"}
SKIP_TYPES = {"DAQ_IMPORTCONFIG", "INSIGHT", "DEFAULT_TREENODE"}


def resolve_target(args: argparse.Namespace) -> dict[str, Any]:
    if args.path:
        client = login_client(args.username, args.password)
        report_id, resolved, resolved_path = resolve_catalog_path(client, args.path)
        leaf = resolved[-1]
        return {
            "report_id": report_id,
            "report_path": resolved_path,
            "report_type": leaf.get("type"),
            "alias": leaf.get("alias"),
            "resolved": resolved,
        }
    if not args.report_id:
        raise SmartbiError("Provide --path or --report-id", code="config_error")
    return {
        "report_id": args.report_id,
        "report_path": args.report_path,
        "report_type": args.report_type,
        "alias": None,
        "resolved": [],
    }


def recommendation_for(report_type: str | None, row_count: int | None, max_rows: int) -> dict[str, Any]:
    if report_type in RAW_SOURCE_TYPES:
        if row_count is None:
            return {"source_role": "raw_data_candidate", "action": "probe_row_count_before_export"}
        if row_count > max_rows:
            return {
                "source_role": "raw_data_candidate",
                "action": "require_filters_before_export",
                "reason": f"rowCount {row_count} exceeds maxRows {max_rows}",
            }
        return {"source_role": "raw_data_candidate", "action": "safe_to_export_with_current_filters"}
    if report_type in EXPORTABLE_WORKBOOK_TYPES:
        return {
            "source_role": "formatted_workbook",
            "action": "export_as_workbook_then_use_domain_parser",
            "reason": "SPREADSHEET_REPORT is often a pivot/dashboard workbook, not a raw table.",
        }
    if report_type in SKIP_TYPES:
        return {"source_role": "not_raw_source", "action": "skip_by_default"}
    return {"source_role": "unknown", "action": "inspect_in_browser_or_catalog_first"}


async def probe(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args)
    report_type = target.get("report_type")
    result: dict[str, Any] = {
        "status": "ok",
        "target": target,
        "probe": {},
    }

    if report_type == "SPREADSHEET_REPORT":
        client = login_client(args.username, args.password)
        result["probe"]["spreadsheet"] = inspect_report(
            client,
            str(target["report_id"]),
            report_path=target.get("report_path"),
            task_name=args.task_name,
        )
    elif report_type == "SIMPLE_REPORT":
        filters = parse_filter_json(args.filters_json)
        simple = await probe_simple_report_with_browser(
            username=args.username,
            password=args.password,
            report_id=str(target["report_id"]),
            max_rows=args.max_rows,
            browser_channel=args.browser_channel,
            headless=not args.headful,
            filters=filters,
        )
        simple.pop("panelValues", None)
        result["probe"]["simple_report"] = simple
    elif report_type in SKIP_TYPES:
        result["probe"]["skipped"] = {"reason": f"{report_type} is not treated as a raw export source by default"}
    else:
        result["probe"]["unknown"] = {
            "reason": "Report type is unknown. Provide --path or --report-type when probing by report id."
        }

    row_count = result.get("probe", {}).get("simple_report", {}).get("rowCount")
    result["recommendation"] = recommendation_for(report_type, row_count, args.max_rows)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe SmartBI report type, parameters, row count, and export readiness.")
    parser.add_argument("--path", help="SmartBI catalog path.")
    parser.add_argument("--report-id")
    parser.add_argument("--report-path")
    parser.add_argument("--report-type", choices=["SPREADSHEET_REPORT", "SIMPLE_REPORT", "INSIGHT", "DAQ_IMPORTCONFIG"])
    parser.add_argument("--task-name")
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--filters-json", help='List of [alias, value, displayValue] filters for SIMPLE_REPORT probing.')
    parser.add_argument("--browser-channel", default=os.environ.get("SMARTBI_BROWSER_CHANNEL", "chrome"))
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--username", default=os.environ.get("SMARTBI_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("SMARTBI_PASSWORD"))
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.username or not args.password:
        raise SystemExit("SMARTBI_USERNAME/SMARTBI_PASSWORD or --username/--password is required")
    try:
        result = asyncio.run(probe(args))
    except (SmartbiError, SmartbiBrowserExportError) as error:
        payload = {"status": "error", "error": {"type": error.__class__.__name__, "message": str(error)}}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(payload["error"]["message"], file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
