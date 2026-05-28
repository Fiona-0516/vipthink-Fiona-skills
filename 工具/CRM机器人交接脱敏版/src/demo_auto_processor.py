#!/usr/bin/env python3
"""
DEMO绿色通道工单自动处理器
负责工单的预判断、自动排课、通知等全流程
"""

import re
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

current_dir = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [DEMO自动处理] %(levelname)-8s %(message)s'
)
logger = logging.getLogger("demo_auto")

# ==================== 配置 ====================

TICKET_API_BASE = "https://ticket.vipthink.cn"
EMS_API_BASE = "https://ems.vipthink.cn/gateway/route__jw/api"
TQS_API_BASE = "https://tqs.vipthink.cn/api"
MEMBER_API_BASE = "https://member.vipthink.cn/member/v1/back"
DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")

TOKEN_FILE = current_dir / "crm_token.json"
PROCESSED_ORDERS_FILE = current_dir / "processed_orders.json"
TEACHER_RATINGS_FILE = current_dir / "teacher_ratings.json"

# 老师评级排序权重（数值越大优先级越高）
RATING_PRIORITY = {"好": 4, "中1": 3, "中2": 2, "差": 1}

# DEMO绿色通道类型ID
DEMO_GREEN_CHANNEL_TYPE_ID = 1

# DEMO试听课 courseType
COURSE_TYPE_DEMO = 2
# 课节状态：待上课
LIVE_STATUS_PENDING = 0

# DEMO默认参数
DEFAULT_DEMO_CONSUME_HOUR = 1
DEFAULT_DEMO_DURATION = 40
DEFAULT_DEMO_SIZE = 4

# 语种 → 课类cateId映射（DEMO试听课）
LANGUAGE_CATE_MAP = {
    "中文": 55,
    "普通话": 55,
    "海外中文": 4088,
    "台湾": 2993,
    "英文": 1896,
    "英语": 1896,
    "粤语": 1894,
    "中英": 1953,
    "双语": 1953,
}

# 语种别名标准化
LANGUAGE_ALIASES = {
    "普通话": "中文",
    "中文": "中文",
    "国语": "中文",
    "英语": "英语",
    "英文": "英语",
    "全英": "英语",
    "粤语": "粤语",
    "广东话": "粤语",
    "台湾": "台湾",
    "海外中文": "海外中文",
    "中英": "中英",
    "双语": "中英",
}

# 周几映射
WEEKDAY_MAP = {
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    "周天": 6, "周七": 6,
}
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 课类阶段stepId缓存（从API动态加载）
_cate_step_cache = {}


# ==================== Token管理 ====================

def load_token() -> str:
    try:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("token", "")
    except Exception as e:
        logger.error(f"加载Token失败: {e}")
        return ""


# ==================== API调用 ====================

def call_ticket_api(method: str, endpoint: str, token: str, data: dict = None) -> dict:
    url = f"{TICKET_API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json;charset=UTF-8"}
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=data, timeout=15)
        else:
            resp = requests.post(url, headers=headers, json=data, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"工单API调用失败: {e}")
        return {"code": -1, "msg": str(e)}


def call_ems_api(endpoint: str, token: str, data: dict = None) -> dict:
    url = f"{EMS_API_BASE}/{endpoint}"
    headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"EMS API调用失败: {e}")
        return {"code": -1, "msg": str(e)}


def call_tqs_api(endpoint: str, token: str, data: dict = None) -> dict:
    url = f"{TQS_API_BASE}/{endpoint}"
    headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"TQS API调用失败: {e}")
        return {"code": -1, "msg": str(e)}


def call_member_api(endpoint: str, token: str, params: dict = None) -> dict:
    """调用会员系统API（member.vipthink.cn）"""
    url = f"{MEMBER_API_BASE}/{endpoint}"
    headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Member API调用失败: {e}")
        return {"code": -1, "msg": str(e)}


# ==================== 课类/课件工具 ====================

def get_step_id(cate_id: int, stage_name: str, token: str) -> Optional[int]:
    """从getTypeTmplDetail获取stepId"""
    global _cate_step_cache
    cache_key = cate_id
    if cache_key in _cate_step_cache:
        return _cate_step_cache[cache_key].get(stage_name)

    result = call_tqs_api("education/course/getTypeTmplDetail", token, {"id": 2})
    if result.get("code") != 200:
        logger.error(f"获取课类模板失败: {result.get('msg')}")
        return None

    categories = result.get("data", {}).get("courseCategories", [])
    for cat in categories:
        cid = cat.get("id")
        steps = {}
        for child in cat.get("children", []):
            name = child.get("name", "")
            steps[name] = child.get("id")
        _cate_step_cache[cid] = steps

    return _cate_step_cache.get(cache_key, {}).get(stage_name)


def get_cn_id(cate_id: int, step_id: int, courseware_name: str, token: str) -> Optional[int]:
    """从getChapters获取课件cnId"""
    result = call_tqs_api("education/course/getChapters", token, {"cateId": cate_id, "stepId": step_id})
    if result.get("code") != 200:
        logger.error(f"获取课件列表失败: {result.get('msg')}")
        return None

    chapters = result.get("data", [])
    if not chapters:
        return None

    # 精确匹配comboName
    for ch in chapters:
        if ch.get("comboName", "") == courseware_name:
            return ch.get("cnId")

    # 模糊匹配numberName
    for ch in chapters:
        if courseware_name.startswith(ch.get("numberName", "")):
            return ch.get("cnId")

    # 返回第一个
    return chapters[0].get("cnId")


def get_available_dates(cate_id: int, step_id: int, token: str) -> List[str]:
    """获取可排课日期"""
    result = call_tqs_api("education/demo_resource/availableDays", token, {"cateId": cate_id, "stepId": step_id})
    if result.get("code") != 200:
        return []
    return result.get("data", [])


def parse_courseware_to_stage(courseware: str) -> Optional[str]:
    """从课件名提取阶段名，如 'S4_2(A)' → 'S4'"""
    match = re.match(r'(S\d+)', courseware, re.IGNORECASE)
    return match.group(1).upper() if match else None


def standardize_language(lang: str) -> str:
    """标准化语种名"""
    lang = lang.strip()
    return LANGUAGE_ALIASES.get(lang, lang)


def get_teacher_rating(teacher_name: str, area: str = "国内") -> str:
    """查询老师评级
    
    Args:
        teacher_name: 老师昵称（不含"老师"后缀）
        area: "国内" 或 "海外"
    
    Returns:
        评级："好"/"中1"/"中2"/"差"/""（未找到）
    """
    try:
        with open(TEACHER_RATINGS_FILE, 'r', encoding='utf-8') as f:
            ratings = json.load(f)
    except Exception as e:
        logger.warning(f"读取老师评级文件失败: {e}")
        return ""
    
    area_key = "海外" if area == "海外" else "国内"
    area_ratings = ratings.get(area_key, {})
    
    # 统一去掉"老师/老師"后缀再匹配
    name_clean = teacher_name.replace("老师", "").replace("老師", "").strip()
    
    for rating, names in area_ratings.items():
        for n in names:
            n_clean = n.replace("老师", "").replace("老師", "").strip()
            if name_clean == n_clean:
                return rating
    
    return ""


def get_teacher_priority(teacher_name: str, area: str = "国内") -> int:
    """获取老师优先级分数（数值越大越优先）
    
    Args:
        teacher_name: 老师昵称
        area: 学员地区属性 "国内"/"海外"
    
    Returns:
        优先级分数，未找到评级返回0
    """
    rating = get_teacher_rating(teacher_name, area)
    return RATING_PRIORITY.get(rating, 0)


def sort_lives_by_teacher_priority(lives: list, stu_area: str = "国内") -> list:
    """按老师评级排序课节列表（好老师优先）
    
    Args:
        lives: 课节列表，每个需含 teacherName 字段
        stu_area: 学员地区属性 "国内"/"海外"
    
    Returns:
        按老师优先级降序排列的课节列表
    """
    def sort_key(live):
        teacher = live.get("teacherName", "")
        return get_teacher_priority(teacher, stu_area)
    
    return sorted(lives, key=sort_key, reverse=True)


def get_student_area(stu_id: str, token: str) -> str:
    """查询学员国内外属性
    
    Returns:
        "国内" 或 "海外"，查询失败返回 "国内"（默认国内）
    """
    try:
        result = call_member_api("ol-user/findDetailById", token, {"userId": stu_id})
        if result.get("code") == 0:
            user_area = result.get("data", {}).get("userArea", {})
            oversea = user_area.get("oversea", "国内")
            logger.info(f"学员{stu_id} 地区属性: {oversea} | 详细: {user_area}")
            return oversea
        else:
            logger.warning(f"查询学员地区失败: {result.get('msg', '未知错误')}")
    except Exception as e:
        logger.error(f"查询学员地区异常: {e}")
    return "国内"  # 默认国内


def get_cate_id(language: str, stu_id: str = "", token: str = "") -> Optional[int]:
    """根据语种+国内外属性获取DEMO课类cateId
    
    核心规则：
    - 中文/普通话 + 国内 → 数学思维DEMO (cateId=55)
    - 中文/普通话 + 海外 → 海外中文DEMO (cateId=4088)
    - 其他语种 → 按语种直接映射
    """
    std_lang = standardize_language(language)
    
    # 中文/普通话需要根据国内外判断
    if std_lang == "中文":
        if stu_id and token:
            area = get_student_area(stu_id, token)
            if area == "海外":
                logger.info(f"海外中文用户 → 海外中文DEMO cateId=4088")
                return 4088
        # 默认国内
        return LANGUAGE_CATE_MAP.get("中文")
    
    return LANGUAGE_CATE_MAP.get(std_lang)


# ==================== 意向时间解析 ====================

def parse_intended_time(time_str: str) -> Optional[Dict]:
    """解析意向时间，如 '周六-14:00' → {weekday: 5, hour: 14, minute: 0, weekday_name: '周六'}
    
    支持格式：
    - 周六-14:00 / 周六 14:00 / 周六14:00
    - 周六-14:00-15:00（取开始时间）
    """
    if not time_str:
        return None

    # 繁体转简体 + 全角标点转半角
    time_str = time_str.replace('週', '周').replace('：', ':').replace('，', ',')

    # 匹配周X + 时间
    match = re.search(r'(周[一二三四五六日天七])\s*[-—]?\s*(\d{1,2}):(\d{2})', time_str)
    if not match:
        # 尝试只匹配时间（没有周几）
        match_time = re.search(r'(\d{1,2}):(\d{2})', time_str)
        if match_time:
            return {
                "weekday": None,
                "hour": int(match_time.group(1)),
                "minute": int(match_time.group(2)),
                "weekday_name": None,
                "raw": time_str
            }
        return None

    weekday_name = match.group(1)
    hour = int(match.group(2))
    minute = int(match.group(3))

    weekday = WEEKDAY_MAP.get(weekday_name)

    return {
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
        "weekday_name": weekday_name,
        "raw": time_str
    }


def calc_next_date_for_weekday(weekday: int, hour: int = None, minute: int = None) -> str:
    """计算最近的指定周几的日期
    
    如果今天就是目标周几，且目标时间还未过，则返回今天；
    否则返回下周的同一天。
    """
    today = datetime.now()
    today_wd = today.weekday()
    days_ahead = (weekday - today_wd) % 7
    
    if days_ahead == 0:
        # 今天就是目标周几，检查时间是否已过
        if hour is not None:
            target_minutes = hour * 60 + (minute or 0)
            now_minutes = today.hour * 60 + today.minute
            if now_minutes < target_minutes:
                # 目标时间还没过，可以排今天
                pass
            else:
                days_ahead = 7  # 时间已过，排下周
        else:
            # 没有指定时间，默认排今天（保守起见还是排下周）
            # 因为不确定课节是几点，可能已经开课了
            days_ahead = 7
    
    target = today + timedelta(days=days_ahead)
    return target.strftime("%Y-%m-%d")


# ==================== 工单字段解析 ====================

def parse_field_values(detail: Dict) -> Dict:
    """解析工单fieldValues，返回结构化字段"""
    field_values = detail.get("fieldValues", [])
    field_map = {}
    for fv in field_values:
        field_id = fv.get("fieldId")
        value = fv.get("value", "")
        field_map[field_id] = value

    stu_id = field_map.get(274, "")
    special_request = field_map.get(287, "")
    language = field_map.get(1005, "")

    # 尝试从特殊诉求中提取指定老师
    teacher_id = None
    teacher_name = None
    if special_request:
        # 匹配 "指定XXX老师" 或 "老师ID:数字" 或 "老师:数字"
        tid_match = re.search(r'老师[：:]\s*(\d+)', special_request)
        if tid_match:
            teacher_id = int(tid_match.group(1))
        tname_match = re.search(r'指定\s*(\S+)\s*老师', special_request)
        if tname_match:
            teacher_name = tname_match.group(1)

    return {
        "stu_id": stu_id.strip() if stu_id else "",
        "意向时间": field_map.get(275, ""),
        "备选时间": field_map.get(276, ""),
        "原因": field_map.get(277, ""),
        "意向课件": field_map.get(278, ""),
        "是否接受同阶其他课件": field_map.get(286, "否"),
        "特殊诉求": special_request,
        "特殊语种选择": language,
        "指定老师ID": teacher_id,
        "指定老师名": teacher_name,
    }


# ==================== 核心流程 ====================

def check_fields_complete(fields: Dict) -> Tuple[bool, str]:
    """检查工单字段是否完整，返回 (是否完整, 缺失说明)"""
    missing = []
    if not fields.get("stu_id"):
        missing.append("学员ID")
    if not fields.get("意向时间"):
        missing.append("意向时间")
    if not fields.get("意向课件"):
        missing.append("意向课件")
    if not fields.get("特殊语种选择"):
        missing.append("语种")

    if missing:
        return False, f"缺少必填字段: {', '.join(missing)}"
    return True, ""


def search_demo_lives(token: str, class_date: str, hour: int = None, minute: int = None,
                      teacher_id: int = None, cate_id: int = None, step_id: int = None,
                      cn_id: int = None) -> List[Dict]:
    """查询DEMO试听课节
    
    Args:
        token: CRM token
        class_date: 上课日期 YYYY-MM-DD
        hour: 小时（可选）
        minute: 分钟（可选）
        teacher_id: 老师ID（可选）
        cate_id: 课类ID（可选，用于语种筛选）
        step_id: 阶段ID（可选，用于课件筛选）
        cn_id: 课件ID（可选，精确匹配课件）
    
    Returns:
        匹配的课节列表
    """
    params = {
        "courseType": COURSE_TYPE_DEMO,
        "liveStatus": LIVE_STATUS_PENDING,
        "classDate": [class_date, class_date],
        "page": 1,
        "limit": 50,
        "___auth___": 1,
    }

    if teacher_id:
        params["teacherId"] = [teacher_id]

    all_lives = []
    while True:
        result = call_ems_api("live/lists", token, params)
        if result.get("code") != 200:
            break

        lives = result.get("data", [])
        if not lives:
            break
        all_lives.extend(lives)
        if len(lives) < 50:
            break
        params["page"] += 1

    # 客户端过滤
    filtered = []
    for live in all_lives:
        # 时间筛选
        start_time = live.get("startTime", "")
        if hour is not None:
            try:
                parts = start_time.split(":")
                live_h = int(parts[0])
                live_m = int(parts[1]) if len(parts) > 1 else 0
                if live_h != hour or (minute is not None and live_m != minute):
                    continue
            except (ValueError, IndexError):
                continue

        # 未满班
        student_count = int(live.get("studentCount", 0))
        max_class_num = int(live.get("maxClassNum", 4))
        if student_count >= max_class_num:
            continue

        # 语种筛选（通过catePid匹配）
        if cate_id and live.get("catePid") != cate_id:
            # catePid可能是课类ID
            pass  # live/lists返回的catePid可能对应，先不过滤

        # 课件筛选（通过cnId匹配）
        if cn_id and live.get("cnId") != cn_id:
            continue

        filtered.append(live)

    return filtered


def create_demo_lesson(token: str, cate_id: int, step_id: int, cn_id: int,
                       teacher_id: int, start_time: str,
                       size: int = DEFAULT_DEMO_SIZE,
                       consume_hour: int = DEFAULT_DEMO_CONSUME_HOUR,
                       duration: int = DEFAULT_DEMO_DURATION) -> Tuple[bool, Optional[int], str]:
    """创建DEMO试听课节
    
    Args:
        token: CRM token
        cate_id: 课类ID
        step_id: 阶段ID
        cn_id: 课件ID
        teacher_id: 老师ID
        start_time: 开始时间，格式 "Y-m-d H:i:s"
        size: 班容量
        consume_hour: 消耗课时
        duration: 课程时长（分钟）
    
    Returns:
        (是否成功, liveId, 消息)
    """
    params = {
        "cateId": cate_id,
        "stepId": step_id,
        "cnId": cn_id,
        "teacherId": teacher_id,
        "startTime": start_time,
        "size": size,
        "consumeHour": consume_hour,
        "courseType": COURSE_TYPE_DEMO,
        "duration": duration,
    }

    result = call_tqs_api("education/lesson/create", token, params)

    if result.get("code") == 200:
        # 尝试从返回数据中获取liveId
        data = result.get("data", {})
        live_id = None
        if isinstance(data, dict):
            live_id = data.get("liveId") or data.get("id") or data.get("roomId")
        elif isinstance(data, int):
            live_id = data
        return True, live_id, "创建成功"
    else:
        msg = result.get("msg", "未知错误")
        return False, None, f"创建失败: {msg}"


def add_student_to_live(token: str, user_id: str, live_id: int) -> Tuple[bool, str]:
    """将学员排入课节"""
    result = call_ems_api("live_student/add", token, {"userId": int(user_id), "liveId": live_id})
    if result.get("code") == 200:
        return True, "排入成功"
    else:
        return False, result.get("msg", "排入失败")


def claim_work_order(token: str, order_id: int, handler_id: int = None) -> Tuple[bool, str]:
    """领取工单"""
    if not handler_id:
        # 使用当前登录用户的ID（陈健=从token解析）
        handler_id = 26193  # TODO: 从token动态获取

    result = call_ticket_api("POST", "/v-ticket/work-order/updateWorkOrderHandler", token, {
        "workOrderIdList": [order_id],
        "handlerList": [handler_id],
        "type": 1
    })

    if result.get("code") == 0:
        return True, "领取成功"
    else:
        return False, result.get("msg", "领取失败")


def save_follow_record(token: str, order_id: int, record: str, status: int = 8,
                       deal_status: int = 1) -> Tuple[bool, str]:
    """保存跟进记录"""
    result = call_ticket_api("POST", "/v-ticket/work-order-follow/save", token, {
        "workOrderId": order_id,
        "record": record,
        "status": status,
        "dealStatus": deal_status,
    })
    if result.get("code") == 0:
        return True, "保存成功"
    else:
        return False, result.get("msg", "保存失败")


def save_solution(token: str, order_id: int, solution: str) -> Tuple[bool, str]:
    """保存解决方案"""
    result = call_ticket_api("POST", "/v-ticket/work-order/saveSolution", token, {
        "workOrderId": order_id,
        "solution": solution,
    })
    if result.get("code") == 0:
        return True, "保存成功"
    else:
        return False, result.get("msg", "保存失败")


def close_work_order(token: str, order_id: int) -> Tuple[bool, str]:
    """关闭工单"""
    result = call_ticket_api("POST", "/v-ticket/work-order/close", token, {
        "workOrderIds": [order_id]
    })
    if result.get("code") == 0:
        return True, "关闭成功"
    else:
        return False, result.get("msg", "关闭失败")


# ==================== 钉钉通知 ====================

def send_dingtalk_message(message: str) -> bool:
    """发送钉钉群消息"""
    try:
        data = {
            "msgtype": "text",
            "text": {"content": f"【DEMO工单】\n{message}"}
        }
        resp = requests.post(DINGTALK_WEBHOOK_URL, json=data, timeout=10)
        result = resp.json()
        return result.get("errcode") == 0
    except Exception as e:
        logger.error(f"钉钉通知发送失败: {e}")
        return False


# ==================== 主流程 ====================

def auto_process_order(order: Dict, token: str) -> Dict:
    """自动处理单个DEMO绿色通道工单（主入口）
    
    返回:
        {
            "action": "auto_processed" | "skipped" | "error",
            "order_id": int,
            "scenario": str,  # A/B/C/skip_xxx
            "message": str,
            "detail": dict
        }
    """
    order_id = order.get("id")
    result = {"order_id": order_id, "action": "error", "scenario": "", "message": "", "detail": {}}

    logger.info(f"开始处理工单 {order_id}")

    # 1. 获取工单详情（含fieldValues）
    detail = call_ticket_api("GET", f"/v-ticket/work-order/detail?id={order_id}", token)
    if detail.get("code") != 0:
        result["message"] = f"获取工单详情失败: {detail.get('msg')}"
        return result

    order_data = detail.get("data", {})
    fields = parse_field_values(order_data)

    # 2. 检查字段完整性
    complete, missing = check_fields_complete(fields)
    if not complete:
        result["action"] = "skipped"
        result["scenario"] = "skip_incomplete"
        result["message"] = missing
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n原因: {missing}\n请人工领取处理"
        )
        return result

    # 3. 解析关键字段
    stu_id = fields["stu_id"]
    intended_time_str = fields["意向时间"]
    alt_time_str = fields["备选时间"]
    courseware = fields["意向课件"]
    language = fields["特殊语种选择"]
    accept_other = fields["是否接受同阶其他课件"] == "是"
    teacher_id = fields["指定老师ID"]
    teacher_name = fields["指定老师名"]

    # 3.5 前置过滤：只自动处理海外学员，国内学员留在待分配
    stu_area = get_student_area(stu_id, token)
    if stu_area == "国内":
        result["action"] = "skipped"
        result["scenario"] = "skip_domestic"
        result["message"] = f"国内学员，留在待分配由人工处理"
        logger.info(f"工单 {order_id}: 国内学员(stu_id={stu_id})，跳过自动处理")
        return result

    logger.info(f"工单 {order_id}: 学员={stu_id}, 地区={stu_area}, 时间={intended_time_str}, 课件={courseware}, "
                f"语种={language}, 指定老师={'ID:'+str(teacher_id) if teacher_id else '无'}")

    # 4. 解析意向时间
    intended_time = parse_intended_time(intended_time_str)
    alt_time = parse_intended_time(alt_time_str) if alt_time_str else None

    if not intended_time:
        result["action"] = "skipped"
        result["scenario"] = "skip_time_parse"
        result["message"] = f"意向时间格式无法解析: {intended_time_str}"
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n原因: 意向时间格式无法解析 '{intended_time_str}'\n请人工领取处理"
        )
        return result

    # 5. 解析课件 → 阶段名 + cateId + stepId
    stage_name = parse_courseware_to_stage(courseware)
    if not stage_name:
        result["action"] = "skipped"
        result["scenario"] = "skip_courseware_parse"
        result["message"] = f"课件名无法解析阶段: {courseware}"
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n原因: 课件名无法解析阶段 '{courseware}'\n请人工领取处理"
        )
        return result

    cate_id = get_cate_id(language, stu_id, token)
    if not cate_id:
        result["action"] = "skipped"
        result["scenario"] = "skip_language"
        result["message"] = f"语种无法映射课类: {language}"
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n原因: 语种 '{language}' 无法映射课类\n请人工领取处理"
        )
        return result

    step_id = get_step_id(cate_id, stage_name, token)
    if not step_id:
        result["action"] = "skipped"
        result["scenario"] = "skip_step_id"
        result["message"] = f"阶段 {stage_name} 在课类 {cate_id} 中未找到"
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n原因: 阶段 {stage_name} 未找到\n请人工领取处理"
        )
        return result

    cn_id = get_cn_id(cate_id, step_id, courseware, token)

    # 6. 计算目标日期
    time_list = [intended_time]
    if alt_time:
        time_list.append(alt_time)

    # 尝试意向时间和备选时间
    matched_live = None
    matched_time_info = None

    # stu_area 已在前置过滤时获取，直接用于老师优先级匹配

    for t_info in time_list:
        if t_info.get("weekday") is not None:
            target_date = calc_next_date_for_weekday(t_info["weekday"], t_info.get("hour"), t_info.get("minute"))
        else:
            # 没有周几信息，无法确定日期
            continue

        # 7. 查课节
        lives = search_demo_lives(
            token=token,
            class_date=target_date,
            hour=t_info.get("hour"),
            minute=t_info.get("minute"),
            teacher_id=teacher_id,
            cn_id=cn_id,
            cate_id=cate_id,
        )

        if lives:
            # 按老师评级排序：好老师优先（地区属性一致 > 好老师优先级）
            lives = sort_lives_by_teacher_priority(lives, stu_area)
            matched_live = lives[0]  # 取优先级最高的
            matched_time_info = t_info
            break

    # ---- 场景判断 ----

    if matched_live:
        # 场景A/B：有匹配课节，直接排入
        scenario = "B" if teacher_id else "A"
        logger.info(f"工单 {order_id}: 场景{scenario} - 找到匹配课节 liveId={matched_live.get('liveId')}")

        # 领取工单
        ok, msg = claim_work_order(token, order_id)
        if not ok:
            result["message"] = f"领取工单失败: {msg}"
            return result

        # 排入学员
        live_id = matched_live.get("liveId")
        ok, msg = add_student_to_live(token, stu_id, live_id)
        if not ok:
            result["message"] = f"排入学员失败: {msg}"
            # 领取了但排入失败，写跟进记录
            save_follow_record(token, order_id, f"[自动处理] 排入学员失败: {msg}", status=7, deal_status=2)
            return result

        # 写跟进记录
        teacher_info = f"老师{teacher_name}(ID:{teacher_id})" if teacher_id else "系统匹配"
        record = (f"[自动处理] 场景{scenario}: 学员{stu_id}已排入课节{live_id}\n"
                  f"时间: {target_date} {matched_time_info.get('hour','')}:{matched_time_info.get('minute',''):02d}\n"
                  f"课件: {courseware} | {teacher_info}")
        save_follow_record(token, order_id, record)

        # 保存解决方案
        save_solution(token, order_id, f"已自动排课: 课节ID {live_id}")

        # 关闭工单
        close_work_order(token, order_id)

        result["action"] = "auto_processed"
        result["scenario"] = scenario
        result["message"] = f"场景{scenario}处理完成: 学员{stu_id}排入课节{live_id}"
        result["detail"] = {"live_id": live_id, "class_date": target_date}

        # 通知
        send_dingtalk_message(
            f"✅ 工单 {order_id} 已自动处理完成\n"
            f"场景{scenario}: 学员{stu_id}排入课节{live_id}\n"
            f"时间: {target_date} {matched_time_info.get('hour','')}:{matched_time_info.get('minute',''):02d}\n"
            f"课件: {courseware}"
        )
        return result

    # 没有匹配课节
    if not teacher_id:
        # 无指定老师 + 查不到 → 交人工
        result["action"] = "skipped"
        result["scenario"] = "skip_no_teacher_no_live"
        result["message"] = "无指定老师且无匹配课节，无法自动新建"
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n"
            f"原因: 无指定老师且无匹配课节\n"
            f"学员: {stu_id} | 课件: {courseware} | 时间: {intended_time_str}\n"
            f"请人工领取处理"
        )
        return result

    # 场景C：有指定老师，尝试新建课节
    if not intended_time.get("weekday") or not cn_id:
        result["action"] = "skipped"
        result["scenario"] = "skip_cannot_create"
        result["message"] = f"无法新建课节: weekday={intended_time.get('weekday')}, cnId={cn_id}"
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n"
            f"原因: 信息不足无法新建课节\n"
            f"请人工领取处理"
        )
        return result

    # 计算startTime
    start_datetime = f"{target_date} {intended_time['hour']:02d}:{intended_time['minute']:02d}:00"

    # 先创建课节，成功后再领取工单（避免创建失败但工单已被领取卡住）
    ok, new_live_id, msg = create_demo_lesson(
        token=token,
        cate_id=cate_id,
        step_id=step_id,
        cn_id=cn_id,
        teacher_id=teacher_id,
        start_time=start_datetime,
    )

    if not ok:
        # 创建失败 → 不领取工单，直接跳过交人工
        result["action"] = "skipped"
        result["scenario"] = "skip_create_lesson_failed"
        result["message"] = f"新建课节失败: {msg}"
        send_dingtalk_message(
            f"📋 工单 {order_id} 无法自动处理\n"
            f"原因: 新建课节失败 - {msg}\n"
            f"学员: {stu_id} | 课件: {courseware} | 时间: {intended_time_str}\n"
            f"请人工领取处理"
        )
        return result

    # 创建课节成功，再领取工单
    ok, msg = claim_work_order(token, order_id)
    if not ok:
        result["message"] = f"课节已创建但领取工单失败: {msg}，课节{new_live_id}可能需要人工处理"
        send_dingtalk_message(
            f"⚠️ 工单 {order_id} 课节已创建(liveId={new_live_id})但领取失败: {msg}\n"
            f"请人工领取工单并排入学员"
        )
        return result

    # 创建成功，获取liveId
    if not new_live_id:
        # 没返回liveId，需要查询刚创建的课节
        lives = search_demo_lives(
            token=token, class_date=target_date,
            hour=intended_time.get("hour"), minute=intended_time.get("minute"),
            teacher_id=teacher_id, cn_id=cn_id,
        )
        if lives:
            new_live_id = lives[0].get("liveId")
        else:
            # 等一秒再查
            time.sleep(1)
            lives = search_demo_lives(
                token=token, class_date=target_date,
                hour=intended_time.get("hour"), minute=intended_time.get("minute"),
                teacher_id=teacher_id,
            )
            if lives:
                new_live_id = lives[0].get("liveId")

    if not new_live_id:
        result["message"] = "新建课节成功但无法获取liveId"
        save_follow_record(token, order_id, f"[自动处理] 新建课节成功但无法获取liveId，请手动排入", status=7, deal_status=2)
        return result

    # 排入学员
    ok, msg = add_student_to_live(token, stu_id, new_live_id)
    if not ok:
        result["message"] = f"新建课节成功但排入失败: {msg}"
        save_follow_record(token, order_id, f"[自动处理] 新建课节{new_live_id}成功但排入学员失败: {msg}", status=7, deal_status=2)
        return result

    # 写跟进记录
    record = (f"[自动处理] 场景C: 新建课节{new_live_id}并排入学员{stu_id}\n"
              f"时间: {start_datetime} | 老师: {teacher_name or ''}(ID:{teacher_id})\n"
              f"课件: {courseware}")
    save_follow_record(token, order_id, record)
    save_solution(token, order_id, f"已自动排课: 新建课节ID {new_live_id}")
    close_work_order(token, order_id)

    result["action"] = "auto_processed"
    result["scenario"] = "C"
    result["message"] = f"场景C处理完成: 新建课节{new_live_id}，学员{stu_id}已排入"
    result["detail"] = {"live_id": new_live_id, "class_date": target_date, "start_time": start_datetime}

    send_dingtalk_message(
        f"✅ 工单 {order_id} 已自动处理完成\n"
        f"场景C: 新建课节并排入学员\n"
        f"课节ID: {new_live_id} | 学员: {stu_id}\n"
        f"时间: {start_datetime}\n"
        f"老师: {teacher_name or ''}(ID:{teacher_id})\n"
        f"课件: {courseware}"
    )
    return result


# ==================== 批量处理入口 ====================

def scan_and_process(token: str = None, dry_run: bool = False) -> List[Dict]:
    """扫描待分配工单并自动处理
    
    Args:
        token: CRM token（不传则自动加载）
        dry_run: 只扫描不执行（预览模式）
    
    Returns:
        处理结果列表
    """
    if not token:
        token = load_token()
    if not token:
        logger.error("无法加载Token")
        return []

    # 查询待分配的DEMO绿色通道工单
    all_orders = []
    page = 1
    while True:
        params = {
            "page": page,
            "limit": 50,
            "relateMe": 7,  # 7=查所有工单（0会返回网络异常）
            "workOrderTypeId": DEMO_GREEN_CHANNEL_TYPE_ID,
            "status": 4,  # 未分配
        }
        result = call_ticket_api("POST", "/v-ticket/work-order/allWorkOrderList", token, params)
        if result.get("code") != 0:
            break
        orders = result.get("data", [])
        if not orders:
            break
        all_orders.extend(orders)
        if len(orders) < 50:
            break
        page += 1

    logger.info(f"扫描到 {len(all_orders)} 个待分配DEMO绿色通道工单")

    results = []
    for order in all_orders:
        order_id = order.get("id")
        create_time = order.get("createTime", "")

        # 只处理3天内的工单
        if create_time:
            try:
                create_dt = datetime.strptime(create_time, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - create_dt > timedelta(days=3):
                    continue
            except ValueError:
                pass

        if dry_run:
            # 预览模式：只解析不执行
            detail = call_ticket_api("GET", f"/v-ticket/work-order/detail?id={order_id}", token)
            if detail.get("code") == 0:
                fields = parse_field_values(detail.get("data", {}))
                complete, missing = check_fields_complete(fields)
                results.append({
                    "order_id": order_id,
                    "fields": fields,
                    "can_auto": complete,
                    "reason": missing if not complete else "可自动处理",
                })
        else:
            r = auto_process_order(order, token)
            results.append(r)

    return results


# ==================== 测试入口 ====================

if __name__ == "__main__":
    import sys
    print("=" * 50)
    print("DEMO工单自动处理器 - 测试模式")
    print("=" * 50)

    token = load_token()
    if not token:
        print("❌ 无法加载Token")
        sys.exit(1)

    if len(sys.argv) > 1:
        # 处理指定工单
        order_id = int(sys.argv[1])
        print(f"\n处理工单: {order_id}")
        result = auto_process_order({"id": order_id}, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 预览模式
        print("\n预览待处理工单（dry_run模式，不执行任何操作）...")
        results = scan_and_process(token, dry_run=True)
        for r in results:
            status = "✅可自动" if r.get("can_auto") else f"❌{r.get('reason')}"
            print(f"  工单{r['order_id']}: {status}")
            if not r.get("can_auto"):
                fields = r.get("fields", {})
                print(f"    学员={fields.get('stu_id','')} 时间={fields.get('意向时间','')} "
                      f"课件={fields.get('意向课件','')} 语种={fields.get('特殊语种选择','')}")
