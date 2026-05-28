#!/usr/bin/env python3
"""Run multiple SmartBI Data CLI tasks as a bounded batch.

The default mode runs only `smartbi_cli.py run --dry-run`. Real exports require
an explicit `--execute` flag and credentials from the environment.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "smartbi_tasks.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "smartbi_batch_runs"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    tasks = data.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise ValueError("config must include a non-empty tasks object")
    return data


def resolve_path(value: str | Path, default_root: Path = ROOT) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else default_root / path


def select_tasks(config: dict[str, Any], requested: list[str], all_tasks: bool) -> list[str]:
    tasks = config.get("tasks") or {}
    if all_tasks:
        selected = sorted(str(task_name) for task_name in tasks)
    else:
        selected = requested
    if not selected:
        raise ValueError("select tasks with --task or --all-tasks")
    unknown = [task_name for task_name in selected if task_name not in tasks]
    if unknown:
        raise ValueError(f"unknown task(s): {', '.join(unknown)}")
    return selected


def require_execute_environment() -> None:
    missing = [name for name in ("SMARTBI_USERNAME", "SMARTBI_PASSWORD") if not os.environ.get(name)]
    if missing:
        raise ValueError(f"--execute requires environment variable(s): {', '.join(missing)}")


def run_task(
    config_path: Path,
    task_name: str,
    execute: bool,
    overwrite: bool,
    worker_timeout_sec: float | None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "smartbi_cli.py"),
        "run",
        "--config",
        str(config_path),
        "--task",
        task_name,
    ]
    if execute:
        if overwrite:
            command.append("--overwrite")
    else:
        command.append("--dry-run")
    command.append("--json")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=worker_timeout_sec,
        )
    except subprocess.TimeoutExpired as error:
        duration_sec = round(time.perf_counter() - started, 3)
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return {
            "task": task_name,
            "status": "fail",
            "mode": "execute" if execute else "dry_run",
            "duration_sec": duration_sec,
            "returncode": 124,
            "command": command,
            "payload": None,
            "parse_error": None,
            "stderr": (stderr.strip() + f"\ntimeout after {worker_timeout_sec}s").strip(),
            "stdout": stdout.strip(),
            "timeout": True,
            "timeout_sec": worker_timeout_sec,
        }
    duration_sec = round(time.perf_counter() - started, 3)
    payload: dict[str, Any] | None = None
    parse_error = None
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            parse_error = str(error)

    expected_status = "exported" if execute else "dry_run"
    ok = completed.returncode == 0 and payload is not None and payload.get("status") == expected_status
    return {
        "task": task_name,
        "status": "pass" if ok else "fail",
        "mode": "execute" if execute else "dry_run",
        "duration_sec": duration_sec,
        "returncode": completed.returncode,
        "command": command,
        "payload": payload,
        "parse_error": parse_error,
        "stderr": completed.stderr.strip(),
        "timeout": False,
        "timeout_sec": worker_timeout_sec,
    }


def result_plan_or_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return {}
    if payload.get("status") == "dry_run":
        plan = payload.get("plan")
        return plan if isinstance(plan, dict) else {}
    return payload


def write_summary(
    run_root: Path,
    config_path: Path,
    results: list[dict[str, Any]],
    max_workers: int,
    execute: bool,
    batch_duration_sec: float,
    worker_timeout_sec: float | None,
    warnings: list[str],
) -> tuple[Path, Path]:
    counts = {
        "total": len(results),
        "pass": sum(1 for item in results if item["status"] == "pass"),
        "fail": sum(1 for item in results if item["status"] == "fail"),
    }
    mode = "execute" if execute else "dry_run_only"
    summary = {
        "schema_version": "smartbi-batch-p1",
        "mode": mode,
        "config": str(config_path),
        "run_root": str(run_root),
        "max_workers": max_workers,
        "worker_timeout_sec": worker_timeout_sec,
        "batch_duration_sec": batch_duration_sec,
        "warnings": warnings,
        "boundary": {
            "no_smartbi_login": not execute,
            "no_excel_export": not execute,
            "no_credentials_required": not execute,
            "credentials_from_environment": execute,
            "credentials_not_written": True,
            "no_external_writes": True,
        },
        "counts": counts,
        "results": results,
    }
    run_root.mkdir(parents=True, exist_ok=True)
    summary_json = run_root / "batch-summary.json"
    summary_md = run_root / "batch-summary.md"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# SmartBI Batch {run_root.name}",
        "",
        f"- Config: `{config_path}`",
        f"- Mode: `{mode}`",
        f"- Max workers: `{max_workers}`",
        f"- Worker timeout sec: `{worker_timeout_sec if worker_timeout_sec is not None else 'none'}`",
        f"- Batch duration sec: `{batch_duration_sec}`",
        f"- Total: {counts['total']}",
        f"- Pass: {counts['pass']}",
        f"- Fail: {counts['fail']}",
        "- Boundary: credentials are read only from environment; no external writes.",
    ]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Task | Status | Duration Sec | Timeout | Report ID | Output | Timing Total Sec | Export Sec |",
            "| --- | --- | ---: | --- | --- | --- | ---: | ---: |",
        ]
    )
    for item in results:
        payload = result_plan_or_payload(item)
        timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
        export_sec = ""
        for step in timings.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == "export_spreadsheet_report":
                export_sec = step.get("duration_sec")
                break
        lines.append(
            "| {task} | {status} | {duration} | {timeout} | {report_id} | {output} | {timing_total} | {export_sec} |".format(
                task=item.get("task") or "",
                status=item.get("status") or "",
                duration=item.get("duration_sec"),
                timeout="yes" if item.get("timeout") else "",
                report_id=payload.get("report_id") or "",
                output=payload.get("output") or payload.get("out_dir") or "",
                timing_total=timings.get("total_sec", ""),
                export_sec=export_sec,
            )
        )
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_json, summary_md


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bounded SmartBI CLI tasks in parallel.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task", action="append", default=[], help="Task name. May be repeated or comma-separated.")
    parser.add_argument("--all-tasks", action="store_true", help="Select every task in the config.")
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument(
        "--worker-timeout-sec",
        type=float,
        help="Optional per-task subprocess timeout. Timed-out tasks fail with return code 124.",
    )
    parser.add_argument("--execute", action="store_true", help="Run real exports. Default is dry-run only.")
    parser.add_argument("--overwrite", action="store_true", help="Pass --overwrite to real export tasks.")
    parser.add_argument("--run-id", help="Output run id. Defaults to current timestamp.")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = resolve_path(args.config)
    out_root = resolve_path(args.out_root)
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    run_root = out_root / run_id
    max_workers = max(1, args.max_workers)
    worker_timeout_sec = args.worker_timeout_sec
    if worker_timeout_sec is not None and worker_timeout_sec <= 0:
        raise ValueError("--worker-timeout-sec must be positive when provided")

    requested = [item for value in args.task for item in str(value).split(",") if item]
    config = load_config(config_path)
    selected = select_tasks(config, requested, args.all_tasks)
    if args.execute:
        require_execute_environment()
    warnings: list[str] = []
    if max_workers > 3:
        warnings.append(f"max_workers={max_workers} is above the default safe concurrency of 3; monitor SmartBI stability.")

    results: list[dict[str, Any]] = []
    batch_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_task, config_path, task_name, args.execute, args.overwrite, worker_timeout_sec): task_name
            for task_name in selected
        }
        for future in concurrent.futures.as_completed(future_map):
            results.append(future.result())
    batch_duration_sec = round(time.perf_counter() - batch_started, 3)
    results.sort(key=lambda item: selected.index(str(item["task"])))

    summary_json, summary_md = write_summary(
        run_root,
        config_path,
        results,
        max_workers,
        args.execute,
        batch_duration_sec,
        worker_timeout_sec,
        warnings,
    )
    response = {
        "status": "ok" if all(item["status"] == "pass" for item in results) else "error",
        "mode": "execute" if args.execute else "dry_run_only",
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
        "batch_duration_sec": batch_duration_sec,
        "worker_timeout_sec": worker_timeout_sec,
        "warnings": warnings,
        "counts": {
            "total": len(results),
            "pass": sum(1 for item in results if item["status"] == "pass"),
            "fail": sum(1 for item in results if item["status"] == "fail"),
        },
        "boundary": {
            "no_smartbi_login": not args.execute,
            "no_excel_export": not args.execute,
            "no_credentials_required": not args.execute,
            "credentials_from_environment": args.execute,
        },
    }
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        print(f"SUMMARY_JSON={summary_json}")
        print(f"SUMMARY_MD={summary_md}")
        print(f"PASS={response['counts']['pass']} FAIL={response['counts']['fail']}")
    return 0 if response["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
