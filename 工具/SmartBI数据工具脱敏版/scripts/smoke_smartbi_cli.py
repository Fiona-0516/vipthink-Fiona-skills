#!/usr/bin/env python3
"""Local smoke checks for the SmartBI Data CLI foundation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "smartbi_cli.py"
DEFAULT_CONFIG = ROOT / "configs" / "smartbi_tasks.json"
DEFAULT_TASK = "outbound_quality_hk_nonbulk_previous_week"
VALIDATOR = ROOT / "scripts" / "validate_smartbi_config.py"
DRAFT = ROOT / "outputs" / "bi_catalog_drafts" / "outbound_catalog_draft_2026-05-16.json"
MAX_CAPTURE_CHARS = 1200


def compact_text(value: str, limit: int = MAX_CAPTURE_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... truncated {len(value) - limit} chars"


def run_check(name: str, command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "name": name,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": compact_text(completed.stdout.strip()),
        "stderr": compact_text(completed.stderr.strip()),
    }


def check_no_plaintext_secrets() -> dict[str, object]:
    targets = [ROOT / "scripts", ROOT / "configs", ROOT / "docs"]
    banned = {"123" + "456", "235" + "08"}
    hits = []
    for target in targets:
        if not target.exists():
            continue
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for token in banned:
                if token in text:
                    hits.append(f"{path}: contains {token}")
    return {
        "name": "no_plaintext_secrets",
        "ok": not hits,
        "returncode": 0 if not hits else 2,
        "stdout": "",
        "stderr": "\n".join(hits),
    }


def check_draft_shape() -> dict[str, object]:
    if not DRAFT.exists():
        return {
            "name": "catalog_draft_shape",
            "ok": True,
            "returncode": 0,
            "stdout": "skipped: draft file does not exist yet",
            "stderr": "",
        }
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    ok = isinstance(data.get("tasks"), dict) and isinstance(data.get("inspections"), dict)
    ok = ok and data.get("report_count", 0) == len(data.get("tasks", {}))
    return {
        "name": "catalog_draft_shape",
        "ok": bool(ok),
        "returncode": 0 if ok else 2,
        "stdout": f"report_count={data.get('report_count')} tasks={len(data.get('tasks', {}))}",
        "stderr": "" if ok else "draft must include matching report_count, tasks, and inspections",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline SmartBI Data CLI smoke checks.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = args.config.expanduser()
    checks = [
        run_check("py_compile_cli", [sys.executable, "-m", "py_compile", str(CLI)]),
        run_check("py_compile_validator", [sys.executable, "-m", "py_compile", str(VALIDATOR)]),
        run_check("json_config", [sys.executable, "-m", "json.tool", str(config)]),
        run_check("validate_config", [sys.executable, str(VALIDATOR), str(config), "--json"]),
        run_check(
            "dry_run_config_task",
            [
                sys.executable,
                str(CLI),
                "run",
                "--config",
                str(config),
                "--task",
                args.task,
                "--dry-run",
                "--json",
            ],
        ),
        check_draft_shape(),
        check_no_plaintext_secrets(),
    ]
    ok = all(bool(check["ok"]) for check in checks)
    result = {"status": "ok" if ok else "error", "checks": checks}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            marker = "PASS" if check["ok"] else "FAIL"
            print(f"{marker} {check['name']}")
            if check["stdout"]:
                print(f"  stdout: {check['stdout']}")
            if check["stderr"]:
                print(f"  stderr: {check['stderr']}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
