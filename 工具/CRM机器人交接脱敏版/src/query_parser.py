"""
查班指令解析器

架构：正则优先，语义兜底
- 第一层：正则精准匹配标准格式
- 第二层：语义分析提取关键词组合

支持的输入格式：
1. 普通话S5 16:00之后
2. S5 普通话 1600之后查班
3. 周一周三周四 16:50或17:40 周日9点10点 粤语S2查班
4. 粤语S2 工作日晚上
5. 英语S3 周一到周四 19:20
6. 普通话S5 19:20 20:10 18:30 17:40查班
7. 奥力老师查班
"""

import re
from typing import List, Dict, Optional, Tuple
from crm_query import parse_time_range


# ==================== 常量 ====================

COURSE_NAMES = ["英语", "英文", "粤语", "台湾", "普通话", "国语", "中英", "豌豆明思"]
COURSE_ALIASES = {"英文": "英语", "国语": "普通话", "广东话": "粤语", "双语": "中英", "明思": "豌豆明思"}
TIME_PERIODS = ["晚上", "下午", "上午", "早上", "中午", "夜间"]
WEEKDAY_NAMES = ["周[一二三四五六日天]", "工作日", "周末"]


# ==================== 预处理 ====================

def preprocess(text: str) -> str:
    """统一格式：去标点、转时间、转语种别名"""
    t = text.strip()
    
    # 去掉@教务小助手
    t = re.sub(r'@教务小助手', '', t).strip()
    
    # 阶段小写转大写
    for i in range(1, 8):
        t = t.replace(f's{i}', f'S{i}')
    
    # 语种别名
    t = t.replace('国语', '普通话').replace('广东话', '粤语')
    t = t.replace('英文', '英语').replace('台灣', '台湾').replace('台灣', '台湾')
    t = t.replace('英語', '英语').replace('粵語', '粤语')
    t = t.replace('週', '周').replace('双语', '中英')
    t = t.replace('明思', '豌豆明思').replace('豌豆豌豆明思', '豌豆明思')
    
    # 去掉"查班/找班"
    t = re.sub(r'查班|找班', '', t).strip()
    
    # 标点统一
    t = re.sub(r'[，、；,;]', ' ', t)
    t = t.replace('：', ':')  # 中文冒号→英文
    
    # 时间格式统一：1600→16:00, 830→8:30
    t = re.sub(r'(?<!\d)(\d{1,2})(\d{2})(?=(之后|以后|后|之前|以前|前|或|\s|$))',
               lambda m: f'{int(m.group(1))}:{m.group(2)}', t)
    # "X点半" → "X:30", "X点YY" → "X:YY", "X点" → "X:00"
    t = re.sub(r'(\d)点半', r'\1:30', t)
    t = re.sub(r'(\d)点(\d{1,2})(?!\d)', lambda m: f'{int(m.group(1))}:{int(m.group(2)):02d}', t)
    t = re.sub(r'(\d)点(?!\d)', r'\1:00', t)
    
    # 统一空格
    t = re.sub(r'\s+', ' ', t).strip()
    
    return t


def normalize_course_stage(text: str) -> Tuple[str, str]:
    """提取并统一语种+阶段的位置，返回 (标准化后的text, course, stage)
    
    处理：语种S阶段 或 S阶段语种 → 统一为 "语种S阶段 剩余部分"
    """
    course = ""
    stage = ""
    prefix = ""
    
    # 模式1：语种+S阶段 在末尾（如 "周一周三16:50 S2粤语"）
    m = re.search(r'S(\d+)\s*(' + '|'.join(COURSE_NAMES) + r')\s*$', text)
    if m:
        stage = f'S{m.group(1)}'
        course = m.group(2)
        prefix = text[:m.start()].strip()
        return f'{course}{stage} {prefix}'.strip(), course, stage
    
    # 模式2：S阶段+语种 在开头（如 "S5普通话 16:00之后"）
    m = re.match(r'^(S?\d+)\s*(' + '|'.join(COURSE_NAMES) + r')(.*)$', text)
    if m:
        s = m.group(1).upper()
        if not s.startswith('S'):
            s = f'S{s}'
        stage = s
        course = m.group(2)
        rest = m.group(3).strip()
        return f'{course}{stage} {rest}'.strip(), course, stage
    
    # 模式3：语种+S阶段 在开头或中间（如 "普通话S5 16:00之后"）
    m = re.search(r'(' + '|'.join(COURSE_NAMES) + r')\s*(S\d+)', text)
    if m:
        course = m.group(1)
        stage = m.group(2)
        # 确保语种和阶段间无多余空格
        text = re.sub(r'(' + '|'.join(COURSE_NAMES) + r')\s+(S\d+)', r'\1\2', text)
        return text, course, stage
    
    return text, course, stage


# ==================== 第一层：正则精准匹配 ====================

def extract_rest(text: str, course: str, stage: str) -> str:
    """从标准化文本中提取语种+阶段之后的部分"""
    # 去掉 "语种S阶段" 部分
    pattern = re.escape(course) + r'\s*' + re.escape(stage)
    rest = re.sub(pattern, '', text, count=1).strip()
    return rest


def parse_weekday_time_groups(rest: str) -> List[Dict]:
    """解析星期+时间组合
    
    返回: [{"weekday": "周一周三周四", "times": ["16:50","17:40"], "period": ""}, ...]
    """
    if not rest:
        return []
    
    # 统一"或者"→"或"
    r = rest.replace('或者', '或').replace('或是', '或')
    
    # 策略：用正则匹配 (连续星期词 + 后续时间) 对
    # 时间部分可以是：数字时间、时间段关键词、或"之后/以前"等方向词
    pattern = r'((?:周[一二三四五六日天])+|工作日|周末)\s*([\d:或\s点半]*(?:以后|之后|后|以前|之前|前)?(?:晚上|下午|上午|早上|中午|夜间)?|[\d:或\s点半]+(?:以后|之后|后|以前|之前|前)?|晚上|下午|上午|早上|中午|夜间)'
    matches = re.findall(pattern, r)
    
    groups = []
    if matches:
        for wd, time_part in matches:
            times = _extract_times_from_segment(time_part)
            period = _extract_period(time_part)
            groups.append({"weekday": wd, "times": times, "period": period})
    else:
        # 没有星期词，纯时间/时间段
        if '或' in r:
            alternatives = re.split(r'\s*或\s*', r)
        else:
            alternatives = [r]
        
        for alt in alternatives:
            alt = alt.strip()
            if not alt:
                continue
            alt_times = re.findall(r'(\d{1,2}:\d{2})', alt)
            alt_period = _extract_period(alt)
            if alt_times or alt_period:
                groups.append({"weekday": "", "times": alt_times, "period": alt_period})
    
    # 如果没有匹配到任何星期词+时间组，尝试纯时间提取
    if not groups and r:
        all_times = re.findall(r'(\d{1,2}:\d{2})', r)
        period = _extract_period(r)
        if all_times or period:
            groups.append({"weekday": "", "times": all_times, "period": period})
    
    # 处理"周一到周五"周期范围（findall会拆成"周一"和"周五"两组，需要合并）
    groups = _merge_weekday_ranges(groups, r)
    
    return groups


def _extract_times_from_segment(seg: str) -> List[str]:
    """从文本段中提取所有时间点"""
    return re.findall(r'(\d{1,2}:\d{2})', seg)


def _extract_period(seg: str) -> str:
    """从文本段中提取时间段关键词"""
    for p in TIME_PERIODS:
        if p in seg:
            return p
    return ""


def _merge_weekday_ranges(groups: List[Dict], original: str) -> List[Dict]:
    """合并'周一到周五'类周期范围
    
    findall会把'周一到周五'拆成'周一'和'周五'两组，需要合并
    """
    if len(groups) < 2:
        return groups
    
    # 检查原文是否包含"周X到/至/-周Y"模式
    range_match = re.search(r'(周[一二三四五六日天])\s*(?:到|至|-|~)\s*(周[一二三四五六日天])', original)
    if not range_match:
        return groups
    
    range_str = f"{range_match.group(1)}到{range_match.group(2)}"
    
    # 找到包含这两个星期词的相邻组，合并
    merged = []
    i = 0
    while i < len(groups):
        if i < len(groups) - 1:
            g1 = groups[i]
            g2 = groups[i + 1]
            # 检查这两个组是否是范围的两端
            if (range_match.group(1) in g1["weekday"] and 
                range_match.group(2) in g2["weekday"] and
                g1["weekday"].replace(range_match.group(1), '') == ''):
                # 合并
                merged.append({
                    "weekday": range_str,
                    "times": g1["times"] or g2["times"],
                    "period": g1["period"] or g2["period"]
                })
                i += 2
                continue
        merged.append(groups[i])
        i += 1
    
    return merged


# ==================== 语义兜底 ====================

def semantic_parse(text: str) -> Optional[Dict]:
    """语义分析：从自由文本中提取关键词组合
    
    当正则精准匹配失败时使用，尽力提取语种、阶段、星期、时间
    """
    result = {"course": "", "stage": "", "filters": [], "raw": text}
    
    # 提取语种
    for name in COURSE_NAMES:
        if name in text:
            result["course"] = name
            break
    
    # 提取阶段
    m = re.search(r'S(\d)', text)
    if m:
        result["stage"] = f'S{m.group(1)}'
    
    # 如果连语种和阶段都没有，放弃
    if not result["course"] and not result["stage"]:
        return None
    
    # 提取星期+时间组合
    rest = text
    if result["course"]:
        rest = rest.replace(result["course"], '')
    if result["stage"]:
        rest = rest.replace(result["stage"], '')
    rest = re.sub(r'查班|找班', '', rest).strip()
    
    groups = parse_weekday_time_groups(rest)
    result["filters"] = groups
    
    return result


# ==================== 主入口 ====================

def parse_query(text: str) -> Dict:
    """解析查班指令，返回结构化结果
    
    Returns:
        {
            "course": str,           # 语种（如"粤语"）
            "stage": str,            # 阶段（如"S2"）
            "filters": [             # 筛选条件组（多组之间是OR关系）
                {
                    "weekday": str,  # 星期（如"周一周三周四"，空=不限）
                    "times": [str],  # 时间点（如["16:50","17:40"]，空=不限）
                    "period": str,   # 时间段（如"晚上"，空=不限）
                }
            ],
            "teacher": str,          # 老师名（空=不指定）
            "time_range_desc": str,  # 时间范围描述（用于单组场景的兼容）
            "weekday_filter": str,   # 星期描述（用于单组场景的兼容）
            "is_multi_group": bool,  # 是否多组条件
        }
    """
    # 预处理
    cleaned = preprocess(text)
    
    # 标准化语种+阶段
    normalized, course, stage = normalize_course_stage(cleaned)
    
    # 提取剩余部分
    rest = extract_rest(normalized, course, stage) if course and stage else ""
    
    # 提取老师名字
    teacher = ""
    teacher_match = re.search(r'([\u4e00-\u9fff]+(?:老师|老師)|[a-zA-Z]+(?:\s+[a-zA-Z]+)*(?:老师|老師)?(?:\([\u4e00-\u9fff]+\))?)', rest)
    if teacher_match:
        # 排除语种词误匹配
        name = teacher_match.group(1)
        if name not in COURSE_NAMES and name not in TIME_PERIODS:
            teacher = name
            rest = rest.replace(teacher, '').strip()
    
    # 解析星期+时间
    filters = parse_weekday_time_groups(rest)
    
    # 单组条件的兼容字段
    time_range_desc = ""
    weekday_filter = ""
    is_multi = len(filters) > 1
    
    if not is_multi and filters:
        f = filters[0]
        weekday_filter = f["weekday"]
        if f["period"]:
            time_range_desc = f["period"]
        elif f["times"]:
            # 检查是否有"之后/以后"等
            if '之后' in rest or '以后' in rest or '后' in rest:
                time_range_desc = f["times"][0] + "之后"
            elif '之前' in rest or '以前' in rest:
                time_range_desc = f["times"][0] + "之前"
            # 多时间点只取第一个作为精确匹配
            # （兼容旧的time_filter逻辑）
    
    # 合并：如果多组filter都只有weekday没有times和period，说明用户想的是"这些天上课的班"
    # 比如"周一 周三"被拆成两组，应该合并成一组 weekday="周一周三"
    if len(filters) > 1:
        all_weekday_only = all(
            f.get("weekday") and not f.get("times") and not f.get("period")
            for f in filters
        )
        if all_weekday_only:
            merged_weekday = "".join(f["weekday"] for f in filters)
            filters = [{"weekday": merged_weekday, "times": [], "period": ""}]
            is_multi = False
            weekday_filter = merged_weekday
    
    # 如果正则解析失败，尝试语义兜底
    if not course and not stage and not teacher:
        sem_result = semantic_parse(cleaned)
        if sem_result:
            course = sem_result["course"]
            stage = sem_result["stage"]
            filters = sem_result["filters"]
    
    return {
        "course": course,
        "stage": stage,
        "filters": filters,
        "teacher": teacher,
        "time_range_desc": time_range_desc,
        "weekday_filter": weekday_filter,
        "is_multi_group": is_multi,
    }


# ==================== 测试 ====================

if __name__ == "__main__":
    tests = [
        "周一周三周四 1650或者17点40周日9点10点查班s2粤语查班",
        "周一周三周四 16:50或17:40 周日9:00 10:00 粤语S2",
        "S5 普通话 16:00之后查班",
        "S5 普通话 1600之后查班",
        "S5 普通话 16：00之后查班",
        "普通话S5 周一到周五 19点20查班",
        "粤语S2 9点半或者10点查班",
        "周一周三 19:20或20:10 粤语S2",
        "工作日16:50或17:40 周末9:00 普通话S3查班",
        "普通话S5 19:20 20:10 18:30 17:40查班",
        "粤语S2 晚上",
        "英语S3 工作日晚上",
        "奥力老师查班",
        "S2粤语 周一到周四晚上",
    ]
    
    for t in tests:
        r = parse_query(t)
        print(f"输入: {t}")
        print(f"  语种={r['course']} 阶段={r['stage']} 老师={r['teacher'] or '无'}")
        if r['filters']:
            for i, f in enumerate(r['filters']):
                wd = f['weekday'] or '不限星期'
                ts = '/'.join(f['times']) if f['times'] else ''
                p = f['period'] or ''
                print(f"  条件{i+1}: {wd} {ts} {p}".strip())
        else:
            print(f"  (无条件筛选)")
        print()
