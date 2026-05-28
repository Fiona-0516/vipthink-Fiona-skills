#!/usr/bin/env python3
"""
CRM 班级查询工具
通过 API 直接查询班级信息，秒级完成
"""

import requests
import json
from typing import List, Dict, Optional

# CRM API 地址
CRM_API_URL = "https://ems.vipthink.cn/gateway/route__jw/api/classs/manage"

# 课程阶段ID映射
COURSE_STAGE_IDS = {
    "豌豆明思2025（英语）": {"S1": 3282, "S2": 3283, "S3": 3284, "S4": 3285, "S5": 3286, "S6": 3287, "S7": 3288},
    "豌豆明思2025（粤语）": {"S1": 3275, "S2": 3276, "S3": 3277, "S4": 3278, "S5": 3279, "S6": 3280, "S7": 3281},
    "豌豆明思2025（台湾）": {"S1": 4074, "S2": 4075, "S3": 4044, "S4": 4076, "S5": 4077, "S6": 4078},
    "豌豆明思2025（中英）": {"S1": 3268, "S2": 3269, "S3": 3270, "S4": 3271, "S5": 3272, "S6": 3273, "S7": 3274},
    "豌豆明思2025": {"S1": 3259, "S2": 3260, "S3": 3261, "S4": 3262, "S5": 3263, "S6": 3264, "S7": 3265, "S8": 3266, "S9": 3267},
}

# 语种ID映射
LANGUAGE_IDS = {
    "普通话": 90,
    "英语": 63,
    "全英": 63,
    "中英": 91,
    "中文": 91,
    "粤语": 69,
}

# 台湾课类覆盖范围：S1-S6，S7起用粤语课类+普通话
# 粤语课类下 S6(cateSid=3280) S7(cateSid=3281) 的普通话班(lanId=90) 实际为台湾班
TAIWAN_OVERRIDE = {
    # 粤语课类中属于台湾的班：{cateSid: (阶段名, lanId)}
    3280: ("S6", 90),  # 粤语S6 + 普通话 = 台湾S6
    3281: ("S7", 90),  # 粤语S7 + 普通话 = 台湾S7
}

# 别名映射（用于兼容旧接口 get_stage_id）
COURSE_ALIASES = {
    "英语": "豌豆明思2025（英语）",
    "英文": "豌豆明思2025（英语）",
    "粤语": "豌豆明思2025（粤语）",
    "台湾": "豌豆明思2025（台湾）",
    "豌豆明思": "豌豆明思2025",
    "正课": "豌豆明思2025",
    "普通话": "豌豆明思2025",
}

# 语种别名标准化
LANGUAGE_ALIASES = {
    "普通话": "普通话",
    "国语": "普通话",
    "英语": "英语",
    "英文": "英语",
    "全英": "英语",
    "粤语": "粤语",
    "广东话": "粤语",
    "台湾": "台湾",
    "台": "台湾",
    "中英": "中英",
    "中文": "中英",
    "双语": "中英",
}


def resolve_class_query(language: str, stage: str) -> Optional[Dict]:
    """统一阶段×语种查询路由
    
    将「语种+阶段」自动路由到正确的 cateSid + lanId 组合。
    
    路由规则:
    - 普通话 → 无后缀课类(catePid=3243) + lanId=90
    - 台湾 S1-S6 → 台湾课类(catePid=4043)，无需lanId筛选
    - 台湾 S7 → 粤语课类S7 + lanId=90
    - 台湾 S8/S9 → 无后缀课类 + lanId=90
    - 英语 → 英语课类(catePid=3202) + lanId=63 (超出S7走无后缀+lanId=63)
    - 粤语 → 粤语课类(catePid=3203) + lanId=69 (超出S7走无后缀+lanId=69)
    - 中英 → 无后缀课类 + lanId=91
    
    Args:
        language: 语种（普通话、英语、粤语、台湾、中英等，支持别名）
        stage: 阶段（S1-S9 或 1-9）
    
    Returns:
        {
            "cate_sid": int,       # 课程阶段ID
            "lan_id": int,         # 语种ID (-1=不限)
            "course_type": str,    # 课类名称（用于显示）
            "language": str,       # 标准化语种名
            "stage": str,          # 标准化阶段名
        }
        或 None（无法匹配时）
    """
    # 标准化阶段名
    if not str(stage).upper().startswith('S'):
        stage = f"S{stage}"
    stage = str(stage).upper()
    
    # 标准化语种名
    language = LANGUAGE_ALIASES.get(language, language)
    
    # ---- 普通话：走无后缀课类 + lanId=90 ----
    if language == "普通话":
        cate_sid = COURSE_STAGE_IDS["豌豆明思2025"].get(stage)
        if cate_sid is None:
            return None
        return {
            "cate_sid": cate_sid,
            "lan_id": LANGUAGE_IDS["普通话"],  # 90
            "course_type": "豌豆明思2025",
            "language": "普通话",
            "stage": stage,
        }
    
    # ---- 台湾：S1-S6走台湾课类，S7走粤语课类+普通话，无S8/S9 ----
    elif language == "台湾":
        if stage in COURSE_STAGE_IDS["豌豆明思2025（台湾）"]:
            # S1-S6: 台湾课类
            cate_sid = COURSE_STAGE_IDS["豌豆明思2025（台湾）"][stage]
            return {
                "cate_sid": cate_sid,
                "lan_id": -1,  # 台湾课类无需lanId筛选
                "course_type": "豌豆明思2025（台湾）",
                "language": "台湾",
                "stage": stage,
                "show_locked": True,  # 台湾展示锁班（不含满班）
            }
        elif stage in COURSE_STAGE_IDS["豌豆明思2025（粤语）"]:
            # S7: 粤语课类 + 普通话
            cate_sid = COURSE_STAGE_IDS["豌豆明思2025（粤语）"][stage]
            return {
                "cate_sid": cate_sid,
                "lan_id": LANGUAGE_IDS["普通话"],  # 90
                "course_type": "豌豆明思2025（粤语）",
                "language": "台湾",
                "stage": stage,
                "show_locked": True,  # 台湾展示锁班（不含满班）
            }
        else:
            return None
    
    # ---- 英语：走英语课类 + lanId=63，超出S7走无后缀 ----
    elif language == "英语":
        if stage in COURSE_STAGE_IDS["豌豆明思2025（英语）"]:
            cate_sid = COURSE_STAGE_IDS["豌豆明思2025（英语）"][stage]
            return {
                "cate_sid": cate_sid,
                "lan_id": LANGUAGE_IDS["英语"],  # 63
                "course_type": "豌豆明思2025（英语）",
                "language": "英语",
                "stage": stage,
            }
        elif stage in COURSE_STAGE_IDS["豌豆明思2025"]:
            # S8/S9: 无后缀课类 + 英语
            cate_sid = COURSE_STAGE_IDS["豌豆明思2025"][stage]
            return {
                "cate_sid": cate_sid,
                "lan_id": LANGUAGE_IDS["英语"],  # 63
                "course_type": "豌豆明思2025",
                "language": "英语",
                "stage": stage,
            }
        else:
            return None
    
    # ---- 粤语：走粤语课类 + lanId=69，超出S7走无后缀 ----
    elif language == "粤语":
        if stage in COURSE_STAGE_IDS["豌豆明思2025（粤语）"]:
            cate_sid = COURSE_STAGE_IDS["豌豆明思2025（粤语）"][stage]
            return {
                "cate_sid": cate_sid,
                "lan_id": LANGUAGE_IDS["粤语"],  # 69
                "course_type": "豌豆明思2025（粤语）",
                "language": "粤语",
                "stage": stage,
            }
        elif stage in COURSE_STAGE_IDS["豌豆明思2025"]:
            # S8/S9: 无后缀课类 + 粤语
            cate_sid = COURSE_STAGE_IDS["豌豆明思2025"][stage]
            return {
                "cate_sid": cate_sid,
                "lan_id": LANGUAGE_IDS["粤语"],  # 69
                "course_type": "豌豆明思2025",
                "language": "粤语",
                "stage": stage,
            }
        else:
            return None
    
    # ---- 中英：需合并3个课类（中英课类+英语课类+无后缀课类） ----
    elif language == "中英":
        cate_sids = []
        # 1. 中英专属课类（S2/S3/S7）
        zhongying_sid = COURSE_STAGE_IDS.get("豌豆明思2025（中英）", {}).get(stage)
        if zhongying_sid is not None:
            cate_sids.append({"cate_sid": zhongying_sid, "course_type": "豌豆明思2025（中英）"})
        # 2. 英语课类中有中英班（S1-S7）
        en_sid = COURSE_STAGE_IDS.get("豌豆明思2025（英语）", {}).get(stage)
        if en_sid is not None:
            cate_sids.append({"cate_sid": en_sid, "course_type": "豌豆明思2025（英语）"})
        # 3. 无后缀课类中也有中英班（S3-S9）
        base_sid = COURSE_STAGE_IDS.get("豌豆明思2025", {}).get(stage)
        if base_sid is not None:
            cate_sids.append({"cate_sid": base_sid, "course_type": "豌豆明思2025"})
        
        if not cate_sids:
            return None
        
        return {
            "cate_sid": cate_sids[0]["cate_sid"],
            "lan_id": LANGUAGE_IDS["中英"],  # 91
            "course_type": "中英",
            "language": "中英",
            "stage": stage,
            "cate_sids": cate_sids,  # 多课类合并查询
        }
    
    return None


def get_stage_id(course_type: str, stage: str) -> Optional[int]:
    """根据课类和阶段获取ID
    
    Args:
        course_type: 课类名称（支持别名）
        stage: 阶段（如 S2 或 2）
    
    Returns:
        阶段ID，未找到返回None
    """
    # 标准化阶段名
    if not stage.upper().startswith('S'):
        stage = f"S{stage}"
    stage = stage.upper()
    
    # 标准化课类名
    if course_type in COURSE_ALIASES:
        course_type = COURSE_ALIASES[course_type]
    
    # 查找ID（精确匹配优先，避免"豌豆明思2025"误匹配到"豌豆明思2025（英语）"）
    # 先精确匹配
    if course_type in COURSE_STAGE_IDS:
        return COURSE_STAGE_IDS[course_type].get(stage)
    # 再模糊匹配
    for full_name, stages in COURSE_STAGE_IDS.items():
        if course_type in full_name or full_name in course_type:
            return stages.get(stage)
    
    return None


def query_classes(token: str, cate_sid: int, limit: int = 200, lan_id: int = -1, class_stu_type: int = 1) -> List[Dict]:
    """查询指定课程阶段的班级（支持分页，突破50条限制）
    
    Args:
        token: Bearer token
        cate_sid: 课程阶段ID
        limit: 每页数量（CRM后台限制最多50条）
        lan_id: 语种ID（-1=不限, 90=普通话, 63=英语, 91=中英, 69=粤语）
        class_stu_type: 班级插班状态筛选（0=全部, 1=允许插班, 2=禁止插班）
    
    Returns:
        班级列表
    """
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json;charset=UTF-8"
    }
    
    all_classes = []
    seen_ids = set()
    
    # 当class_stu_type=0(查全部)时，isMax=-1不返回满班，需要分两次查
    if class_stu_type == 0:
        is_max_list = [0, 1]  # 0=非满班, 1=满班
    else:
        is_max_list = [-1]
    
    for is_max in is_max_list:
        page = 1
        page_size = 50
        
        while True:
            data = {
                "___auth___": 1,
                "group": "",
                "teacherId": "",
                "weekArr": [],
                "page": page,
                "limit": page_size,
                "isMax": is_max,
                "classLevel": "",
                "courseStage": [],
                "nextCnId": "",
                "remainSymbol": 1,
                "remainLive": "",
                "keyword": "",
                "classDate": "",
                "nextLiveTime": [],
                "isClose": -1,
                "maxClassNum": "",
                "grade": "",
                "cateArr": [],
                "classId": "",
                "hourArr": [],
                "sex": -1,
                "lanId": lan_id,
                "cateSids": [cate_sid],
                "teacherTag": -1,
                "oldCateSids": [],
                "courseType": "",
                "DepartmentMemberSelector": "",
                "classTag": "",
                "classType": 0,
                "classStuType": class_stu_type,  # 0=全部, 1=仅允许插班
                "sysTag": ""
            }
            
            try:
                resp = requests.post(CRM_API_URL, headers=headers, json=data, timeout=10)
                result = resp.json()
                
                if result.get("code") == 200:
                    classes = result.get("data", [])
                    if not classes:
                        break
                    for c in classes:
                        cid = c.get("classId")
                        if cid not in seen_ids:
                            all_classes.append(c)
                            seen_ids.add(cid)
                    
                    if len(classes) < page_size:
                        break
                    page += 1
                else:
                    print(f"API错误: {result}")
                    break
            except Exception as e:
                print(f"查询失败: {e}")
                break
    
    return all_classes


def parse_weekday_range(weekday_desc: str) -> tuple:
    """解析周期范围描述
    
    支持格式：
    - "周一到周四" -> (["周一", "周二", "周三", "周四"], False)
    - "周一至周四" -> (["周一", "周二", "周三", "周四"], False)
    - "周一到周五" -> (["周一", "周二", "周三", "周四", "周五"], False)
    - "仅周一到周四" -> (["周一", "周二", "周三", "周四"], True)  # strict=True 表示仅包含这些天
    - "工作日" -> (["周一", "周二", "周三", "周四", "周五"], False)
    - "周末" -> (["周六", "周日"], False)
    - "周一" -> (["周一"], False)
    - "周一周四" -> (["周一", "周四"], False)
    
    Returns:
        tuple: (weekday_list, strict_mode)
        - weekday_list: 包含的周几列表
        - strict_mode: 是否为严格模式（仅包含这些天，不能有其他天）
    """
    weekday_desc = weekday_desc.strip()
    
    WEEKDAY_ALL = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    WEEKDAY_MAP = {
        "一": "周一", "二": "周二", "三": "周三", "四": "周四", 
        "五": "周五", "六": "周六", "日": "周日", "天": "周日", "七": "周日"
    }
    
    strict_mode = False
    
    # 检查是否是严格模式（仅包含）
    if "仅" in weekday_desc or "只" in weekday_desc:
        strict_mode = True
        weekday_desc = weekday_desc.replace("仅", "").replace("只", "").strip()
    
    # 检查是否是范围表达（周一到周四、周一至周五）
    import re
    range_match = re.search(r'周([一二三四五六日天])\s*(?:到|至|-|~)\s*周([一二三四五六日天])', weekday_desc)
    if range_match:
        start_key = range_match.group(1)
        end_key = range_match.group(2)
        start_idx = ["一", "二", "三", "四", "五", "六", "日"].index(start_key)
        end_idx = ["一", "二", "三", "四", "五", "六", "日"].index(end_key)
        
        if start_idx <= end_idx:
            selected = [WEEKDAY_MAP[k] for k in ["一", "二", "三", "四", "五", "六", "日"][start_idx:end_idx+1]]
            return (selected, strict_mode)
    
    # 检查工作日
    if "工作日" in weekday_desc:
        return (["周一", "周二", "周三", "周四", "周五"], strict_mode)
    
    # 检查周末
    if "周末" in weekday_desc:
        return (["周六", "周日"], strict_mode)
    
    # 提取所有周几
    selected = []
    for key, name in WEEKDAY_MAP.items():
        if f"周{key}" in weekday_desc:
            selected.append(name)
    
    # 去重并保持顺序
    seen = set()
    result = []
    for w in selected:
        if w not in seen:
            seen.add(w)
            result.append(w)
    
    return (result if result else [], strict_mode)


def check_weekday_match(week_date: str, allowed_weekdays: list, strict_mode: bool = False) -> bool:
    """检查班级时间是否匹配周期要求
    
    Args:
        week_date: 班级时间字符串，如 "周一:18:30/周五:18:30"
        allowed_weekdays: 允许的周几列表，如 ["周一", "周二", "周三", "周四"]
        strict_mode: 是否严格模式（班级所有时间点都要在允许范围内）
    
    Returns:
        bool: 是否匹配
    """
    if not allowed_weekdays:
        return True
    
    import re
    # 提取所有周几，如从 "周一:18:30/周五:18:30" 提取 ["周一", "周五"]
    weekdays_in_class = re.findall(r'周[一二三四五六日天]', week_date)
    
    if strict_mode:
        # 严格模式：所有时间点都要在允许范围内
        for wd in weekdays_in_class:
            if wd not in allowed_weekdays:
                return False
        # 还要至少有一个时间点在范围内
        return any(wd in allowed_weekdays for wd in weekdays_in_class)
    else:
        # 宽松模式：至少有一个时间点在范围内
        return any(wd in allowed_weekdays for wd in weekdays_in_class)


def parse_time_range(time_desc: str) -> dict:
    """解析时间范围描述
    
    支持格式：
    - "16:00以后" -> {"min": "16:00"}
    - "16:00之前" -> {"max": "16:00"}
    - "19:00-21:00" -> {"min": "19:00", "max": "21:00"}
    - "上午" -> {"min": "08:00", "max": "12:00"}
    - "下午" -> {"min": "12:00", "max": "18:00"}
    - "晚上" -> {"min": "18:00", "max": "23:00"}
    - "20:10" -> {"exact": "20:10"} 精确匹配
    
    Returns:
        dict: {"min": "HH:MM", "max": "HH:MM", "exact": "HH:MM"} 或 {}
    """
    time_desc = time_desc.strip()
    time_desc = time_desc.replace('：', ':')  # 中文全角冒号→英文半角冒号
    
    # 时间段映射
    TIME_PERIODS = {
        "上午": {"min": "08:00", "max": "12:00"},
        "早上": {"min": "08:00", "max": "12:00"},
        "中午": {"min": "11:00", "max": "14:00"},
        "下午": {"min": "12:00", "max": "18:00"},
        "晚上": {"min": "18:00", "max": "23:00"},
        "夜间": {"min": "19:00", "max": "23:00"},
    }
    
    # 检查时间段关键词
    for period, range_dict in TIME_PERIODS.items():
        if period in time_desc:
            return range_dict
    
    # 检查 "XX:XX以后" 或 "XX:XX之后"
    import re
    match_after = re.search(r'(\d{1,2}:\d{2})\s*(?:以后|之后|后)', time_desc)
    if match_after:
        return {"min": match_after.group(1)}
    
    # 检查 "XX:XX之前" 或 "XX:XX之前"
    match_before = re.search(r'(\d{1,2}:\d{2})\s*(?:以前|之前|前)', time_desc)
    if match_before:
        return {"max": match_before.group(1)}
    
    # 检查范围 "XX:XX-YY:YY"
    match_range = re.search(r'(\d{1,2}:\d{2})\s*[-~到]\s*(\d{1,2}:\d{2})', time_desc)
    if match_range:
        return {"min": match_range.group(1), "max": match_range.group(2)}
    
    # 精确时间 "XX:XX"
    match_exact = re.match(r'^(\d{1,2}:\d{2})$', time_desc)
    if match_exact:
        return {"exact": match_exact.group(1)}
    
    return {}


def _normalize_time(t: str) -> str:
    """标准化时间格式为 HH:MM（补前导零），确保 "7:00" 和 "07:00" 比较一致"""
    parts = t.split(':')
    if len(parts) == 2:
        return f'{int(parts[0]):02d}:{parts[1]}'
    return t


def time_in_range(time_str: str, range_dict: dict) -> bool:
    """检查时间是否在指定范围内
    
    Args:
        time_str: 时间字符串，格式 "HH:MM"
        range_dict: 时间范围 {"min": "HH:MM", "max": "HH:MM", "exact": "HH:MM"}
    
    Returns:
        bool: 是否在范围内
    """
    if not range_dict:
        return True
    
    try:
        # 从 weekDate 中提取时间，如 "周二:20:10/周四:19:00"
        # 取第一个时间点
        import re
        times = re.findall(r'(\d{1,2}:\d{2})', time_str)
        if not times:
            return False
        
        time_val = _normalize_time(times[0])  # 取第一个时间，标准化格式
        
        # 精确匹配（标准化后再比较）
        if "exact" in range_dict:
            return time_val == _normalize_time(range_dict["exact"])
        
        # 范围匹配（标准化后再比较）
        if "min" in range_dict and time_val < _normalize_time(range_dict["min"]):
            return False
        if "max" in range_dict and time_val > _normalize_time(range_dict["max"]):
            return False
        
        return True
    except:
        return False


def parse_chapter_number(chapter_name: str) -> int:
    """从讲次名称中解析讲次编号
    例如 "S1_85(虫虫乐队)" -> 85, "S2_9(测试)" -> 9
    """
    import re
    match = re.search(r'_(\d+)', chapter_name)
    if match:
        return int(match.group(1))
    return -1


def is_first_lecture(chapter_name: str) -> bool:
    """判断讲次是否为专题首讲（4X+1规则）
    4节课=1个专题，首讲编号满足 n % 4 == 1
    即第1、5、9、13...讲
    """
    num = parse_chapter_number(chapter_name)
    if num < 0:
        return True  # 解析失败时默认允许
    return num % 4 == 1


def calc_next_first_lecture_date(next_live_date: str, chapter_name: str, week_date: str) -> tuple:
    """计算下一个专题首讲的上课时间
    
    Args:
        next_live_date: 下次上课时间，如 "2026-05-16 08:00"
        chapter_name: 下次课讲次名称，如 "S1_85(虫虫乐队)"
        week_date: 上课时间，如 "周三:08:00/周六:08:00"
    
    Returns:
        (首讲日期字符串, 首讲讲次编号, 距首讲几节课)
    """
    from datetime import datetime, timedelta
    import re
    
    num = parse_chapter_number(chapter_name)
    if num < 0:
        return next_live_date, num, 0
    
    # 计算到下一个首讲的课次间隔
    # 4X+1: 1,5,9,13,... 
    # gap = (5 - N%4) % 4
    if num % 4 == 1:
        gap = 0  # 当前就是首讲
    else:
        gap = (5 - num % 4) % 4
    
    if gap == 0:
        return next_live_date, num, 0
    
    next_chapter_num = num + gap
    
    # 解析上课时间点列表
    # week_date格式: "周三:08:00/周六:08:00"
    weekday_map = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6}
    time_slots = []  # [(weekday, hour, minute), ...]
    for part in week_date.split("/"):
        m = re.match(r'(\w+):(\d{2}):(\d{2})', part.strip())
        if m:
            day_name, hour, minute = m.group(1), int(m.group(2)), int(m.group(3))
            if day_name in weekday_map:
                time_slots.append((weekday_map[day_name], hour, minute))
    
    if not time_slots:
        return next_live_date, next_chapter_num, gap
    
    # 按weekday排序
    time_slots.sort(key=lambda x: x[0] * 1440 + x[1] * 60 + x[2])
    
    # 解析next_live_date
    try:
        base_dt = datetime.strptime(next_live_date, "%Y-%m-%d %H:%M")
    except:
        return next_live_date, next_chapter_num, gap
    
    # 找到base_dt对应的time_slot
    base_weekday = base_dt.weekday()
    base_hour = base_dt.hour
    base_minute = base_dt.minute
    
    # 从base_dt开始，往后推gap个课次
    current_dt = base_dt
    # 找当前时间在time_slots中的位置
    current_idx = -1
    for i, (wd, h, m) in enumerate(time_slots):
        if wd == base_weekday and h == base_hour and m == base_minute:
            current_idx = i
            break
    
    if current_idx == -1:
        # 无法匹配，用简单推算：每周len(time_slots)次课
        days_per_class = 7 / len(time_slots)
        result_dt = base_dt + timedelta(days=days_per_class * gap)
        return result_dt.strftime("%Y-%m-%d %H:%M"), next_chapter_num, gap
    
    # 逐课次推算
    idx = current_idx
    for _ in range(gap):
        idx += 1
        if idx >= len(time_slots):
            idx = 0
            # 进入下一周
            current_dt = current_dt + timedelta(days=7)
        
        # 设置到对应的时间点
        target_wd, target_h, target_m = time_slots[idx]
        # 计算从current_dt到目标weekday的偏移
        current_wd = current_dt.weekday()
        day_diff = (target_wd - current_wd) % 7
        current_dt = current_dt.replace(hour=target_h, minute=target_m) + timedelta(days=day_diff)
    
    return current_dt.strftime("%Y-%m-%d %H:%M"), next_chapter_num, gap


def filter_insertable_classes(classes: List[Dict], course_type: str = "", time_filter: str = "", weekday_filter: str = "", time_range: dict = None, weekday_strict_mode: bool = False, token: str = "") -> List[Dict]:
    """筛选可插班班级
    
    注意：API已通过 classStuType=1 筛选了允许插班的班级
    这里只需再检查：
    - isClose == 0 (执行中)
    - studentCount < maxClassNum (未满班)
    - 英语/粤语排除普通话班级（lanId=90），台湾不排除
    - 下次课必须为专题首讲（4X+1规则：讲次编号 % 4 == 1）
    - 时间筛选（如 20:10）
    - 时间范围筛选（如 16:00以后、晚上）
    - 周期筛选（如 工作日、周一、周一到周四）
    
    Args:
        classes: 原始班级列表
        course_type: 课类（英语、粤语、台湾）
        time_filter: 时间筛选（如 20:10）- 已废弃，使用 time_range
        weekday_filter: 周期筛选（如 工作日、周一、周一到周四）
        time_range: 时间范围 {"min": "HH:MM", "max": "HH:MM", "exact": "HH:MM"}
        weekday_strict_mode: 是否严格模式（班级所有时间点都要在指定周期范围内）
    
    Returns:
        可插班班级列表（按剩余名额降序）
    """
    # 工作日映射
    WEEKDAY_MAP = {
        "周一": "周一", "周二": "周二", "周三": "周三", "周四": "周四", "周五": "周五",
        "周六": "周六", "周日": "周日", "周天": "周日", "周七": "周日"
    }
    WORKDAYS = ["周一", "周二", "周三", "周四", "周五"]
    
    # 兼容旧的 time_filter 参数
    if time_filter and not time_range:
        time_range = {"exact": time_filter}
    
    # 解析周期范围（支持"周一到周四"这种表达）
    allowed_weekdays = []
    if weekday_filter:
        allowed_weekdays, parsed_strict = parse_weekday_range(weekday_filter)
        # 如果解析出严格模式，使用解析结果
        if parsed_strict:
            weekday_strict_mode = True
    
    valid = []
    for c in classes:
        # 英语和粤语排除普通话班级（lanId=90），台湾不排除
        if course_type in ["英语", "粤语"] and c.get("lanId") == 90:
            continue
        
        week_date = c.get("weekDate", "")
        
        # 周期筛选（使用新的智能匹配）
        if allowed_weekdays:
            if not check_weekday_match(week_date, allowed_weekdays, weekday_strict_mode):
                continue
        
        # 时间范围筛选
        if time_range:
            if not time_in_range(week_date, time_range):
                continue
            
        if (c.get("isClose") == 0 and 
            c.get("studentCount", 0) < c.get("maxClassNum", 8)):
            
            remain = c["maxClassNum"] - c["studentCount"]
            
            # 推算首讲信息（作为后备，后续会用课节列表精准覆盖）
            next_chapter = c.get("nextChapterName", "")
            next_live_date = c.get("nextLiveDate", "")
            week_date_str = c.get("weekDate", "")
            first_lecture_date, first_lecture_num, gap = calc_next_first_lecture_date(
                next_live_date, next_chapter, week_date_str
            )
            
            valid.append({
                "id": c["classId"],
                "teacher": c["teacherName"],
                "teacher_tag": c.get("teacherOverseaGradeStr", "") or c.get("teacherGradeStr", "") or c.get("teacherTagStr", ""),
                "week": c["weekDate"],
                "student_count": c["studentCount"],
                "max_num": c["maxClassNum"],
                "remain": remain,
                "next_date": first_lecture_date,
                "next_chapter": f"S{first_lecture_num}" if first_lecture_num > 0 else next_chapter,
                "gap": gap
            })
    
    # 精准定位首讲时间：查询每个班级的课节列表
    if valid and token:
        import requests as req
        headers = {
            "authorization": f"Bearer {token}",
            "content-type": "application/json"
        }
        # 并发请求getLiveList，大幅提升速度
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def fetch_first_lecture(v):
            """查询单个班级的首讲课节"""
            try:
                resp = req.post(
                    "https://ems.vipthink.cn/gateway/route__jw/api/classs/getLiveList",
                    headers=headers,
                    json={"classId": v["id"], "liveStatus": 0},
                    timeout=10
                )
                data = resp.json()
                lives = data.get("data", [])
                for live in lives:
                    chapter_number = live.get("chapterNumber", "")
                    chapter_num = parse_chapter_number(chapter_number)
                    if chapter_num > 0 and chapter_num % 4 == 1:
                        v["next_date"] = f"{live.get('classDate', '')} {live.get('startTime', '')}"
                        v["next_chapter"] = chapter_number
                        v["gap"] = 0
                        break
            except:
                pass
            return v
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            list(executor.map(fetch_first_lecture, valid))
    
    # 按剩余名额降序
    valid.sort(key=lambda x: x["remain"], reverse=True)
    return valid


def format_result(classes: List[Dict], course_type: str, stage: str) -> str:
    """格式化查询结果为消息文本（钉钉消息限制20000字节，超出自动截断）
    
    Args:
        classes: 可插班班级列表
        course_type: 课类
        stage: 阶段
    
    Returns:
        格式化的消息文本（Markdown格式）
    """
    MAX_BYTES = 18000  # 留2000字节余量
    
    lines = [
        f"### {course_type} {stage} 可插班班级",
        f"共找到 **{len(classes)}** 个可插班班级\n"
    ]
    
    if len(classes) == 0:
        lines.append("暂无符合条件的班级")
        return "\n\n".join(lines)
    
    truncated = False
    current_bytes = len("\n\n".join(lines).encode('utf-8'))
    
    for i, c in enumerate(classes, 1):
        tag_str = f" | {c['teacher_tag']}" if c.get('teacher_tag') else ""
        first_lecture = f" | 首讲:{c['next_date']}" if c.get("next_date") else ""
        first_chapter = f"({c['next_chapter']})" if c.get("next_chapter") else ""
        line = f"**{i}.** ID `{c['id']}` | {c['teacher']}{tag_str} | {c['week']} | 剩余**{c['remain']}**人{first_lecture}{first_chapter}"
        line_bytes = len(line.encode('utf-8')) + 2  # +2 for \n\n
        
        if current_bytes + line_bytes > MAX_BYTES:
            truncated = True
            break
        
        lines.append(line)
        current_bytes += line_bytes
    
    if truncated:
        lines.append(f"\n⚠️ 结果过长，仅显示前 {i-1} 条，共 {len(classes)} 条。请缩小查询范围（加时间/星期筛选）")
    
    return "\n\n".join(lines)


def format_class_detail(cls: Dict, language: str = "", show_teacher_tag: bool = True, show_first_lecture: bool = True) -> str:
    """格式化单个班级的详细信息（用于指定老师查班，展示更多字段）
    
    包含：语种、阶段、老师、时间、人数、满班/锁班标记、首讲
    指定老师查班时可关闭teacher_tag和first_lecture
    """
    # 语种
    lang = cls.get("language", "") or ""
    # 阶段（从cateStr提取，如"豌豆明思2025/S2"）
    cate_str = cls.get("cateStr", "")
    stage_str = cate_str.split("/")[-1] if "/" in cate_str else ""
    # 老师
    teacher = cls.get("teacherName", "")
    tag = cls.get("teacherTagStr", "") or cls.get("teacherGradeStr", "")
    tag_str = f"({tag})" if (tag and show_teacher_tag) else ""
    # 时间
    week = cls.get("weekDate", "")
    # 人数
    student_count = cls.get("studentCount", 0)
    max_num = cls.get("maxClassNum", 0)
    # 状态标记
    status_tags = []
    if student_count >= max_num:
        status_tags.append("满班")
    if cls.get("classStuType") == 2:
        status_tags.append("锁班")
    status_str = " | " + " ".join(status_tags) if status_tags else ""
    # 首讲
    next_live = cls.get("nextLiveDate", "")
    first_lecture = f" | 首讲:{next_live}" if (next_live and show_first_lecture) else ""
    
    # 语种+阶段
    lang_stage = ""
    if lang:
        lang_stage = f"{lang} {stage_str}" if stage_str else lang
    elif stage_str:
        lang_stage = stage_str
    
    return f"ID `{cls.get('classId', cls.get('id', ''))}` | {lang_stage} | {teacher}{tag_str} | {week} | {student_count}/{max_num}{status_str}{first_lecture}"


# 测试
if __name__ == "__main__":
    # 测试查询
    token = "eyJhbGciOiJzaGEyNTYiLCJ0eXAiOiJKV1QifQ.W3sibmJmIjoxNzc3MzQwODk5LCJpc3MiOiJkb2YiLCJ0emEiOiJDU1QiLCJleHAiOjE3Nzc0MjcyOTksImlhdCI6MTc3NzM0MDg5OSwic2lkIjoxfSx7InJhbmQiOiIzOTE2NTM5ODA5ODM1Mzc5Mjk4OTA1MTkwNjIwMTI4MjIxMzcyMDUwNTE5Mjc3MDQ1NDQwMTQ5ODA2NTE3NjI4IiwidWlkIjozMzAxLCJ0eXAiOiJhIiwidGltZSI6MTc3NzM0MDg5OX1d.YmUxMTI2YjI3NjNjY2EyZDhlZjE4ODk0NmQ1N2U4OWUzN2MwYzA5YWJkNzNjZTg3Njc5Zjk3NGQ0ZTMwNTNlMA"
    
    # 获取台湾S3的ID
    stage_id = get_stage_id("台湾", "S3")
    print(f"台湾S3 ID: {stage_id}")
    
    # 查询
    classes = query_classes(token, stage_id)
    print(f"查询到 {len(classes)} 个班级")
    
    # 筛选
    valid = filter_insertable_classes(classes)
    print(f"可插班: {len(valid)} 个")
    
    # 格式化
    msg = format_result(valid, "台湾", "S3")
    print(msg)


# 锁班/解锁班 API
LOCK_API_URL = "https://ems.vipthink.cn/gateway/route__jw/api/classs/batchSetGradeType"



def lock_class(token: str, class_id: str, lock: bool = True) -> dict:
    """锁班/解锁班
    
    Args:
        token: Bearer token
        class_id: 班级ID
        lock: True=锁班, False=解锁
    
    Returns:
        {"success": bool, "msg": str}
    """
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json;charset=UTF-8"
    }
    
    # classStuTypeSet: 1=解锁, 2=锁定
    data = {
        "___auth___": 1,
        "classId": str(class_id),
        "classStuTypeSet": 2 if lock else 1,
        "operaType": 1
    }
    
    try:
        resp = requests.post(LOCK_API_URL, headers=headers, json=data, timeout=10)
        result = resp.json()
        
        if result.get("code") == 200:
            return {"success": True, "msg": "操作成功"}
        else:
            return {"success": False, "msg": result.get("msg", "未知错误")}
    except Exception as e:
        return {"success": False, "msg": str(e)}


# 设置插班状态 API
# classStuType: 0=锁班(禁止插班), 1=解锁班(允许插班)
SET_GRADE_TYPE_URL = "https://ems.vipthink.cn/gateway/route__jw/api/classs/setGradeType"



def set_insertable(token: str, class_id: str, allow: bool = True) -> dict:
    """设置班级插班权限
    
    Args:
        token: Bearer token
        class_id: 班级ID
        allow: True=解锁班(允许插班), False=锁班(禁止插班)
    
    Returns:
        {"success": bool, "msg": str}
    """
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json;charset=UTF-8"
    }
    
    # classStuType: 0=锁班(禁止插班), 1=解锁班(允许插班)
    data = {
        "classId": int(class_id),
        "classStuType": 1 if allow else 0
    }
    
    try:
        resp = requests.post(SET_GRADE_TYPE_URL, headers=headers, json=data, timeout=10)
        result = resp.json()
        
        if result.get("code") == 200:
            action = "允许插班" if allow else "禁止插班"
            return {"success": True, "msg": f"{action}成功"}
        else:
            return {"success": False, "msg": result.get("msg", "未知错误")}
    except Exception as e:
        return {"success": False, "msg": str(e)}


# 设置补课权限 API
# makeup: 1=允许补课, 2=禁止补课
SET_MAKEUP_URL = "https://ems.vipthink.cn/gateway/route__jw/api/classs/setMakeup"



def set_makeup(token: str, class_id: str, allow: bool = True) -> dict:
    """设置班级补课权限
    
    Args:
        token: Bearer token
        class_id: 班级ID
        allow: True=允许补课, False=禁止补课
    
    Returns:
        {"success": bool, "msg": str}
    """
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json;charset=UTF-8"
    }
    
    # makeup: 1=允许补课, 2=禁止补课
    data = {
        "classId": int(class_id),
        "makeup": 1 if allow else 2
    }
    
    try:
        resp = requests.post(SET_MAKEUP_URL, headers=headers, json=data, timeout=10)
        result = resp.json()
        
        if result.get("code") == 200:
            action = "允许补课" if allow else "禁止补课"
            return {"success": True, "msg": f"{action}成功"}
        else:
            return {"success": False, "msg": result.get("msg", "未知错误")}
    except Exception as e:
        return {"success": False, "msg": str(e)}


# ========== Token 自动刷新功能 ==========
import base64
import json as json_module
from datetime import datetime

def parse_token_expiry(token: str) -> datetime:
    """解析 JWT Token 的过期时间
    
    JWT Token 格式: header.payload.signature
    payload 是 base64 编码的 JSON
    """
    try:
        # 分割 token
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        # 解码 payload（第二部分）
        payload = parts[1]
        # 补齐 base64 padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        decoded = base64.urlsafe_b64decode(payload)
        
        # 尝试解析 JSON（可能有多段）
        text = decoded.decode('utf-8')
        
        # 格式1: 标准 JSON
        if text.startswith('['):
            # 数组格式 [{...}, {...}] 后可能有多余数据
            # 找到第一个完整的 JSON 数组
            try:
                data = json_module.loads(text)
            except json_module.JSONDecodeError:
                # 有多余数据，截取到第一个 ] 结束
                idx = text.find(']')
                if idx > 0:
                    json_part = text[:idx+1]
                    data = json_module.loads(json_part)
                else:
                    raise
        elif text.startswith('{'):
            # 对象格式
            data = json_module.loads(text)
        else:
            # 尝试直接解析
            data = json_module.loads(text)
        
        # JWT 中的 exp 可能在不同位置
        exp_value = None
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and 'exp' in item:
                    exp_value = item['exp']
                    break
        elif isinstance(data, dict):
            exp_value = data.get('exp')
        
        if exp_value:
            return datetime.fromtimestamp(exp_value)
        
        return None
    except Exception as e:
        print(f"解析 Token 失败: {e}")
        return None


def is_token_expiring_soon(token: str, hours: int = 24) -> bool:
    """检查 Token 是否即将过期
    
    Args:
        token: JWT Token
        hours: 提前多少小时提醒（默认24小时）
    
    Returns:
        True 如果 Token 将在指定时间内过期
    """
    expiry = parse_token_expiry(token)
    if not expiry:
        return False  # 无法解析，假设有效
    
    now = datetime.now()
    time_left = expiry - now
    
    return time_left.total_seconds() < hours * 3600


# ==================== 按老师操作 ====================

# 老师名→teacherId缓存（启动时预加载小阶段，避免每次查班都遍历）
_teacher_cache: Dict[str, str] = {}  # 艺名/真名 -> teacherId
_cache_loaded = False


def _build_teacher_cache(token: str):
    """预加载老师名→ID缓存，先查小阶段（一页覆盖），再查大阶段（分页）"""
    global _teacher_cache, _cache_loaded
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json;charset=UTF-8"
    }
    
    # 分类：小阶段（<=200班）和大阶段（>200班）
    small_sids = []  # (sid, total)
    large_sids = []  # (sid, total)
    
    for name, stages in COURSE_STAGE_IDS.items():
        for stage, sid in stages.items():
            # 先查总数
            data = {
                "___auth___": 1, "group": "", "teacherId": "", "weekArr": [],
                "page": 1, "limit": 1, "isMax": -1, "classLevel": "",
                "courseStage": [], "nextCnId": "", "remainSymbol": 1,
                "remainLive": "", "keyword": "",
                "classDate": "", "nextLiveTime": [], "isClose": -1, "maxClassNum": "",
                "grade": "", "cateArr": [], "classId": "", "hourArr": [],
                "sex": -1, "lanId": -1, "cateSids": [sid],
                "teacherTag": -1, "oldCateSids": [], "courseType": "",
                "DepartmentMemberSelector": "", "classTag": "", "classType": 0,
                "classStuType": 0, "sysTag": ""
            }
            try:
                resp = requests.post(CRM_API_URL, headers=headers, json=data, timeout=10)
                total = resp.json().get("pages", {}).get("total", 0)
                if total <= 200:
                    small_sids.append((sid, total))
                else:
                    large_sids.append((sid, total))
            except:
                small_sids.append((sid, 0))  # 出错也加入小阶段列表
    
    # 先查小阶段（一页覆盖全部老师）
    for sid, _ in small_sids:
        data = {
            "___auth___": 1, "group": "", "teacherId": "", "weekArr": [],
            "page": 1, "limit": 200, "isMax": -1, "classLevel": "",
            "courseStage": [], "nextCnId": "", "remainSymbol": 1,
            "remainLive": "", "keyword": "",
            "classDate": "", "nextLiveTime": [], "isClose": -1, "maxClassNum": "",
            "grade": "", "cateArr": [], "classId": "", "hourArr": [],
            "sex": -1, "lanId": -1, "cateSids": [sid],
            "teacherTag": -1, "oldCateSids": [], "courseType": "",
            "DepartmentMemberSelector": "", "classTag": "", "classType": 0,
            "classStuType": 0, "sysTag": ""
        }
        try:
            resp = requests.post(CRM_API_URL, headers=headers, json=data, timeout=10)
            classes = resp.json().get("data", [])
            for c in classes:
                _add_teacher_to_cache(c)
        except:
            pass
    
    # 再查大阶段（分页，最多5页）
    for sid, total in large_sids:
        max_pages = min(5, (total + 199) // 200)  # 最多5页
        for page in range(1, max_pages + 1):
            data = {
                "___auth___": 1, "group": "", "teacherId": "", "weekArr": [],
                "page": page, "limit": 200, "isMax": -1, "classLevel": "",
                "courseStage": [], "nextCnId": "", "remainSymbol": 1,
                "remainLive": "", "keyword": "",
                "classDate": "", "nextLiveTime": [], "isClose": -1, "maxClassNum": "",
                "grade": "", "cateArr": [], "classId": "", "hourArr": [],
                "sex": -1, "lanId": -1, "cateSids": [sid],
                "teacherTag": -1, "oldCateSids": [], "courseType": "",
                "DepartmentMemberSelector": "", "classTag": "", "classType": 0,
                "classStuType": 0, "sysTag": ""
            }
            try:
                resp = requests.post(CRM_API_URL, headers=headers, json=data, timeout=10)
                classes = resp.json().get("data", [])
                if not classes:
                    break
                for c in classes:
                    _add_teacher_to_cache(c)
            except:
                break
    
    _cache_loaded = True


def _add_teacher_to_cache(class_item: Dict):
    """从班级数据中提取老师信息加入缓存"""
    tn = class_item.get("teacherName", "")
    tid = str(class_item.get("teacherId", ""))
    if tn and tid:
        _teacher_cache[tn] = tid
    for t in class_item.get("teacherArr", []):
        nickname = t.get("nickname", "")
        name_val = t.get("name", "")
        tid2 = str(t.get("id", ""))
        if nickname and tid2 and nickname not in _teacher_cache:
            _teacher_cache[nickname] = tid2
        if name_val and tid2 and name_val not in _teacher_cache:
            _teacher_cache[name_val] = tid2


def _find_teacher_id(token: str, teacher_name: str) -> str:
    """查找老师ID，优先从缓存找，找不到则实时查小阶段"""
    global _teacher_cache, _cache_loaded
    
    # 先从缓存找（精确匹配和模糊匹配）
    if _teacher_cache:
        # 精确匹配
        if teacher_name in _teacher_cache:
            return _teacher_cache[teacher_name]
        # 模糊匹配：名字包含关系，优先短名匹配
        matches = []
        for cached_name, tid in _teacher_cache.items():
            if teacher_name in cached_name or cached_name in teacher_name:
                matches.append((cached_name, tid))
        if matches:
            # 如果只有一个匹配，直接返回
            if len(matches) == 1:
                return matches[0][1]
            # 多个匹配时，优先选名字最短的（更精确）
            matches.sort(key=lambda x: len(x[0]))
            return matches[0][1]
    
    # 缓存没找到，实时查小阶段（英语/粤语/台湾/S1，数据量小响应快）
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json;charset=UTF-8"
    }
    for name, stages in COURSE_STAGE_IDS.items():
        for stage, sid in stages.items():
            data = {
                "___auth___": 1, "group": "", "teacherId": "", "weekArr": [],
                "page": 1, "limit": 200, "isMax": -1, "classLevel": "",
                "courseStage": [], "nextCnId": "", "remainSymbol": 1,
                "remainLive": "", "keyword": "",
                "classDate": "", "nextLiveTime": [], "isClose": -1, "maxClassNum": "",
                "grade": "", "cateArr": [], "classId": "", "hourArr": [],
                "sex": -1, "lanId": -1, "cateSids": [sid],
                "teacherTag": -1, "oldCateSids": [], "courseType": "",
                "DepartmentMemberSelector": "", "classTag": "", "classType": 0,
                "classStuType": 0, "sysTag": ""
            }
            try:
                resp = requests.post(CRM_API_URL, headers=headers, json=data, timeout=10)
                classes = resp.json().get("data", [])
                for c in classes:
                    _add_teacher_to_cache(c)
                    tn = c.get("teacherName", "")
                    if teacher_name in tn or tn in teacher_name:
                        return str(c.get("teacherId", ""))
                    for t in c.get("teacherArr", []):
                        nickname = t.get("nickname", "")
                        name_val = t.get("name", "")
                        if (teacher_name in nickname or nickname in teacher_name or
                            teacher_name in name_val or name_val in teacher_name):
                            return str(t.get("id", ""))
            except:
                pass
    
    return ""


def query_classes_by_teacher(token: str, teacher_name: str, course_type: str = None, class_stu_type: int = None) -> List[Dict]:
    """按老师名字查询班级（高效版：缓存teacherId + 一次查所有班）
    
    优化策略：
    1. 启动时预加载老师名→ID缓存
    2. 查老师时先从缓存找teacherId，找不到再实时遍历
    3. 用teacherId + 空cateSids一次查所有阶段的班
    
    Args:
        token: Bearer token
        teacher_name: 老师名字（模糊匹配，如"奥力"、"Precious"）
        course_type: 可选，限定课类（英语、粤语、台湾）
        class_stu_type: 可选，班级状态筛选
            - None: 查询所有（锁班+解锁班+满班）
            - 0: 只查询锁班/禁止插班的班级（用于解锁操作）
            - 1: 只查询解锁班/允许插班的班级（用于锁定操作）
    
    Returns:
        班级列表
    """
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json;charset=UTF-8"
    }
    
    # 第一步：查老师ID
    teacher_id = _find_teacher_id(token, teacher_name)
    if not teacher_id:
        return []
    
    # 第二步：用teacherId一次性查所有班级（空cateSids查全部课类）
    all_classes = []
    seen_ids = set()
    
    # 构建cateSids（如果限定了课类）
    if course_type:
        stage_ids = []
        for full_name, stages in COURSE_STAGE_IDS.items():
            if course_type in full_name or COURSE_ALIASES.get(course_type, course_type) in full_name:
                stage_ids.extend(stages.values())
    else:
        stage_ids = []  # 空表示查所有课类
    
    # classStuType参数映射
    if class_stu_type is not None:
        if class_stu_type == 0:
            stu_types = [2]  # 查锁班
        else:
            stu_types = [1]  # 查解锁班
    else:
        stu_types = [0]  # 查全部
    
    # isMax: 查全部时需要补查满班；查锁班时也要包含满班（满班也可能是锁班状态）
    if class_stu_type is None or class_stu_type == 0:
        is_max_list = [0, 1]  # 查全部和查锁班都需要包含满班
    else:
        is_max_list = [-1]
    
    for stu_type in stu_types:
        for is_max in is_max_list:
            page = 1
            while True:
                data = {
                    "___auth___": 1, "group": "",
                    "teacherId": teacher_id,
                    "weekArr": [], "page": page, "limit": 200,
                    "isMax": is_max, "classLevel": "",
                    "courseStage": [], "nextCnId": "", "remainSymbol": -1,
                    "remainLive": "", "keyword": "",
                    "classDate": "", "nextLiveTime": [], "isClose": -1, "maxClassNum": "",
                    "grade": "", "cateArr": [], "classId": "", "hourArr": [],
                    "sex": -1, "lanId": -1,
                    "cateSids": stage_ids,
                    "teacherTag": -1, "oldCateSids": [], "courseType": "",
                    "DepartmentMemberSelector": "", "classTag": "", "classType": 0,
                    "classStuType": stu_type, "sysTag": ""
                }
                try:
                    resp = requests.post(CRM_API_URL, headers=headers, json=data, timeout=10)
                    result = resp.json()
                    if result.get("code") == 200:
                        classes = result.get("data", [])
                        if not classes:
                            break
                        for c in classes:
                            cid = c.get("classId")
                            if cid not in seen_ids and c.get("isClose") == 0:
                                all_classes.append(c)
                                seen_ids.add(cid)
                        if len(classes) < 200:
                            break
                        page += 1
                    else:
                        break
                except:
                    break
    
    return all_classes


def batch_set_insertable(token: str, class_ids: list, allow: bool = True) -> dict:
    """批量设置班级插班权限
    
    Args:
        token: Bearer token
        class_ids: 班级ID列表
        allow: True=解锁班(允许插班), False=锁班(禁止插班)
    
    Returns:
        {"success": int, "failed": int, "total": int, "failed_ids": list}
    """
    success_count = 0
    failed_count = 0
    failed_ids = []
    
    for class_id in class_ids:
        result = set_insertable(token, class_id, allow)
        if result["success"]:
            success_count += 1
        else:
            failed_count += 1
            failed_ids.append({"id": class_id, "msg": result["msg"]})
    
    return {
        "success": success_count,
        "failed": failed_count,
        "total": len(class_ids),
        "failed_ids": failed_ids
    }


def batch_set_makeup(token: str, class_ids: list, allow: bool = True) -> dict:
    """批量设置班级补课权限
    
    Args:
        token: Bearer token
        class_ids: 班级ID列表
        allow: True=允许补课, False=禁止补课
    
    Returns:
        {"success": int, "failed": int, "total": int, "failed_ids": list}
    """
    success_count = 0
    failed_count = 0
    failed_ids = []
    
    for class_id in class_ids:
        result = set_makeup(token, class_id, allow)
        if result["success"]:
            success_count += 1
        else:
            failed_count += 1
            failed_ids.append({"id": class_id, "msg": result["msg"]})
    
    return {
        "success": success_count,
        "failed": failed_count,
        "total": len(class_ids),
        "failed_ids": failed_ids
    }
# ==================== Token验证模块 ====================

def validate_token(token: str) -> tuple:
    """
    验证Token是否有效
    
    Returns:
        (is_valid, message)
    """
    import base64
    from datetime import datetime
    
    try:
        # 解析JWT获取过期时间
        if token.startswith('Bearer '):
            token = token[7:]
        
        parts = token.split('.')
        if len(parts) != 3:
            return False, "Token格式错误"
        
        # 解析payload
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        
        # 获取过期时间
        exp = payload[0].get('exp', 0)
        exp_time = datetime.fromtimestamp(exp)
        now = datetime.now()
        
        if exp < now.timestamp():
            return False, f"Token已过期，过期时间: {exp_time}"
        
        # Token还有1小时就提前刷新
        if exp - now.timestamp() < 3600:
            return False, f"Token即将过期，过期时间: {exp_time}，建议刷新"
        
        # 验证API调用
        test_url = "https://ems.vipthink.cn/gateway/route__jw/api/classs/setGradeType"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        data = {"classId": 1, "classStuType": 1}
        resp = requests.post(test_url, headers=headers, json=data, timeout=5)
        result = resp.json()
        
        # code=200表示Token有效，code=201可能是权限问题但Token本身有效
        if result.get("code") == 200:
            return True, "Token有效"
        elif result.get("code") == 201:
            # 用户识别失败，需要重新登录获取Token
            return False, f"API返回: {result.get('msg', '用户识别失败')}，请重新获取Token"
        else:
            return False, f"API异常: {result.get('msg', '未知错误')}"
            
    except Exception as e:
        return False, f"验证异常: {str(e)}"


def check_and_refresh_token_if_needed(token: str, token_file: str = None, bot_file: str = None) -> str:
    """
    检查Token有效性，如需刷新则自动刷新
    
    Returns:
        有效的Token
    """
    import os
    import subprocess
    from datetime import datetime
    
    is_valid, message = validate_token(token)
    print(f"[Token检查] {message}")
    
    if not is_valid:
        print("[Token检查] Token无效，正在刷新...")
        
        # 调用浏览器获取新Token（需要人工介入，这里只做日志记录）
        if "用户识别失败" in message or "Token已过期" in message:
            print("[Token检查] ⚠️ 需要重新登录CRM获取Token")
            print("[Token检查] 请执行以下命令刷新Token:")
            print("[Token检查] python dingtalk_stream_bot/update_token.py <新Token>")
            
            # 发送告警
            try:
                from notify import send_message_with_image
                send_message_with_image(
                    "⚠️ CRM Token失效提醒",
                    "Token已失效或即将过期，请尽快刷新！\n" + message,
                    None
                )
            except:
                pass
    
    return token


