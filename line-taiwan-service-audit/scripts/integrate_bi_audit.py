import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd


OLD_XLSX = None
BI_CSV = None
OUT_XLSX = None
OUT_REPORT = None


RULES = [
    "进群信息核对",
    "自我介绍",
    "首视频邀约",
    "操作指引",
    "课程预告",
    "课后总结",
    "课后三部曲提醒",
    "续费回访邀约",
    "结课寄语",
    "换师自我介绍",
]


def norm_id(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return "".join(ch for ch in text if ch.isdigit())


def status_counts(series):
    c = Counter(series.fillna("").astype(str))
    return {k: int(v) for k, v in c.items() if k}


def any_done(df, cols):
    for col in cols:
        if col in df.columns and (df[col].fillna("") == "完成").any():
            return True
    return False


def any_not_done(df, cols):
    for col in cols:
        if col in df.columns and (df[col].fillna("") == "未完成").any():
            return True
    return False


def all_not_done(df, cols):
    vals = []
    for col in cols:
        if col in df.columns:
            vals.extend(df[col].dropna().astype(str).tolist())
    return bool(vals) and all(v == "未完成" for v in vals)


def summarize_bi_for_student(bi_rows):
    if bi_rows.empty:
        return {}
    return {
        "BI课次行数": len(bi_rows),
        "BI上课日期范围": f"{bi_rows['上课日期'].min()} ~ {bi_rows['上课日期'].max()}",
        "BI主讲": "、".join(sorted(set(bi_rows["主讲昵称"].dropna().astype(str))))[:120],
        "BI课程预告": status_counts(bi_rows["课程预告"]),
        "BI课后文字总结": status_counts(bi_rows["课后_文字总结"]),
        "BI课后截图": status_counts(bi_rows["课后_截图"]),
        "BI课后语音反馈": status_counts(bi_rows["课后_语音反馈"]),
        "BI课后三部曲": status_counts(bi_rows["课后_三部曲"]),
        "BI是否首课": status_counts(bi_rows["是否首课"]),
        "BI是否0课时任务": status_counts(bi_rows["是否0课时任务学员"]),
        "BI0课时结课回访": status_counts(bi_rows["0课时结课回访"]),
        "BI是否4课时任务": status_counts(bi_rows["是否4课时任务学员"]),
        "BI4课时语音回访": status_counts(bi_rows["4课时语音回访"]),
        "BI4课时文字回访": status_counts(bi_rows["4课时文字回访"]),
    }


def judge_with_bi(rule, original, bi_rows):
    if bi_rows.empty:
        return original, "无BI匹配课次", ""

    note = ""
    basis = ""
    new_status = original

    if rule == "课程预告":
        basis = str(status_counts(bi_rows["课程预告"]))
        if any_done(bi_rows, ["课程预告"]):
            new_status = "合格"
            note = "BI显示课程预告存在完成记录"
        elif all_not_done(bi_rows, ["课程预告"]) and original != "合格":
            new_status = "问题"
            note = "BI显示匹配课次课程预告均未完成"

    elif rule == "课后总结":
        basis = str(
            {
                "文字总结": status_counts(bi_rows["课后_文字总结"]),
                "截图": status_counts(bi_rows["课后_截图"]),
                "语音反馈": status_counts(bi_rows["课后_语音反馈"]),
            }
        )
        if any_done(bi_rows, ["课后_文字总结"]):
            new_status = "合格"
            note = "BI显示课后文字总结存在完成记录"
        elif all_not_done(bi_rows, ["课后_文字总结"]) and original != "合格":
            new_status = "问题"
            note = "BI显示匹配课次课后文字总结均未完成"

    elif rule == "课后三部曲提醒":
        basis = str(status_counts(bi_rows["课后_三部曲"]))
        if any_done(bi_rows, ["课后_三部曲"]):
            new_status = "合格"
            note = "BI显示课后三部曲存在完成记录"
        elif all_not_done(bi_rows, ["课后_三部曲"]) and original != "合格":
            new_status = "问题"
            note = "BI显示匹配课次课后三部曲均未完成"

    elif rule == "续费回访邀约":
        task_rows = bi_rows[bi_rows["是否4课时任务学员"].fillna("") == "是"]
        basis = str(
            {
                "是否4课时任务": status_counts(bi_rows["是否4课时任务学员"]),
                "4课时语音回访": status_counts(task_rows["4课时语音回访"]) if not task_rows.empty else {},
                "4课时文字回访": status_counts(task_rows["4课时文字回访"]) if not task_rows.empty else {},
            }
        )
        if task_rows.empty:
            new_status = "不适用"
            note = "BI显示非4课时任务学员"
        elif any_done(task_rows, ["4课时语音回访", "4课时文字回访"]):
            new_status = "合格"
            note = "BI显示4课时回访存在完成记录"
        elif any_not_done(task_rows, ["4课时语音回访", "4课时文字回访"]) and original != "合格":
            new_status = "问题"
            note = "BI显示4课时任务回访未完成"

    elif rule == "结课寄语":
        task_rows = bi_rows[bi_rows["是否0课时任务学员"].fillna("") == "是"]
        basis = str(
            {
                "是否0课时任务": status_counts(bi_rows["是否0课时任务学员"]),
                "0课时结课回访": status_counts(task_rows["0课时结课回访"]) if not task_rows.empty else {},
            }
        )
        if task_rows.empty:
            new_status = "不适用"
            note = "BI显示非0课时任务学员"
        elif any_done(task_rows, ["0课时结课回访"]):
            new_status = "合格"
            note = "BI显示0课时结课回访完成"
        elif any_not_done(task_rows, ["0课时结课回访"]) and original != "合格":
            new_status = "问题"
            note = "BI显示0课时任务结课回访未完成"

    elif rule == "自我介绍":
        assessed = bi_rows[bi_rows["首课自我介绍"].notna()]
        basis = str(
            {
                "是否首课": status_counts(bi_rows["是否首课"]),
                "首课自我介绍": status_counts(bi_rows["首课自我介绍"].fillna("<空>")),
            }
        )
        if not assessed.empty:
            if any_done(assessed, ["首课自我介绍"]):
                new_status = "合格"
                note = "BI显示首课自我介绍完成"
            elif any_not_done(assessed, ["首课自我介绍"]) and original != "合格":
                new_status = "问题"
                note = "BI显示首课自我介绍未完成"

    elif rule == "首视频邀约":
        assessed = bi_rows[bi_rows["首视邀约"].notna() | bi_rows["首视"].notna()]
        basis = str(
            {
                "是否首课": status_counts(bi_rows["是否首课"]),
                "首视邀约": status_counts(bi_rows["首视邀约"].fillna("<空>")),
                "首视": status_counts(bi_rows["首视"].fillna("<空>")),
            }
        )
        if not assessed.empty:
            if any_done(assessed, ["首视邀约", "首视"]):
                new_status = "合格"
                note = "BI显示首视邀约/首视完成"
            elif any_not_done(assessed, ["首视邀约", "首视"]) and original != "合格":
                new_status = "问题"
                note = "BI显示首视邀约/首视未完成"

    return new_status, note, basis


def main():
    detail = pd.read_excel(OLD_XLSX, sheet_name="学员会话明细")
    old_review = pd.read_excel(OLD_XLSX, sheet_name="待复核")
    old_problem = pd.read_excel(OLD_XLSX, sheet_name="问题证据")
    bi = pd.read_csv(BI_CSV, encoding="gb18030")

    detail["学员ID_norm"] = detail["学员ID"].map(norm_id)
    detail["老师ID_norm"] = detail["老师ID"].map(norm_id)
    bi["用户id_norm"] = bi["用户id"].map(norm_id)
    bi["主讲id_norm"] = bi["主讲id"].map(norm_id)

    bi_groups = {uid: g.copy() for uid, g in bi.groupby("用户id_norm")}

    integrated = detail.copy()
    changes = []
    bi_summary_rows = []

    for idx, row in integrated.iterrows():
        uid = row["学员ID_norm"]
        tid = row["老师ID_norm"]
        bi_rows = bi_groups.get(uid, pd.DataFrame(columns=bi.columns))
        if not bi_rows.empty and tid and (bi_rows["主讲id_norm"] == tid).any():
            bi_rows = bi_rows[bi_rows["主讲id_norm"] == tid].copy()

        summary = summarize_bi_for_student(bi_rows)
        if summary:
            bi_summary_rows.append(
                {
                    "文件名": row["文件名"],
                    "学员ID": row["学员ID"],
                    "学员姓名": row["学员姓名"],
                    "老师ID": row["老师ID"],
                    "老师名称": row["老师名称"],
                    **summary,
                }
            )

        for rule in RULES:
            old = row[rule]
            new, note, basis = judge_with_bi(rule, old, bi_rows)
            integrated.at[idx, f"{rule}_BI整合"] = new
            if new != old:
                changes.append(
                    {
                        "文件名": row["文件名"],
                        "学员ID": row["学员ID"],
                        "学员姓名": row["学员姓名"],
                        "老师ID": row["老师ID"],
                        "老师名称": row["老师名称"],
                        "规则": rule,
                        "原状态": old,
                        "BI整合后状态": new,
                        "变更说明": note,
                        "BI依据": basis,
                    }
                )

    integrated["BI整合合格项数"] = integrated[[f"{r}_BI整合" for r in RULES]].eq("合格").sum(axis=1)
    integrated["BI整合问题项数"] = integrated[[f"{r}_BI整合" for r in RULES]].eq("问题").sum(axis=1)
    integrated["BI整合待复核项数"] = integrated[[f"{r}_BI整合" for r in RULES]].eq("待复核").sum(axis=1)
    integrated["BI整合不适用项数"] = integrated[[f"{r}_BI整合" for r in RULES]].eq("不适用").sum(axis=1)

    changes_df = pd.DataFrame(changes)
    bi_summary = pd.DataFrame(bi_summary_rows)

    rule_rows = []
    for rule in RULES:
        old_counts = detail[rule].value_counts().to_dict()
        new_counts = integrated[f"{rule}_BI整合"].value_counts().to_dict()
        rule_rows.append(
            {
                "规则": rule,
                "原合格": old_counts.get("合格", 0),
                "原问题": old_counts.get("问题", 0),
                "原待复核": old_counts.get("待复核", 0),
                "BI后合格": new_counts.get("合格", 0),
                "BI后问题": new_counts.get("问题", 0),
                "BI后待复核": new_counts.get("待复核", 0),
                "BI后不适用": new_counts.get("不适用", 0),
                "待复核减少": old_counts.get("待复核", 0) - new_counts.get("待复核", 0),
            }
        )
    rule_compare = pd.DataFrame(rule_rows)

    matched_bi_conversations = int(integrated["学员ID_norm"].isin(set(bi["用户id_norm"])).sum())
    overview = pd.DataFrame(
        [
            ["原待复核条数", int(detail[RULES].eq("待复核").sum().sum())],
            ["BI整合后待复核条数", int(integrated[[f"{r}_BI整合" for r in RULES]].eq("待复核").sum().sum())],
            ["待复核减少", int(detail[RULES].eq("待复核").sum().sum() - integrated[[f"{r}_BI整合" for r in RULES]].eq("待复核").sum().sum())],
            ["原问题条数", int(detail[RULES].eq("问题").sum().sum())],
            ["BI整合后问题条数", int(integrated[[f"{r}_BI整合" for r in RULES]].eq("问题").sum().sum())],
            ["BI整合后不适用条数", int(integrated[[f"{r}_BI整合" for r in RULES]].eq("不适用").sum().sum())],
            ["BI明细课次行数", len(bi)],
            ["BI覆盖用户数", bi["用户id_norm"].nunique()],
            ["BI覆盖原会话数", matched_bi_conversations],
            ["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ],
        columns=["指标", "数值"],
    )

    teacher_summary = (
        integrated.groupby(["老师ID", "老师名称"], dropna=False)
        .agg(
            会话数=("文件名", "count"),
            学员数=("学员ID", "nunique"),
            BI合格项数=("BI整合合格项数", "sum"),
            BI问题项数=("BI整合问题项数", "sum"),
            BI待复核项数=("BI整合待复核项数", "sum"),
            BI不适用项数=("BI整合不适用项数", "sum"),
        )
        .reset_index()
        .sort_values(["BI问题项数", "BI待复核项数"], ascending=False)
    )

    # New issue/review sheets under integrated status.
    issue_rows = []
    review_rows = []
    for _, row in integrated.iterrows():
        for rule in RULES:
            status = row[f"{rule}_BI整合"]
            if status in {"问题", "待复核"}:
                item = {
                    "文件名": row["文件名"],
                    "学员ID": row["学员ID"],
                    "学员姓名": row["学员姓名"],
                    "老师ID": row["老师ID"],
                    "老师名称": row["老师名称"],
                    "阶段": row.get("阶段", ""),
                    "规则": rule,
                    "BI整合状态": status,
                    "原状态": row[rule],
                }
                if status == "问题":
                    issue_rows.append(item)
                else:
                    review_rows.append(item)
    issues = pd.DataFrame(issue_rows)
    reviews = pd.DataFrame(review_rows)

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        overview.to_excel(writer, sheet_name="总览_BI整合", index=False)
        rule_compare.to_excel(writer, sheet_name="规则变化", index=False)
        teacher_summary.to_excel(writer, sheet_name="教师汇总_BI整合", index=False)
        integrated.to_excel(writer, sheet_name="会话明细_BI整合", index=False)
        changes_df.to_excel(writer, sheet_name="BI判定变更", index=False)
        issues.to_excel(writer, sheet_name="问题清单_BI整合", index=False)
        reviews.to_excel(writer, sheet_name="待复核_BI整合", index=False)
        bi_summary.to_excel(writer, sheet_name="BI课次汇总", index=False)
        bi.head(5000).to_excel(writer, sheet_name="BI原始样例", index=False)
        old_review.to_excel(writer, sheet_name="原待复核", index=False)
        old_problem.to_excel(writer, sheet_name="原问题证据", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col_cells in ws.columns:
                letter = col_cells[0].column_letter
                max_len = max(min(len(str(c.value or "")), 50) for c in col_cells[:200])
                ws.column_dimensions[letter].width = max(10, min(max_len + 2, 45))

    write_report(overview, rule_compare, teacher_summary)


def write_report(overview, rule_compare, teacher_summary):
    m = dict(zip(overview["指标"], overview["数值"]))
    lines = [
        "# 台湾教师团队教学服务质检总结（BI整合版）",
        "",
        f"生成时间：{m['生成时间']}",
        "",
        "## 一、待复核变化",
        "",
        f"原待复核为 {m['原待复核条数']} 条，整合 BI 课次明细后为 {m['BI整合后待复核条数']} 条，减少 {m['待复核减少']} 条。",
        f"BI 明细覆盖 {m['BI明细课次行数']} 条课次、{m['BI覆盖用户数']} 个用户，覆盖原 LINE 会话 {m['BI覆盖原会话数']} 个。",
        "",
        "## 二、规则变化",
        "",
    ]
    for _, row in rule_compare.sort_values("待复核减少", ascending=False).iterrows():
        lines.append(
            f"- {row['规则']}：待复核 {int(row['原待复核'])} → {int(row['BI后待复核'])}，"
            f"减少 {int(row['待复核减少'])}；BI后问题 {int(row['BI后问题'])}，不适用 {int(row['BI后不适用'])}。"
        )
    lines.extend(["", "## 三、教师维度（按BI整合后问题项排序）", ""])
    for _, row in teacher_summary.head(10).iterrows():
        lines.append(
            f"- {row['老师名称']}（{row['老师ID']}）：问题项 {int(row['BI问题项数'])}，"
            f"待复核 {int(row['BI待复核项数'])}，不适用 {int(row['BI不适用项数'])}。"
        )
    lines.extend(
        [
            "",
            "## 四、口径说明",
            "",
            "- BI 表中直接有“完成/未完成”的项目，优先用于减少待复核。",
            "- 续费回访只在 BI 显示“是否4课时任务学员=是”时判定；否则标为不适用。",
            "- 结课寄语只在 BI 显示“是否0课时任务学员=是”时判定；否则标为不适用。",
            "- 首课自我介绍、首视邀约字段大量为空，空值不硬判，只在 BI 明确给出完成/未完成时改判。",
            "- BI 显示未完成但 LINE 已有明确合格证据的项目，保留 LINE 合格，不用 BI 反向推翻。",
        ]
    )
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Integrate BI SOP detail CSV into a LINE service audit workbook.")
    parser.add_argument("--audit-xlsx", required=True, help="Path to workbook generated by line_quality_audit.py.")
    parser.add_argument("--bi-csv", required=True, help="Path to BI SOP detail CSV, usually GB18030 encoded.")
    parser.add_argument("--output-dir", required=True, help="Directory for integrated output workbook and report.")
    parser.add_argument("--prefix", default="台湾教师团队教学服务质检", help="Output filename prefix.")
    return parser.parse_args()


def configure_paths(args):
    global OLD_XLSX, BI_CSV, OUT_XLSX, OUT_REPORT
    OLD_XLSX = Path(args.audit_xlsx).expanduser().resolve()
    BI_CSV = Path(args.bi_csv).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    OUT_XLSX = output_dir / f"{args.prefix}结果_BI整合版.xlsx"
    OUT_REPORT = output_dir / f"{args.prefix}总结_BI整合版.md"


if __name__ == "__main__":
    args = parse_args()
    configure_paths(args)
    main()
    print(f"Workbook: {OUT_XLSX}")
    print(f"Report: {OUT_REPORT}")
