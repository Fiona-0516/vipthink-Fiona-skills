#!/usr/bin/env python3
"""Offline validator for SmartBI Excel writeback inputs.

This script is intentionally local-only: it opens the workbook, validates the
configured template contract, and writes a machine-readable dry-run report.
It does not log in to SmartBI and it does not upload files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/smartbi_writeback_tasks.json"


class ValidationError(RuntimeError):
    pass


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValidationError("config root must be an object")
    return data


def get_task(config: dict[str, Any], task_name: str) -> dict[str, Any]:
    tasks = config.get("tasks")
    if not isinstance(tasks, dict):
        raise ValidationError("config missing tasks object")
    task = tasks.get(task_name)
    if not isinstance(task, dict):
        available = ", ".join(sorted(str(name) for name in tasks))
        raise ValidationError(f"unknown task {task_name!r}; available: {available}")
    if task.get("enabled") is False:
        raise ValidationError(f"task {task_name!r} is disabled")
    return task


def clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def cell_text(value: Any) -> str:
    value = clean(value)
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value).strip()


def is_empty(value: Any) -> bool:
    return cell_text(value) == ""


def is_allowed_path(path: Path, allowed_dirs: list[str]) -> bool:
    resolved = path.resolve()
    for item in allowed_dirs:
        allowed = Path(item)
        if not allowed.is_absolute():
            allowed = ROOT / allowed
        try:
            resolved.relative_to(allowed.resolve())
            return True
        except ValueError:
            continue
    return False


def parse_date(value: Any) -> str | None:
    value = clean(value)
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_decimal(value: Any) -> Decimal | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def compact_counter(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    return dict(counter.most_common(limit))


def validate_workbook(path: Path, task_name: str, task: dict[str, Any]) -> dict[str, Any]:
    input_cfg = task.get("input") or {}
    schema = task.get("schema") or {}
    if not isinstance(input_cfg, dict) or not isinstance(schema, dict):
        raise ValidationError("task must include input and schema objects")

    errors: list[str] = []
    warnings: list[str] = []
    path = path.expanduser()
    if not path.exists():
        raise ValidationError(f"input workbook not found: {path}")
    if path.suffix.lower() != ".xlsx":
        errors.append(f"input file must be .xlsx, got {path.suffix}")

    allowed_dirs = [str(item) for item in input_cfg.get("allowed_dirs", [])]
    if allowed_dirs and not is_allowed_path(path, allowed_dirs):
        errors.append(f"input file is outside allowed dirs: {path}")

    pattern = input_cfg.get("filename_pattern")
    if isinstance(pattern, str) and not re.match(pattern, path.name):
        errors.append(f"filename does not match configured pattern: {path.name}")

    # Normal mode is faster for this small writeback template than read-only
    # random cell access, and it preserves exact original row numbers.
    workbook = load_workbook(path, read_only=False, data_only=True)
    primary_sheet_name = str(input_cfg.get("sheet_name") or workbook.sheetnames[0])
    layouts: list[dict[str, Any]] = [
        {
            "name": "primary",
            "sheet_name": primary_sheet_name,
            "header_row": int(input_cfg.get("header_row", 1)),
            "data_start_row": int(input_cfg.get("data_start_row", int(input_cfg.get("header_row", 1)) + 1)),
            "expected_headers": [str(item) for item in schema.get("expected_headers", [])],
        }
    ]
    for layout in input_cfg.get("accepted_layouts", []) if isinstance(input_cfg.get("accepted_layouts"), list) else []:
        if isinstance(layout, dict):
            layouts.append(layout)

    selected_layout = layouts[0]
    selected_ws = None
    expected_headers = [str(item) for item in selected_layout.get("expected_headers", [])]
    header_row = int(selected_layout.get("header_row", 1))
    actual_headers: list[str] = []
    for layout in layouts:
        candidate_sheet_name = str(layout.get("sheet_name") or primary_sheet_name)
        if candidate_sheet_name not in workbook.sheetnames:
            continue
        candidate_expected = [str(item) for item in layout.get("expected_headers", [])]
        if not candidate_expected:
            continue
        candidate_header_row = int(layout.get("header_row", 1))
        candidate_ws = workbook[candidate_sheet_name]
        candidate_actual = [
            cell_text(candidate_ws.cell(candidate_header_row, col).value)
            for col in range(1, len(candidate_expected) + 1)
        ]
        if candidate_actual == candidate_expected:
            selected_layout = layout
            selected_ws = candidate_ws
            expected_headers = candidate_expected
            header_row = candidate_header_row
            actual_headers = candidate_actual
            break

    if selected_ws is None:
        sheet_names = [str(layout.get("sheet_name") or primary_sheet_name) for layout in layouts]
        raise ValidationError(f"none of configured sheets {sheet_names!r} found; available: {workbook.sheetnames}")
    if not actual_headers:
        actual_headers = [cell_text(selected_ws.cell(header_row, col).value) for col in range(1, len(expected_headers) + 1)]

    ws = selected_ws
    sheet_name = str(selected_layout.get("sheet_name") or primary_sheet_name)
    data_start_row = int(selected_layout.get("data_start_row", header_row + 1))
    if actual_headers != expected_headers:
        missing = [header for header in expected_headers if header not in actual_headers]
        unexpected = [header for header in actual_headers if header and header not in expected_headers]
        errors.append("header row does not match any expected writeback template")
        if missing:
            errors.append(f"missing headers: {missing}")
        if unexpected:
            errors.append(f"unexpected headers: {unexpected}")

    header_to_col = {header: index + 1 for index, header in enumerate(actual_headers) if header}
    required = [str(item) for item in selected_layout.get("required_non_empty", schema.get("required_non_empty", []))]
    numeric_columns = [str(item) for item in selected_layout.get("numeric_columns", schema.get("numeric_columns", []))]
    date_columns = [str(item) for item in selected_layout.get("date_columns", schema.get("date_columns", []))]
    summary_columns = [str(item) for item in selected_layout.get("business_summary_columns", schema.get("business_summary_columns", []))]

    max_rows = int(input_cfg.get("max_rows", 5000))
    data_rows = []
    empty_streak = 0
    for row_number in range(data_start_row, ws.max_row + 1):
        row = {header: ws.cell(row_number, col).value for header, col in header_to_col.items()}
        if all(is_empty(value) for value in row.values()):
            empty_streak += 1
            continue
        empty_streak = 0
        data_rows.append((row_number, row))
        if len(data_rows) > max_rows:
            errors.append(f"data rows exceed max_rows {max_rows}")
            break
    if empty_streak:
        warnings.append(f"ignored {empty_streak} empty trailing/intermediate rows")

    required_missing: dict[str, list[int]] = defaultdict(list)
    invalid_dates: dict[str, list[int]] = defaultdict(list)
    invalid_numbers: dict[str, list[int]] = defaultdict(list)
    distinct: dict[str, Counter[str]] = {name: Counter() for name in summary_columns}
    date_ranges: dict[str, dict[str, str]] = {}
    numeric_sums: dict[str, str] = {}
    numeric_accumulators: dict[str, Decimal] = {name: Decimal("0") for name in numeric_columns}

    for row_number, row in data_rows:
        for column in required:
            if is_empty(row.get(column)):
                required_missing[column].append(row_number)
        for column in date_columns:
            value = row.get(column)
            if is_empty(value):
                continue
            parsed = parse_date(value)
            if parsed is None:
                invalid_dates[column].append(row_number)
            else:
                current = date_ranges.setdefault(column, {"min": parsed, "max": parsed})
                current["min"] = min(current["min"], parsed)
                current["max"] = max(current["max"], parsed)
        for column in numeric_columns:
            value = row.get(column)
            if is_empty(value):
                continue
            parsed = parse_decimal(value)
            if parsed is None:
                invalid_numbers[column].append(row_number)
            else:
                numeric_accumulators[column] += parsed
        for column in summary_columns:
            value = cell_text(row.get(column))
            if value:
                distinct[column][value] += 1

    for column, rows in required_missing.items():
        errors.append(f"{column}: required value missing at rows {rows[:20]}{'...' if len(rows) > 20 else ''}")
    for column, rows in invalid_dates.items():
        errors.append(f"{column}: invalid date values at rows {rows[:20]}{'...' if len(rows) > 20 else ''}")
    for column, rows in invalid_numbers.items():
        errors.append(f"{column}: invalid numeric values at rows {rows[:20]}{'...' if len(rows) > 20 else ''}")
    for column, value in numeric_accumulators.items():
        if value:
            numeric_sums[column] = format(value, "f")

    return {
        "status": "ok" if not errors else "error",
        "mode": "offline_writeback_dry_run",
        "boundary": {
            "no_smartbi_login": True,
            "no_upload": True,
            "no_external_write": True,
        },
        "task": task_name,
        "target": task.get("target"),
        "input": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sheet_name": sheet_name,
            "workbook_sheets": workbook.sheetnames,
            "max_row": ws.max_row,
            "max_column": ws.max_column,
            "header_row": header_row,
            "data_start_row": data_start_row,
            "data_rows": len(data_rows),
        },
        "schema": {
            "layout": selected_layout.get("name", "primary"),
            "expected_header_count": len(expected_headers),
            "actual_header_count": len([item for item in actual_headers if item]),
            "headers_match": actual_headers == expected_headers,
            "required_non_empty": required,
        },
        "quality": {
            "date_ranges": date_ranges,
            "numeric_sums": numeric_sums,
            "distinct": {name: compact_counter(counter) for name, counter in distinct.items()},
        },
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a SmartBI writeback Excel file without uploading it.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task", required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        task = get_task(config, args.task)
        result = validate_workbook(args.file, args.task, task)
    except Exception as error:
        result = {
            "status": "error",
            "mode": "offline_writeback_dry_run",
            "boundary": {
                "no_smartbi_login": True,
                "no_upload": True,
                "no_external_write": True,
            },
            "errors": [str(error)],
            "warnings": [],
        }

    if args.out:
        out_path = args.out.expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output"] = str(out_path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["status"] == "ok":
        print("SmartBI writeback dry-run validation passed")
    else:
        print("SmartBI writeback dry-run validation failed", file=sys.stderr)
        for error in result.get("errors", []):
            print(f"- {error}", file=sys.stderr)
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
