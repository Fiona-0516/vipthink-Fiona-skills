import argparse
import csv
import io
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd


ZIP_PATH = None
STUDENT_PATH = None
OUTPUT_DIR = None
XLSX_OUT = None
REPORT_OUT = None


RULES = [
    {
        "rule": "进群信息核对",
        "category": "首课前",
        "standard": "进群后核对学员名称、上课时间、阶段、语种/地区、ID等信息。",
        "keywords": ["上課時間", "上课时间", "階段", "阶段", "學員", "学员", "ID", "寶貝", "宝贝"],
        "min_hits": 2,
        "default_missing": "待复核",
    },
    {
        "rule": "自我介绍",
        "category": "首课前",
        "standard": "首课前发送自我介绍话术、老师手账/卡片、个人视频。",
        "keywords": ["自我介紹", "自我介绍", "主講老師", "主讲老师", "我是", "老師", "介绍影片", "介紹影片", "個人視頻", "个人视频", "卡片", "手帳", "手账"],
        "min_hits": 2,
        "default_missing": "问题",
    },
    {
        "rule": "首视频邀约",
        "category": "首课前",
        "standard": "首课前72小时内，分两天邀约两次视频/视讯沟通。",
        "keywords": ["視訊", "视讯", "視頻通話", "视频通话", "視頻會議", "视频会议", "Quickmeeting", "視訊嗎", "视频吗"],
        "min_hits": 1,
        "distinct_dates_required": 2,
        "default_missing": "问题",
    },
    {
        "rule": "操作指引",
        "category": "首课前",
        "standard": "发送上课指引图、专题探索说明、小老师完成指南、上课操作指引视频。",
        "keywords": ["上課指引", "上课指引", "操作指引", "專題探索", "专题探索", "小老師完成指南", "小老师完成指南", "課前和課後功課", "课前和课后功课"],
        "min_hits": 1,
        "default_missing": "待复核",
    },
    {
        "rule": "课程预告",
        "category": "正课课前",
        "standard": "每节课上课前24小时内发送课程预告。",
        "keywords": ["課程預告", "课程预告", "主題：", "主题：", "學習內容", "学习内容", "預熱", "预热", "別忘記完成課前", "别忘记完成课前"],
        "min_hits": 1,
        "default_missing": "问题",
    },
    {
        "rule": "课后总结",
        "category": "正课课后",
        "standard": "每节课后12小时内发送文字总结、语音反馈及截图/文件。",
        "keywords": ["課後總結", "课后总结", "本節課", "本节课", "核心本領", "核心本领", "課堂表現", "课堂表现", "語音", "语音"],
        "min_hits": 1,
        "default_missing": "问题",
    },
    {
        "rule": "课后三部曲提醒",
        "category": "正课课后",
        "standard": "课后168小时内提醒课后练习、小老师视频、预习下一堂。",
        "keywords": ["課後三部曲", "课后三部曲", "課後練習", "课后练习", "小老師視頻", "小老师视频", "預習下一堂", "预习下一堂", "完成練習", "完成练习"],
        "min_hits": 1,
        "default_missing": "待复核",
    },
    {
        "rule": "续费回访邀约",
        "category": "续费SOP",
        "standard": "倒数第五节课后至倒数第四节课前，先邀约语音电话；未回应再做语音/文字反馈。",
        "keywords": ["語音回訪", "语音回访", "回訪電話", "回访电话", "學習情況", "学习情况", "卡點", "卡点", "專題學習已經有一段時間", "专题学习已经有一段时间", "續費", "续费"],
        "min_hits": 1,
        "default_missing": "待复核",
    },
    {
        "rule": "结课寄语",
        "category": "续费SOP",
        "standard": "最后一节课上完后72小时内发送结课寄语。",
        "keywords": ["結課寄語", "结课寄语", "結束我們的豌豆課程", "结束我们的豌豆课程", "恭喜你", "冒險圓滿", "冒险圆满", "等你回來", "等你回来"],
        "min_hits": 1,
        "default_missing": "待复核",
    },
    {
        "rule": "换师自我介绍",
        "category": "换师/新师",
        "standard": "新孩子或换老师后，首课前72小时内发送新老师自我介绍。",
        "keywords": ["新老師", "新老师", "換老師", "换老师", "換師", "换师", "我是寶貝的新老師", "我是宝贝的新老师"],
        "min_hits": 1,
        "default_missing": "待复核",
    },
]


def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_digits(value):
    text = clean_text(value)
    if text.endswith(".0"):
        text = text[:-2]
    return re.sub(r"\D", "", text)


def read_students():
    df = pd.read_excel(STUDENT_PATH, dtype=str)
    for col in df.columns:
        df[col] = df[col].map(clean_text)
    df["学员ID_norm"] = df["学员ID"].map(normalize_digits)
    df["老师ID_norm"] = df["老师ID"].map(normalize_digits)
    return df


def parse_csv_file(zf, name):
    text = zf.read(name).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    messages = []
    for row in rows[4:]:
        if len(row) < 5:
            continue
        sender_type, sender_name, date_s, time_s, content = row[:5]
        dt = None
        try:
            dt = datetime.strptime(f"{date_s} {time_s}", "%Y/%m/%d %H:%M:%S")
        except Exception:
            pass
        messages.append(
            {
                "sender_type": sender_type,
                "sender_name": sender_name,
                "date": date_s,
                "time": time_s,
                "dt": dt,
                "content": content or "",
            }
        )
    return rows[:4], messages


def first_evidence(matches, limit=3):
    snippets = []
    for m in matches[:limit]:
        content = re.sub(r"\s+", " ", m["content"]).strip()
        if len(content) > 160:
            content = content[:157] + "..."
        snippets.append(f"{m['date']} {m['time']}｜{m['sender_name']}｜{content}")
    return "\n".join(snippets)


def context_snippets(messages, limit=3):
    snippets = []
    for msg in messages[:limit]:
        content = re.sub(r"\s+", " ", msg["content"]).strip()
        if not content:
            continue
        if len(content) > 140:
            content = content[:137] + "..."
        snippets.append(f"{msg['date']} {msg['time']}｜{msg['sender_name']}｜{content}")
    return "\n".join(snippets)


def match_student(name, full_text, students, id_map, name_map):
    filename_digits = set(re.findall(r"\d{6,}", name))
    text_digits = set(re.findall(r"\d{6,}", full_text[:3000]))

    id_candidates = []
    for d in filename_digits | text_digits:
        if d in id_map:
            id_candidates.extend(id_map[d])
    if id_candidates:
        return id_candidates[0], "学员ID匹配"

    filename_lower = name.lower()
    text_head = full_text[:5000].lower()
    name_candidates = []
    for student_name, idxs in name_map.items():
        if not student_name:
            continue
        if student_name.lower() in filename_lower or student_name.lower() in text_head:
            name_candidates.extend(idxs)
    if name_candidates:
        return name_candidates[0], "学员姓名匹配"

    # Some LINE filenames include teacher names; use this only for a weak match if unique.
    teacher_hits = []
    for idx, row in students.iterrows():
        teacher = row.get("老师名称", "")
        stage = row.get("阶段", "")
        if teacher and teacher.lower() in filename_lower:
            if not stage or stage.lower() in filename_lower:
                teacher_hits.append(idx)
    if len(set(teacher_hits)) == 1:
        return teacher_hits[0], "老师+阶段弱匹配"

    return None, "未匹配：文件名/聊天内容未识别到学员ID或姓名"


def evaluate_rule(rule, teacher_messages):
    keywords = rule["keywords"]
    matches = []
    for msg in teacher_messages:
        content = msg["content"]
        if any(k in content for k in keywords):
            matches.append(msg)

    hit_count = len(matches)
    distinct_dates = len({m["date"] for m in matches if m["date"]})

    if hit_count >= rule.get("min_hits", 1):
        if rule.get("distinct_dates_required") and distinct_dates < rule["distinct_dates_required"]:
            return "待复核", hit_count, distinct_dates, first_evidence(matches), "有视频邀约痕迹，但未达到分两天两次的自动判定条件"
        return "合格", hit_count, distinct_dates, first_evidence(matches), ""

    return rule["default_missing"], 0, 0, "", "未找到明确关键词或等价表达"


def make_outputs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    students = read_students()
    id_map = defaultdict(list)
    name_map = defaultdict(list)
    for idx, row in students.iterrows():
        sid = row["学员ID_norm"]
        if sid:
            id_map[sid].append(idx)
        sname = row.get("学员姓名", "")
        if sname:
            name_map[sname].append(idx)

    detail_rows = []
    evidence_rows = []
    rule_hit_rows = []
    review_rows = []
    unmatched_rows = []
    rule_totals = {r["rule"]: Counter() for r in RULES}
    rule_examples = {r["rule"]: [] for r in RULES}

    total_messages = 0
    teacher_messages_total = 0
    parsed_files = 0

    with zipfile.ZipFile(ZIP_PATH) as zf:
        for filename in zf.namelist():
            parsed_files += 1
            _, messages = parse_csv_file(zf, filename)
            total_messages += len(messages)
            teacher_messages = [m for m in messages if m["sender_type"] == "Account"]
            user_messages = [m for m in messages if m["sender_type"] == "User"]
            teacher_messages_total += len(teacher_messages)
            context = context_snippets(teacher_messages, limit=3)
            full_text = "\n".join(m["content"] for m in messages)
            start_dt = min([m["dt"] for m in messages if m["dt"]] or [None])
            end_dt = max([m["dt"] for m in messages if m["dt"]] or [None])

            match_idx, match_method = match_student(filename, full_text, students, id_map, name_map)
            if match_idx is not None:
                student = students.loc[match_idx]
            else:
                student = pd.Series(dtype=str)
                unmatched_rows.append(
                    {
                        "文件名": filename,
                        "原因": match_method,
                        "消息数": len(messages),
                        "老师侧消息数": len(teacher_messages),
                        "首条时间": start_dt,
                        "末条时间": end_dt,
                    }
                )

            row = {
                "文件名": filename,
                "匹配状态": "已匹配" if match_idx is not None else "未匹配",
                "匹配方式": match_method,
                "学员ID": student.get("学员ID", ""),
                "学员姓名": student.get("学员姓名", ""),
                "老师ID": student.get("老师ID", ""),
                "老师名称": student.get("老师名称", ""),
                "阶段": student.get("阶段", ""),
                "课类": student.get("课类", ""),
                "班级语种": student.get("班级语种", ""),
                "学员是否新签": student.get("学员是否新签", ""),
                "剩余课时数": student.get("学员当前使用的课包剩余课时数", ""),
                "下节课上课时间": student.get("下节课上课时间", ""),
                "消息数": len(messages),
                "老师侧消息数": len(teacher_messages),
                "家长侧消息数": len(user_messages),
                "首条时间": start_dt,
                "末条时间": end_dt,
            }

            problem_count = 0
            review_count = 0
            pass_count = 0
            for rule in RULES:
                status, hits, distinct_dates, evidence, note = evaluate_rule(rule, teacher_messages)
                rule_name = rule["rule"]
                row[rule_name] = status
                row[f"{rule_name}命中数"] = hits
                rule_totals[rule_name][status] += 1
                if evidence and len(rule_examples[rule_name]) < 5:
                    rule_examples[rule_name].append(evidence.split("\n")[0])
                if status == "合格":
                    pass_count += 1
                elif status == "问题":
                    problem_count += 1
                else:
                    review_count += 1

                if hits:
                    rule_hit_rows.append(
                        {
                            "文件名": filename,
                            "学员ID": student.get("学员ID", ""),
                            "学员姓名": student.get("学员姓名", ""),
                            "老师名称": student.get("老师名称", ""),
                            "规则": rule_name,
                            "状态": status,
                            "命中数": hits,
                            "不同日期数": distinct_dates,
                            "证据": evidence,
                        }
                    )

                if status in {"问题", "待复核"}:
                    issue = {
                        "文件名": filename,
                        "匹配状态": row["匹配状态"],
                        "学员ID": student.get("学员ID", ""),
                        "学员姓名": student.get("学员姓名", ""),
                        "老师ID": student.get("老师ID", ""),
                        "老师名称": student.get("老师名称", ""),
                        "阶段": student.get("阶段", ""),
                        "规则": rule_name,
                        "状态": status,
                        "原因": note,
                        "证据": evidence,
                        "会话样例": context,
                    }
                    if status == "问题":
                        evidence_rows.append(issue)
                    else:
                        review_rows.append(issue)

            row["合格项数"] = pass_count
            row["问题项数"] = problem_count
            row["待复核项数"] = review_count
            detail_rows.append(row)

    detail_df = pd.DataFrame(detail_rows)
    evidence_df = pd.DataFrame(evidence_rows)
    rule_hits_df = pd.DataFrame(rule_hit_rows)
    review_df = pd.DataFrame(review_rows)
    unmatched_df = pd.DataFrame(unmatched_rows)

    matched_df = detail_df[detail_df["匹配状态"] == "已匹配"].copy()
    teacher_summary = (
        matched_df.groupby(["老师ID", "老师名称"], dropna=False)
        .agg(
            负责会话数=("文件名", "count"),
            涉及学员数=("学员ID", "nunique"),
            消息数=("消息数", "sum"),
            老师侧消息数=("老师侧消息数", "sum"),
            合格项数=("合格项数", "sum"),
            问题项数=("问题项数", "sum"),
            待复核项数=("待复核项数", "sum"),
        )
        .reset_index()
    )
    teacher_summary["问题项占比"] = (
        teacher_summary["问题项数"] / (teacher_summary["合格项数"] + teacher_summary["问题项数"] + teacher_summary["待复核项数"])
    ).round(4)
    teacher_summary = teacher_summary.sort_values(["问题项数", "待复核项数"], ascending=False)

    rule_summary_rows = []
    for rule in RULES:
        c = rule_totals[rule["rule"]]
        rule_summary_rows.append(
            {
                "规则": rule["rule"],
                "类别": rule["category"],
                "标准": rule["standard"],
                "合格": c["合格"],
                "问题": c["问题"],
                "待复核": c["待复核"],
                "样例": "\n".join(rule_examples[rule["rule"]][:3]),
            }
        )
    rule_summary = pd.DataFrame(rule_summary_rows)

    overview = pd.DataFrame(
        [
            ["CSV文件数", parsed_files],
            ["消息总数", total_messages],
            ["老师侧消息数", teacher_messages_total],
            ["学员明细人数", len(students)],
            ["已匹配会话数", int((detail_df["匹配状态"] == "已匹配").sum())],
            ["未匹配会话数", int((detail_df["匹配状态"] == "未匹配").sum())],
            ["问题证据条数", len(evidence_df)],
            ["待复核条数", len(review_df)],
            ["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ],
        columns=["指标", "数值"],
    )

    dimension_rows = []
    for dim in ["阶段", "课类", "班级语种", "学员是否新签"]:
        if dim in matched_df.columns:
            grouped = matched_df.groupby(dim, dropna=False).agg(
                会话数=("文件名", "count"),
                合格项数=("合格项数", "sum"),
                问题项数=("问题项数", "sum"),
                待复核项数=("待复核项数", "sum"),
            )
            for key, vals in grouped.reset_index().iterrows():
                dimension_rows.append({"维度": dim, "取值": vals[dim], **vals.drop(dim).to_dict()})
    dimensions_df = pd.DataFrame(dimension_rows)

    with pd.ExcelWriter(XLSX_OUT, engine="openpyxl") as writer:
        overview.to_excel(writer, sheet_name="总览", index=False)
        teacher_summary.to_excel(writer, sheet_name="教师汇总", index=False)
        detail_df.to_excel(writer, sheet_name="学员会话明细", index=False)
        evidence_df.to_excel(writer, sheet_name="问题证据", index=False)
        rule_summary.to_excel(writer, sheet_name="规则命中", index=False)
        rule_hits_df.to_excel(writer, sheet_name="规则命中明细", index=False)
        review_df.to_excel(writer, sheet_name="待复核", index=False)
        unmatched_df.to_excel(writer, sheet_name="未匹配清单", index=False)
        dimensions_df.to_excel(writer, sheet_name="维度分析", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col_cells in ws.columns:
                max_len = 0
                col_letter = col_cells[0].column_letter
                for cell in col_cells[:200]:
                    val = "" if cell.value is None else str(cell.value)
                    max_len = max(max_len, min(len(val), 60))
                ws.column_dimensions[col_letter].width = max(10, min(max_len + 2, 48))

    write_report(overview, teacher_summary, rule_summary, detail_df, evidence_df, review_df, unmatched_df, dimensions_df)


def pct(num, den):
    if not den:
        return "0.0%"
    return f"{num / den:.1%}"


def write_report(overview, teacher_summary, rule_summary, detail_df, evidence_df, review_df, unmatched_df, dimensions_df):
    metrics = dict(zip(overview["指标"], overview["数值"]))
    total_rules = len(detail_df) * len(RULES)
    total_pass = int(detail_df["合格项数"].sum())
    total_problem = int(detail_df["问题项数"].sum())
    total_review = int(detail_df["待复核项数"].sum())
    top_rules = rule_summary.sort_values("问题", ascending=False).head(5)
    top_teachers = teacher_summary.head(10)

    lines = []
    lines.append("# 台湾教师团队教学服务质检总结")
    lines.append("")
    lines.append(f"生成时间：{metrics.get('生成时间')}")
    lines.append("")
    lines.append("## 一、整体结论")
    lines.append("")
    lines.append(
        f"本次共读取 {metrics.get('CSV文件数')} 个 LINE 会话、{metrics.get('消息总数')} 条消息，其中老师侧消息 {metrics.get('老师侧消息数')} 条。"
        f"学员明细共 {metrics.get('学员明细人数')} 人，自动匹配会话 {metrics.get('已匹配会话数')} 个，未匹配会话 {metrics.get('未匹配会话数')} 个。"
    )
    lines.append(
        f"按 {len(RULES)} 个 SOP 项进行会话级检查，共形成 {total_rules} 个判断点：合格 {total_pass} 项（{pct(total_pass, total_rules)}），"
        f"问题 {total_problem} 项（{pct(total_problem, total_rules)}），待复核 {total_review} 项（{pct(total_review, total_rules)}）。"
    )
    lines.append("")
    lines.append("## 二、主要问题")
    lines.append("")
    for _, row in top_rules.iterrows():
        lines.append(f"- {row['规则']}：问题 {int(row['问题'])} 个，待复核 {int(row['待复核'])} 个。")
    lines.append("")
    lines.append("## 三、教师维度关注名单")
    lines.append("")
    for _, row in top_teachers.iterrows():
        lines.append(
            f"- {row['老师名称']}（{row['老师ID']}）：会话 {int(row['负责会话数'])} 个，"
            f"问题项 {int(row['问题项数'])}，待复核 {int(row['待复核项数'])}。"
        )
    lines.append("")
    lines.append("## 四、典型证据")
    lines.append("")
    sample = evidence_df.head(12)
    if sample.empty:
        lines.append("本次自动扫描未形成明确问题证据。")
    else:
        for _, row in sample.iterrows():
            evidence = str(row.get("证据", "")).replace("\n", " / ")
            if len(evidence) > 220:
                evidence = evidence[:217] + "..."
            lines.append(
                f"- {row.get('规则')}｜{row.get('老师名称')}｜{row.get('学员姓名')}｜{row.get('原因')}"
                + (f"｜证据：{evidence}" if evidence else "")
            )
    lines.append("")
    lines.append("## 五、整改建议")
    lines.append("")
    lines.append("- 对课程预告、课后总结等高频必做 SOP，建议建立固定模板和发送后自查机制。")
    lines.append("- 对首视频邀约，建议记录两次邀约日期，确保满足“分两天两次”的要求。")
    lines.append("- 对待复核项，优先复核有物料痕迹但文本不明确的会话，例如“照片已传送”“影片已传送”“檔案已傳送”。")
    lines.append("- 对未匹配会话，建议补充学员 ID 或家长昵称映射后再纳入教师维度绩效。")
    lines.append("")
    lines.append("## 六、口径说明")
    lines.append("")
    lines.append("本报告使用关键词与上下文证据做自动质检；涉及课前/课后精确时效、图片/视频内容、历史换师归属等无法稳定自动判断的项目，统一列为待复核。")

    REPORT_OUT.write_text("\n".join(lines), encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Generate LINE Taiwan service quality audit workbook and summary.")
    parser.add_argument("--line-zip", required=True, help="Path to LINE OA chat CSV zip export.")
    parser.add_argument("--student-xlsx", required=True, help="Path to student-teacher matching workbook.")
    parser.add_argument("--output-dir", required=True, help="Directory for output workbook and report.")
    parser.add_argument("--prefix", default="台湾教师团队教学服务质检", help="Output filename prefix.")
    return parser.parse_args()


def configure_paths(args):
    global ZIP_PATH, STUDENT_PATH, OUTPUT_DIR, XLSX_OUT, REPORT_OUT
    ZIP_PATH = Path(args.line_zip).expanduser().resolve()
    STUDENT_PATH = Path(args.student_xlsx).expanduser().resolve()
    OUTPUT_DIR = Path(args.output_dir).expanduser().resolve()
    XLSX_OUT = OUTPUT_DIR / f"{args.prefix}结果.xlsx"
    REPORT_OUT = OUTPUT_DIR / f"{args.prefix}总结.md"


if __name__ == "__main__":
    args = parse_args()
    configure_paths(args)
    make_outputs()
    print(f"Workbook: {XLSX_OUT}")
    print(f"Report: {REPORT_OUT}")
