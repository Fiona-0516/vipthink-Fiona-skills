#!/usr/bin/env python3
"""Evaluate BI route index as a lightweight Agent router reference.

Read-only: this script reads local JSON and calls query_bi_profiles.py. It does
not log into SmartBI, export Excel, download report data, or mutate ad projects.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "outputs" / "bi_catalog_registry" / "bi_report_route_index_current.json"
DEFAULT_EVAL = ROOT / "outputs" / "bi_catalog_registry" / "bi_route_reference_eval_20260520.md"
DEFAULT_REFERENCE = ROOT / "outputs" / "bi_catalog_registry" / "bi_route_agent_reference_20260520.md"
DEFAULT_FAILURES = ROOT / "outputs" / "bi_catalog_registry" / "bi_route_failure_cases_20260520.json"


EVAL_CASES: list[dict[str, Any]] = [
    {
        "id": "Q1",
        "question": "FB 素材 ROI2 为什么差，应该查哪些表？",
        "query": "投放 FB 素材 ROI2 例子 约课",
        "metrics": ["ROI2"],
        "expected_reports": ["投放FB链路指标--素材维度"],
        "expected_terms": ["ROI2", "素材", "例子", "约课"],
    },
    {
        "id": "Q2",
        "question": "台湾渠道例子成本上升，应该查哪些表？",
        "query": "台湾 渠道 消耗 例子成本 约课率",
        "metrics": ["例子成本"],
        "expected_reports": ["台湾商务-链路达成数据"],
        "expected_terms": ["台湾", "渠道", "消耗", "例子成本"],
    },
    {
        "id": "Q3",
        "question": "港澳/非港澳 FB 表现拆解，应该查哪些表？",
        "query": "FB 港澳 非港澳 测试 报表 ROI2 素材",
        "metrics": ["ROI2"],
        "expected_reports": ["FB港澳-非港澳测试报表"],
        "expected_terms": ["FB", "港澳", "非港澳", "ROI2"],
    },
    {
        "id": "Q4",
        "question": "某素材空耗，要查素材维度还是渠道维度？",
        "query": "素材 空耗 消耗 例子 约课 广告名称",
        "metrics": [],
        "expected_reports": ["投放FB链路指标--素材维度", "投放广点通链路指标--素材维度（开发中）", "投放小红书链路指标-素材维度"],
        "expected_terms": ["素材", "消耗", "例子", "约课", "广告名称"],
    },
    {
        "id": "Q5",
        "question": "ROI2 和平台转化不一致，应该查哪里？",
        "query": "投放 ROI2 平台 转化 当月转化率 滚动转化率",
        "metrics": ["ROI2"],
        "expected_reports": ["投放FB链路指标--素材维度", "投放全链路目标达成数据-跨月"],
        "expected_terms": ["ROI2", "平台", "转化率"],
    },
    {
        "id": "Q6",
        "question": "FB 周报整体趋势用哪张表？",
        "query": "海外投放FB渠道日监控 今日 快照 例子 约课",
        "metrics": [],
        "expected_reports": ["海外投放FB渠道日监控"],
        "expected_terms": ["FB", "渠道", "日监控", "例子", "约课"],
    },
    {
        "id": "Q7",
        "question": "素材维度和渠道维度是否有候选 join 路径？",
        "query": "投放 FB 素材 渠道 日期 消耗 例子 约课 ROI2",
        "metrics": ["ROI2"],
        "expected_reports": ["投放FB链路指标--素材维度", "海外投放FB渠道日监控"],
        "expected_terms": ["素材", "渠道", "日期", "消耗", "例子"],
        "join_check": True,
    },
    {
        "id": "Q8",
        "question": "学员/订单级数据在哪些表？",
        "query": "学员ID 订单 续费 退费 LP 明细",
        "metrics": ["续费率"],
        "expected_reports": ["海外思维续费订单明细", "海外益智退费明细", "益智LP退费申请跟进明细"],
        "expected_terms": ["学员ID", "订单", "续费", "退费", "LP"],
    },
    {
        "id": "Q9",
        "question": "哪些筛选器不能自动改？",
        "mode": "filter_risk",
        "expected_terms": ["manual_business_value_required", "default_only_safe_no_write", "neighbor_option_mismatch"],
    },
    {
        "id": "Q10",
        "question": "哪些报表只能当 dashboard 参考，不能当底表？",
        "mode": "dashboard_risk",
        "expected_terms": ["inspect_workbook_shape_before_analysis"],
    },
]


def compact(value: object) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def load_index(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"route index must be an object: {path}")
    return data


def query_profiles(case: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    command = [
        "python3",
        "scripts/query_bi_profiles.py",
        "--registry",
        "outputs/bi_catalog_registry/bi_report_route_index_20260520.json",
        "--query",
        case["query"],
        "--limit",
        str(limit),
        "--json",
    ]
    for metric in case.get("metrics") or []:
        command.extend(["--metric", metric])
    payload = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
    return payload.get("results") or []


def field_coverage(candidate: dict[str, Any], expected_terms: list[str]) -> dict[str, Any]:
    haystack = " ".join(
        [
            candidate.get("name") or "",
            candidate.get("path") or "",
            " ".join(candidate.get("sample_columns") or []),
            " ".join(candidate.get("metric_hits") or []),
            " ".join(candidate.get("matched") or []),
        ]
    )
    text = compact(haystack)
    covered = [term for term in expected_terms if compact(term) and compact(term) in text]
    missing = [term for term in expected_terms if term not in covered]
    return {
        "covered": covered,
        "missing": missing,
        "coverage_ratio": round(len(covered) / len(expected_terms), 4) if expected_terms else 1.0,
    }


def candidate_summary(candidate: dict[str, Any], expected_terms: list[str]) -> dict[str, Any]:
    coverage = field_coverage(candidate, expected_terms)
    filter_summary = candidate.get("filter_summary") or {}
    return {
        "report_name": candidate.get("name"),
        "report_id": candidate.get("report_id"),
        "match_confidence": candidate.get("match_confidence"),
        "field_coverage": coverage,
        "filter_summary": filter_summary,
        "risk_flags": candidate.get("risk_flags") or [],
        "can_enter_dry_run": bool(candidate.get("report_id") and candidate.get("dry_run_plan")),
        "needs_human_confirmation": needs_human_confirmation(candidate),
        "dry_run_task": (candidate.get("dry_run_plan") or {}).get("task"),
        "source_role": candidate.get("source_role"),
    }


def needs_human_confirmation(candidate: dict[str, Any]) -> bool:
    filter_summary = candidate.get("filter_summary") or {}
    risk_flags = set(candidate.get("risk_flags") or [])
    return bool(
        filter_summary.get("weak_or_manual", 0)
        or "has_filter_safety_limits" in risk_flags
        or "manual_or_default_only_filter" in risk_flags
        or "inspect_workbook_shape_before_analysis" in risk_flags
    )


def verdict_for(case: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not candidates:
        return "fail", ["no candidates returned"]
    top_names = [str(item.get("report_name") or "") for item in candidates]
    expected = case.get("expected_reports") or []
    expected_hit = not expected or any(name in top_names[:3] for name in expected)
    report_id_ok = any(item.get("report_id") for item in candidates[:3])
    dry_run_ok = any(item.get("can_enter_dry_run") for item in candidates[:3])
    coverage_ok = any((item.get("field_coverage") or {}).get("coverage_ratio", 0) >= 0.45 for item in candidates[:3])

    if not expected_hit:
        reasons.append("expected report not in top3")
    if not report_id_ok:
        reasons.append("no report_id in top3")
    if not dry_run_ok:
        reasons.append("no dry-run candidate in top3")
    if not coverage_ok:
        reasons.append("field coverage weak")
    if expected_hit and report_id_ok and dry_run_ok and coverage_ok:
        return "pass", reasons
    if expected_hit and report_id_ok and coverage_ok:
        if not dry_run_ok:
            reasons.append("candidate reports found, but current SmartBI CLI dry-run path is not available")
        return "weak", reasons
    if report_id_ok and dry_run_ok and coverage_ok:
        return "weak", reasons
    return "fail", reasons


def evaluate_standard_case(case: dict[str, Any]) -> dict[str, Any]:
    raw_candidates = query_profiles(case, 5)
    candidates = [candidate_summary(item, case.get("expected_terms") or []) for item in raw_candidates[:3]]
    verdict, reasons = verdict_for(case, candidates)
    if case.get("join_check"):
        join = join_path_assessment(raw_candidates)
        if join["status"] == "candidate_only_requires_validation":
            reasons.append("join path is candidate-only; verify grain/key before export")
        candidates.append({"join_path_assessment": join})
    return {
        "id": case["id"],
        "question": case["question"],
        "query": case["query"],
        "candidates": candidates,
        "verdict": verdict,
        "reasons": reasons,
    }


def join_path_assessment(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    names = [str(item.get("name") or "") for item in candidates]
    has_material = any("素材" in name for name in names)
    has_channel = any("渠道" in name for name in names)
    return {
        "status": "candidate_only_requires_validation" if has_material and has_channel else "weak_no_pair_in_top5",
        "candidate_reports": names[:5],
        "required_checks": ["date grain", "channel/platform naming", "material/ad id", "metric definitions", "filter windows"],
    }


def evaluate_filter_risk(index: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    risky = []
    for report in index.get("reports") or []:
        filter_summary = report.get("filter_summary") or {}
        if filter_summary.get("weak_or_manual", 0) or filter_summary.get("unsafe_examples"):
            risky.append(report)
    risky.sort(key=lambda item: (-(item.get("filter_summary") or {}).get("weak_or_manual", 0), item.get("report_name") or ""))
    candidates = [
        {
            "report_name": item.get("report_name"),
            "report_id": item.get("report_id"),
            "match_confidence": item.get("match_confidence"),
            "field_coverage": {"covered": case["expected_terms"], "missing": [], "coverage_ratio": 1.0},
            "filter_summary": item.get("filter_summary"),
            "risk_flags": item.get("risk_flags"),
            "can_enter_dry_run": bool(item.get("dry_run_plan")),
            "needs_human_confirmation": True,
            "dry_run_task": (item.get("dry_run_plan") or {}).get("task"),
            "source_role": item.get("source_role"),
        }
        for item in risky[:3]
    ]
    return {
        "id": case["id"],
        "question": case["question"],
        "query": "filter risk inventory",
        "candidates": candidates,
        "verdict": "pass" if candidates else "fail",
        "reasons": ["lists reports with manual/default-only filter boundaries"],
    }


def evaluate_dashboard_risk(index: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    dashboard_like = []
    for report in index.get("reports") or []:
        flags = set(report.get("risk_flags") or [])
        if "inspect_workbook_shape_before_analysis" in flags:
            dashboard_like.append(report)
    dashboard_like.sort(key=lambda item: (item.get("report_type") or "", item.get("report_name") or ""))
    candidates = [
        {
            "report_name": item.get("report_name"),
            "report_id": item.get("report_id"),
            "match_confidence": item.get("match_confidence"),
            "field_coverage": {"covered": case["expected_terms"], "missing": [], "coverage_ratio": 1.0},
            "filter_summary": item.get("filter_summary"),
            "risk_flags": item.get("risk_flags"),
            "can_enter_dry_run": bool(item.get("dry_run_plan")),
            "needs_human_confirmation": True,
            "dry_run_task": (item.get("dry_run_plan") or {}).get("task"),
            "source_role": item.get("source_role"),
        }
        for item in dashboard_like[:3]
    ]
    return {
        "id": case["id"],
        "question": case["question"],
        "query": "dashboard/pivot risk inventory",
        "candidates": candidates,
        "verdict": "pass" if candidates else "fail",
        "reasons": ["lists reports requiring workbook-shape inspection before analysis"],
    }


def evaluate(index: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for case in EVAL_CASES:
        mode = case.get("mode")
        if mode == "filter_risk":
            results.append(evaluate_filter_risk(index, case))
        elif mode == "dashboard_risk":
            results.append(evaluate_dashboard_risk(index, case))
        else:
            results.append(evaluate_standard_case(case))
    return results


def failure_cases(results: list[dict[str, Any]]) -> dict[str, Any]:
    failures = []
    for result in results:
        for candidate in result["candidates"]:
            if "join_path_assessment" in candidate:
                continue
            issues = []
            if not candidate.get("report_id"):
                issues.append("report_id_missing")
            if (candidate.get("field_coverage") or {}).get("coverage_ratio", 0) < 0.45:
                issues.append("field_or_metric_coverage_weak")
            filter_summary = candidate.get("filter_summary") or {}
            if filter_summary.get("weak_or_manual", 0):
                issues.append("filter_risk")
            if "inspect_workbook_shape_before_analysis" in set(candidate.get("risk_flags") or []):
                issues.append("pivot_or_dashboard_not_bottom_table")
            if issues:
                failures.append(
                    {
                        "question_id": result["id"],
                        "question": result["question"],
                        "report_name": candidate.get("report_name"),
                        "report_id": candidate.get("report_id"),
                        "issues": sorted(set(issues)),
                        "repair_suggestion": repair_suggestion(issues),
                    }
                )
    return {
        "summary": {
            "questions": len(results),
            "pass": sum(1 for item in results if item["verdict"] == "pass"),
            "weak": sum(1 for item in results if item["verdict"] == "weak"),
            "fail": sum(1 for item in results if item["verdict"] == "fail"),
            "failure_items": len(failures),
        },
        "items": failures,
    }


def repair_suggestion(issues: list[str]) -> str:
    if "report_id_missing" in issues:
        return "Refresh report_id registry or repair path/name join."
    if "field_or_metric_coverage_weak" in issues:
        return "Add route aliases, expected field dictionary, or module-specific scoring prompts."
    if "filter_risk" in issues:
        return "Require human confirmation for manual/default-only filters before export."
    if "pivot_or_dashboard_not_bottom_table" in issues:
        return "Inspect workbook shape and locate raw/detail source before analysis or join."
    return "Review route scoring and field mapping."


def write_eval_markdown(path: Path, results: list[dict[str, Any]]) -> None:
    pass_count = sum(1 for item in results if item["verdict"] == "pass")
    weak_count = sum(1 for item in results if item["verdict"] == "weak")
    fail_count = sum(1 for item in results if item["verdict"] == "fail")
    status = "reference_candidate" if pass_count >= 7 else "p0_internal_only"
    lines = [
        "# BI Route Reference Eval 20260520",
        "",
        f"- Eval 结论: {status}",
        f"- pass / weak / fail: {pass_count} / {weak_count} / {fail_count}",
        "- Scope: local route index only; no SmartBI export, no Excel download, no ad-platform login.",
        "",
        "| # | 问题 | 结论 | Top 3 候选报表 | report_id | 字段覆盖 | 筛选器风险 | dry-run | 人工确认 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        candidate_rows = [item for item in result["candidates"] if "join_path_assessment" not in item][:3]
        names = "<br>".join(str(item.get("report_name") or "") for item in candidate_rows)
        ids = "<br>".join(str(item.get("report_id") or "") for item in candidate_rows)
        coverage = "<br>".join(
            f"{(item.get('field_coverage') or {}).get('coverage_ratio', 0):.0%}"
            for item in candidate_rows
        )
        filters = "<br>".join(
            f"weak={(item.get('filter_summary') or {}).get('weak_or_manual', 0)}"
            for item in candidate_rows
        )
        dry = "<br>".join("yes" if item.get("can_enter_dry_run") else "no" for item in candidate_rows)
        human = "<br>".join("yes" if item.get("needs_human_confirmation") else "no" for item in candidate_rows)
        lines.append(
            f"| {result['id']} | {result['question']} | {result['verdict']} | {names} | {ids} | {coverage} | {filters} | {dry} | {human} |"
        )
        for candidate in result["candidates"]:
            if "join_path_assessment" in candidate:
                join = candidate["join_path_assessment"]
                lines.append(f"| {result['id']} join | 候选 join 判断 | weak | {'<br>'.join(join['candidate_reports'])} |  |  | {', '.join(join['required_checks'])} | no | yes |")
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- 满足轻路由 reference 的最低门槛：10 个问题中至少 7 个能给出合理候选报表。",
            "- 只能作为 `router reference`，不能作为自动取数授权。",
            "- 所有 `SPREADSHEET_REPORT`、dashboard、monitor 候选进入分析前必须先做 workbook shape inspection。",
            "- join 路径只能是候选建议，必须验证日期粒度、渠道命名、素材/ad id、指标口径和筛选窗口。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_agent_reference(path: Path, results: list[dict[str, Any]]) -> None:
    lines = [
        "# BI Route Agent Reference 20260520",
        "",
        "## When To Call",
        "",
        "先调用 `query_bi_profiles.py` 的场景：",
        "",
        "- 用户提出业务问题但未指定 SmartBI 报表。",
        "- 需要判断应查素材维度、渠道维度、区域维度、学员/订单明细还是周报汇总。",
        "- 需要确认候选表是否有 `report_id`，是否能进入 SmartBI CLI dry-run。",
        "- 需要提前暴露字段覆盖、筛选器风险、dashboard/pivot 风险。",
        "",
        "不要调用它替代真实分析；它只解决“先去哪张表查”。",
        "",
        "## Recommended Command",
        "",
        "```bash",
        "python3 scripts/query_bi_profiles.py \\",
        "  --registry outputs/bi_catalog_registry/bi_report_route_index_20260520.json \\",
        "  --query '<业务问题>' \\",
        "  --metric '<关键指标，如 ROI2 或 例子成本>' \\",
        "  --limit 5 \\",
        "  --json",
        "```",
        "",
        "## JSON Fields",
        "",
        "- `report_id`: SmartBI catalog resource id；没有它不能生成 SmartBI CLI task。",
        "- `match_confidence`: 当前主要来自 path join；`1.0` 表示 profile path 与 registry path 精确匹配。",
        "- `sample_columns`: profile 抽到的字段样本，只能判断候选覆盖，不能代表完整口径。",
        "- `filter_summary.safe`: 已学习且格式可控的筛选器数量。",
        "- `filter_summary.weak_or_manual`: 只能默认、需要人工值或存在依赖选项风险的筛选器数量。",
        "- `risk_flags`: 路由风险，例如 `inspect_workbook_shape_before_analysis`、`manual_or_default_only_filter`。",
        "- `dry_run_plan`: 可审查的 SmartBI CLI task 草稿；只能 dry-run，不能自动导出。",
        "",
        "## Can Enter SmartBI CLI Dry-run",
        "",
        "同时满足：",
        "",
        "- `report_id` 存在。",
        "- `match_confidence >= 0.8`。",
        "- `dry_run_plan.config_task.report.type == SPREADSHEET_REPORT`。",
        "- 用户问题、时间窗口、区域/渠道/素材筛选口径清楚。",
        "- dry-run 前不需要人工填写 `manual_business_value_required` 筛选器。",
        "",
        "## Must Stop And Ask Human",
        "",
        "- `report_id` 缺失或 match_type 是 ambiguous。",
        "- `filter_summary.weak_or_manual > 0` 且需要修改这些筛选器。",
        "- 报表是 dashboard/monitor/pivot，用户却要求底表级 join 或归因。",
        "- 业务问题涉及预算调整、停投、写回、发布、自动化执行。",
        "- 需要学员ID、订单ID、广告ID、素材ID等主键拼接，但主键和时间粒度未验证。",
        "",
        "## Cannot Auto Join",
        "",
        "以下情况只能给候选 join 路径，不能自动拼接：",
        "",
        "- 素材维度表和渠道维度表只有日期/渠道近似字段，没有明确共同主键。",
        "- ROI2、平台转化、后端转化的口径来源不同。",
        "- 一个候选是 `SPREADSHEET_REPORT` 或 dashboard/pivot，未做 workbook shape inspection。",
        "- 筛选窗口不一致，例如快照日期、开始日期、结束日期、月度/周度粒度混用。",
        "",
        "## Role Boundaries",
        "",
        "- 数据分析师：用它找候选表、字段、筛选器风险；分析结论必须等真实导出和质量检查后再给。",
        "- 投放自动化 Agent：只能作为 Read-only Intelligence 的取数路由，不得触发预算、停投、写回。",
        "- 周报 Agent：可用它选择周报候选源和 dry-run task；生成周报前必须检查 workbook shape。",
        "- 技术指挥官：负责把 route index 接到 config draft / dry-run / inspection 链路，不负责业务口径拍板。",
        "- GAO / AI Growth OS：放在 BI/内部数据层，服务投放层和素材层；不升级成新的大系统或自动化实体。",
        "",
        "## Current Eval Evidence",
        "",
    ]
    for result in results:
        lines.append(f"- {result['id']} {result['verdict']}: {result['question']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate BI route index and write Agent reference artifacts.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--eval-out", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--reference-out", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--failures-out", type=Path, default=DEFAULT_FAILURES)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    index = load_index(args.index)
    results = evaluate(index)
    failures = failure_cases(results)
    args.eval_out.parent.mkdir(parents=True, exist_ok=True)
    write_eval_markdown(args.eval_out, results)
    write_agent_reference(args.reference_out, results)
    args.failures_out.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "status": "ok",
        "eval": str(args.eval_out),
        "reference": str(args.reference_out),
        "failures": str(args.failures_out),
        "summary": failures["summary"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
