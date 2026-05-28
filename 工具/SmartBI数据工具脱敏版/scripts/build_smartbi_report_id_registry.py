#!/usr/bin/env python3
"""Build a read-only SmartBI report_id registry from catalog metadata.

The registry is the fourth JSON that complements:

- report_profiles_v2.json
- filter_learning_inventory.json
- kb_bi_business_data_map.json

It only reads the SmartBI catalog. It does not open reports, export workbooks,
download data, or mutate any project files outside the explicit output path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from smartbi_cli import SmartbiClient, SmartbiError, login_client, required_element_id, resolve_catalog_path


DEFAULT_ROOT_PATHS = [
    "分析报表/海外直播业务线",
    "分析报表/平台业务线",
]
DEFAULT_KNOWLEDGE_DIR = ROOT / "inputs" / "bi_knowledge_maps" / "current"
DEFAULT_PROFILES = DEFAULT_KNOWLEDGE_DIR / "report_profiles_v2.json"
DEFAULT_OUT_DIR = ROOT / "outputs" / "bi_catalog_registry"


def normalize_element(element: dict[str, Any], path: str, depth: int) -> dict[str, Any]:
    alias = element.get("alias") or element.get("name") or element.get("id")
    return {
        "id": element.get("id"),
        "alias": alias,
        "name": element.get("name"),
        "type": element.get("type"),
        "path": path,
        "depth": depth,
        "has_child": bool(element.get("hasChild")),
    }


def walk_catalog(
    client: SmartbiClient,
    parent_id: str,
    parent_path: str,
    max_depth: int,
    report_types: set[str] | None,
    delay_seconds: float,
    depth: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        children = client.child_elements(parent_id)
    except SmartbiError as error:
        return [], [{"path": parent_path, "code": error.code, "message": str(error)}]

    for child in children:
        label = str(child.get("alias") or child.get("name") or child.get("id") or "")
        child_path = f"{parent_path}/{label}" if label else parent_path
        normalized = normalize_element(child, child_path, depth)
        child_type = str(normalized.get("type") or "")
        include = report_types is None or child_type in report_types or normalized["has_child"]
        if include:
            entries.append(normalized)
        if normalized["has_child"] and depth < max_depth:
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            child_entries, child_errors = walk_catalog(
                client,
                required_element_id(child),
                child_path,
                max_depth=max_depth,
                report_types=report_types,
                delay_seconds=delay_seconds,
                depth=depth + 1,
            )
            entries.extend(child_entries)
            errors.extend(child_errors)
    return entries, errors


def load_profiles(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"profile file must be an object: {path}")
    return data


def profile_report_rows(profiles: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, report in (profiles.get("reports") or {}).items():
        if not isinstance(report, dict):
            continue
        identity = report.get("identity") or {}
        name = str(identity.get("name") or key)
        parts = [str(part) for part in identity.get("path") or [] if part]
        if parts and parts[0] == "益智业务线":
            path = "分析报表/平台业务线/" + "/".join(parts)
        else:
            path = "分析报表/" + "/".join(parts)
        rows.append({"name": name, "path": path})
    return rows


def build_join_summary(registry_reports: list[dict[str, Any]], profiles: dict[str, Any] | None) -> dict[str, Any]:
    if profiles is None:
        return {"status": "not_requested"}

    by_path = {str(item.get("path")): item for item in registry_reports if item.get("id") and item.get("path")}
    by_alias: dict[str, list[dict[str, Any]]] = {}
    for item in registry_reports:
        alias = str(item.get("alias") or "")
        if alias:
            by_alias.setdefault(alias, []).append(item)

    matched_by_path = 0
    matched_by_alias = 0
    unmatched: list[dict[str, str]] = []
    ambiguous: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []

    for profile in profile_report_rows(profiles):
        registry_item = by_path.get(profile["path"])
        match_type = "path"
        if registry_item is None:
            candidates = by_alias.get(profile["name"], [])
            if len(candidates) == 1:
                registry_item = candidates[0]
                match_type = "alias"
            elif len(candidates) > 1:
                ambiguous.append({"profile": profile, "candidate_count": len(candidates)})
        if registry_item is None:
            unmatched.append(profile)
            continue
        if match_type == "path":
            matched_by_path += 1
        else:
            matched_by_alias += 1
        if len(examples) < 12:
            examples.append(
                {
                    "profile_name": profile["name"],
                    "profile_path": profile["path"],
                    "report_id": registry_item.get("id"),
                    "registry_type": registry_item.get("type"),
                    "match_type": match_type,
                }
            )

    total = len(profile_report_rows(profiles))
    matched_total = matched_by_path + matched_by_alias
    return {
        "status": "ok",
        "profiles_total": total,
        "matched_total": matched_total,
        "matched_by_path": matched_by_path,
        "matched_by_alias": matched_by_alias,
        "unmatched_total": len(unmatched),
        "ambiguous_total": len(ambiguous),
        "match_rate": round(matched_total / total, 4) if total else 0,
        "examples": examples,
        "unmatched_examples": unmatched[:30],
        "ambiguous_examples": ambiguous[:20],
    }


def build_registry(args: argparse.Namespace) -> dict[str, Any]:
    client = login_client(args.username, args.password)
    root_paths = args.root_path or DEFAULT_ROOT_PATHS
    report_types = set(args.report_type or []) if args.report_type else None
    entries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    resolved_roots: list[dict[str, Any]] = []
    for root_path in root_paths:
        root_id, resolved, resolved_path = resolve_catalog_path(client, root_path)
        resolved_roots.append({"requested_path": root_path, "resolved_path": resolved_path, "resolved": resolved})
        root_entries, root_errors = walk_catalog(
            client,
            root_id,
            resolved_path,
            max_depth=args.max_depth,
            report_types=report_types,
            delay_seconds=args.delay_seconds,
        )
        entries.extend(root_entries)
        errors.extend(root_errors)
    reports_by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        report_id = str(entry.get("id") or "")
        if entry.get("type") in {"DEFAULT_TREENODE", ""} or not report_id:
            continue
        reports_by_id.setdefault(report_id, entry)
    reports = list(reports_by_id.values())
    type_counts = Counter(str(item.get("type") or "unknown") for item in reports)
    profile_data = load_profiles(args.profiles) if args.profiles else None
    generated_at = dt.datetime.now().isoformat(timespec="seconds")
    return {
        "schema_version": "smartbi-report-id-registry-v1",
        "generated_at": generated_at,
        "source": {
            "root_paths": root_paths,
            "resolved_roots": resolved_roots,
            "max_depth": args.max_depth,
            "report_types": sorted(report_types) if report_types else "all_catalog_resource_types",
            "mode": "catalog_only_no_export",
        },
        "summary": {
            "catalog_entries": len(entries),
            "reports": len(reports),
            "type_counts": dict(sorted(type_counts.items())),
            "errors": len(errors),
        },
        "reports": reports,
        "errors": errors,
        "profile_join": build_join_summary(reports, profile_data),
    }


def default_output_path(root_paths: list[str]) -> Path:
    slug_source = root_paths[0] if len(root_paths) == 1 else "multi_root"
    slug = "".join(ch if ch.isalnum() else "_" for ch in slug_source).strip("_")
    today = dt.date.today().isoformat().replace("-", "")
    return DEFAULT_OUT_DIR / f"smartbi_report_id_registry_{slug}_{today}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a read-only SmartBI report_id registry from catalog metadata.")
    parser.add_argument(
        "--root-path",
        action="append",
        help="Catalog root to scan. Repeatable. Defaults to overseas live and domestic math/teaching roots.",
    )
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--report-type", action="append", help="Limit included resource type. Repeatable.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES, help="Optional profile JSON to join for match summary.")
    parser.add_argument("--out", type=Path, help="Output JSON path.")
    parser.add_argument("--delay-seconds", type=float, default=0.15, help="Small serial delay between child catalog calls.")
    parser.add_argument("--username", default=os.environ.get("SMARTBI_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("SMARTBI_PASSWORD"))
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.username or not args.password:
        print("SMARTBI_USERNAME/SMARTBI_PASSWORD or --username/--password is required", file=sys.stderr)
        return 2
    try:
        registry = build_registry(args)
        out_path = (args.out or default_output_path(args.root_path or DEFAULT_ROOT_PATHS)).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {
            "status": "ok",
            "output": str(out_path),
            "summary": registry["summary"],
            "profile_join": registry["profile_join"],
        }
    except Exception as error:
        result = {"status": "error", "error": str(error)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"registry build failed: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Registry written: {result['output']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        print(json.dumps(result["profile_join"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
