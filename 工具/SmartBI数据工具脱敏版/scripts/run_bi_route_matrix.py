#!/usr/bin/env python3
"""Run an offline BI route matrix without logging into SmartBI.

The matrix turns business questions into reviewable dry-run packets by reusing
build_bi_route_dry_run_packet.py. It writes a JSON/Markdown summary that mirrors
the public BI export matrix pattern, but never exports reports.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "bi_route_matrix_p0.json"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("matrix config root must be an object")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("matrix config must contain a non-empty cases list")
    return data


def resolve_path(path_value: str | None, default: Path) -> Path:
    if not path_value:
        return default
    path = Path(path_value)
    return path if path.is_absolute() else ROOT / path


def run_packet(case: dict[str, Any], registry: Path, run_root: Path, limit: int) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = str(case.get("id") or "").strip()
    query = str(case.get("query") or "").strip()
    if not case_id or not query:
        raise ValueError("each case requires non-empty id and query")

    packet_path = run_root / case_id / f"{case_id}.json"
    command = [
        "python3",
        "scripts/build_bi_route_dry_run_packet.py",
        "--query",
        query,
        "--registry",
        str(registry),
        "--limit",
        str(limit),
        "--out",
        str(packet_path),
        "--json",
    ]
    for metric in case.get("metrics") or []:
        command.extend(["--metric", str(metric)])

    started_at = datetime.now().isoformat(timespec="seconds")
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    ended_at = datetime.now().isoformat(timespec="seconds")

    packet: dict[str, Any] = {}
    if packet_path.exists():
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

    return packet, {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "started_at": started_at,
        "ended_at": ended_at,
        "packet_path": str(packet_path),
    }


def evaluate_case(case: dict[str, Any], packet: dict[str, Any], command_result: dict[str, Any]) -> dict[str, Any]:
    recommended = packet.get("recommended_report") or {}
    decision = packet.get("decision") or {}
    config_validation = packet.get("dry_run_config_validation") or {}

    expected_reports = {str(item) for item in case.get("expected_reports") or []}
    expected_type = case.get("expected_registry_type")
    report_name = str(recommended.get("report_name") or "")
    registry_type = recommended.get("registry_type")
    report_id = recommended.get("report_id")

    checks = {
        "command_ok": command_result.get("exit_code") == 0,
        "has_packet": bool(packet),
        "has_report_id": bool(report_id),
        "config_validation_ok": config_validation.get("status") == "ok",
        "expected_report_hit": not expected_reports or report_name in expected_reports,
        "expected_type_hit": not expected_type or registry_type == expected_type,
        "no_export_boundary": bool((packet.get("boundary") or {}).get("no_smartbi_export")),
    }

    failed_checks = [name for name, passed in checks.items() if not passed]
    if not failed_checks and decision.get("status") in {"dry_run_ready", "dry_run_ready_after_human_confirmation"}:
        status = "pass"
    elif checks["command_ok"] and checks["has_packet"] and checks["has_report_id"]:
        status = "weak"
    else:
        status = "fail"

    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "metrics": case.get("metrics") or [],
        "status": status,
        "failed_checks": failed_checks,
        "recommended_report": report_name,
        "report_id": report_id,
        "registry_type": registry_type,
        "decision": decision,
        "config_validation": config_validation,
        "risk_flags": recommended.get("risk_flags") or [],
        "filter_summary": recommended.get("filter_summary") or {},
        "packet_path": command_result.get("packet_path"),
    }


def write_summary(run_root: Path, config_path: Path, results: list[dict[str, Any]], command_results: list[dict[str, Any]]) -> tuple[Path, Path]:
    counts = {
        "total": len(results),
        "pass": sum(1 for item in results if item["status"] == "pass"),
        "weak": sum(1 for item in results if item["status"] == "weak"),
        "fail": sum(1 for item in results if item["status"] == "fail"),
    }
    summary = {
        "schema_version": "bi-route-matrix-summary-p0",
        "config": str(config_path),
        "run_root": str(run_root),
        "counts": counts,
        "boundary": {
            "offline_only": True,
            "no_smartbi_login": True,
            "no_excel_export": True,
            "no_ad_system_write": True,
        },
        "results": results,
        "commands": command_results,
    }
    summary_json = run_root / "matrix-summary.json"
    summary_md = run_root / "matrix-summary.md"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# BI Route Matrix {run_root.name}",
        "",
        f"- Config: `{config_path}`",
        f"- Total: {counts['total']}",
        f"- Pass: {counts['pass']}",
        f"- Weak: {counts['weak']}",
        f"- Fail: {counts['fail']}",
        "- Boundary: offline only; no SmartBI login; no Excel export; no ad-system write.",
        "",
        "| ID | Status | Recommended Report | Report ID | Decision | Failed Checks |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        decision = (item.get("decision") or {}).get("status") or ""
        failed = ", ".join(item.get("failed_checks") or [])
        lines.append(
            "| {id} | {status} | {report} | {report_id} | {decision} | {failed} |".format(
                id=item.get("id") or "",
                status=item.get("status") or "",
                report=item.get("recommended_report") or "",
                report_id=item.get("report_id") or "",
                decision=decision,
                failed=failed,
            )
        )
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_json, summary_md


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline BI route matrix cases.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-id")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    registry = resolve_path(config.get("registry"), ROOT / "outputs" / "bi_catalog_registry" / "bi_report_route_index_current.json")
    output_root = resolve_path(config.get("output_root"), ROOT / "outputs" / "bi_catalog_registry" / "matrix_runs")
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = output_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    wanted = {item for value in args.case_id for item in str(value).split(",") if item}
    cases = [case for case in config["cases"] if not wanted or str(case.get("id")) in wanted]
    if not cases:
        raise ValueError("no cases selected")

    results = []
    command_results = []
    for case in cases:
        packet, command_result = run_packet(case, registry, run_root, args.limit)
        command_results.append(command_result)
        results.append(evaluate_case(case, packet, command_result))

    summary_json, summary_md = write_summary(run_root, args.config, results, command_results)
    response = {
        "status": "ok" if all(item["status"] != "fail" for item in results) else "error",
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
        "counts": {
            "total": len(results),
            "pass": sum(1 for item in results if item["status"] == "pass"),
            "weak": sum(1 for item in results if item["status"] == "weak"),
            "fail": sum(1 for item in results if item["status"] == "fail"),
        },
    }
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        print(f"SUMMARY_JSON={summary_json}")
        print(f"SUMMARY_MD={summary_md}")
        print(f"PASS={response['counts']['pass']} WEAK={response['counts']['weak']} FAIL={response['counts']['fail']}")
    return 0 if response["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
