#!/usr/bin/env python3
"""Offline validator for SmartBI Data CLI task configs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_DATE_WINDOWS = {"previous_week", "current_week_snapshot", "previous_month"}
OUTPUT_PLACEHOLDERS = {"task", "run_date", "run_id"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    return data


def validate_config(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tasks = data.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        return ["tasks must be a non-empty object"]

    for task_name, task in tasks.items():
        prefix = f"tasks.{task_name}"
        if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$", str(task_name)):
            errors.append(f"{prefix}: task name should use ASCII letters, numbers, '_' or '-'")
        if not isinstance(task, dict):
            errors.append(f"{prefix}: task must be an object")
            continue
        errors.extend(validate_task(prefix, task))
    return errors


def validate_task(prefix: str, task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "enabled" in task and not isinstance(task["enabled"], bool):
        errors.append(f"{prefix}.enabled: must be boolean when present")

    report = task.get("report")
    if not isinstance(report, dict):
        errors.append(f"{prefix}.report: required object")
    else:
        report_id = report.get("id")
        if not isinstance(report_id, str) or not report_id:
            errors.append(f"{prefix}.report.id: required non-empty string")
        report_type = report.get("type", "SPREADSHEET_REPORT")
        if report_type != "SPREADSHEET_REPORT":
            errors.append(f"{prefix}.report.type: V1 only supports SPREADSHEET_REPORT")

    filters = task.get("filters", {})
    if not isinstance(filters, dict):
        errors.append(f"{prefix}.filters: must be object when present")
    else:
        date_window = filters.get("date_window")
        if date_window is not None and date_window not in ALLOWED_DATE_WINDOWS:
            errors.append(f"{prefix}.filters.date_window: unsupported value {date_window!r}")
        overrides = filters.get("overrides", [])
        if not isinstance(overrides, list):
            errors.append(f"{prefix}.filters.overrides: must be list when present")
        else:
            for index, override in enumerate(overrides):
                errors.extend(validate_param_override(f"{prefix}.filters.overrides[{index}]", override))
        extra_params = filters.get("extra_params", [])
        if not isinstance(extra_params, list):
            errors.append(f"{prefix}.filters.extra_params: must be list when present")
        else:
            for index, extra in enumerate(extra_params):
                errors.extend(validate_extra_param(f"{prefix}.filters.extra_params[{index}]", extra))

    output = task.get("output", {})
    if not isinstance(output, dict):
        errors.append(f"{prefix}.output: must be object when present")
    else:
        output_dir = output.get("dir", "outputs/bi_exports/{task}/{run_date}")
        if not isinstance(output_dir, str) or not output_dir:
            errors.append(f"{prefix}.output.dir: must be non-empty string")
        else:
            errors.extend(validate_output_template(f"{prefix}.output.dir", output_dir))

    return errors


def validate_param_override(prefix: str, override: object) -> list[str]:
    if not isinstance(override, dict):
        return [f"{prefix}: must be object"]
    errors = []
    if not isinstance(override.get("key"), str) or not override.get("key"):
        errors.append(f"{prefix}.key: required non-empty string")
    if "value" not in override:
        errors.append(f"{prefix}.value: required")
    return errors


def validate_extra_param(prefix: str, extra: object) -> list[str]:
    if not isinstance(extra, dict):
        return [f"{prefix}: must be object"]
    errors = []
    if not isinstance(extra.get("id") or extra.get("key"), str) or not (extra.get("id") or extra.get("key")):
        errors.append(f"{prefix}.id: required non-empty string")
    if not isinstance(extra.get("name") or extra.get("key"), str) or not (extra.get("name") or extra.get("key")):
        errors.append(f"{prefix}.name: required non-empty string")
    return errors


def validate_output_template(prefix: str, template: str) -> list[str]:
    errors = []
    for match in re.finditer(r"{([^{}]+)}", template):
        placeholder = match.group(1)
        if placeholder not in OUTPUT_PLACEHOLDERS:
            errors.append(f"{prefix}: unsupported placeholder {{{placeholder}}}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate SmartBI Data CLI task config without logging into BI.")
    parser.add_argument("config", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_json(args.config)
        errors = validate_config(data)
    except Exception as error:
        errors = [str(error)]

    result = {"status": "ok" if not errors else "error", "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Config validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("Config validation passed")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
