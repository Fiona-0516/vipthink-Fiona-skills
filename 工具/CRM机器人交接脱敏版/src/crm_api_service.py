#!/usr/bin/env python3
"""
CRM API Service - FastAPI轻量服务
为企微机器人提供HTTP接口访问CRM功能
Token管理与钉钉机器人共享
"""

import os
import sys
from pathlib import Path

# 添加当前目录到Python路径，确保能导入crm_query
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from fastapi import FastAPI, HTTPException, Query, Depends, Security
from fastapi.responses import PlainTextResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# 导入CRM查询模块
import crm_query
from crm_query import (
    get_stage_id, query_classes, filter_insertable_classes,
    set_insertable, set_makeup, parse_token_expiry,
    query_classes_by_teacher, batch_set_insertable,
    resolve_class_query
)

# Token文件路径
TOKEN_FILE = current_dir / "crm_token.json"
API_KEY_FILE = current_dir / "api_key.txt"

app = FastAPI(
    title="CRM API Service",
    description="为企微机器人提供CRM功能接口",
    version="1.0.0"
)

# API Key验证
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def load_api_key() -> str:
    """加载API Key"""
    try:
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    except:
        return ""

async def verify_api_key(api_key: str = Security(api_key_header)):
    """验证API Key（如果没有配置key则跳过验证）"""
    stored_key = load_api_key()
    if stored_key and api_key != stored_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True


# ==================== Token管理 ====================

def load_token() -> str:
    """从文件加载Token"""
    try:
        import json
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("token", "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载Token失败: {str(e)}")


def check_token() -> tuple:
    """检查Token是否有效
    
    Returns:
        (is_valid, token, message)
    """
    try:
        token = load_token()
        if not token:
            return False, None, "Token为空"
        
        expiry = parse_token_expiry(token)
        if not expiry:
            return True, token, "Token有效（无法解析过期时间）"
        
        now = datetime.now()
        if expiry <= now:
            return False, None, f"Token已过期，过期时间: {expiry}"
        
        # Token剩余有效期小于1小时，标记为即将过期
        hours_left = (expiry - now).total_seconds() / 3600
        if hours_left < 1:
            return True, token, f"Token即将过期，剩余{minutes_left:.0f}分钟"
        
        return True, token, f"Token有效，过期时间: {expiry}"
    except Exception as e:
        return False, None, f"Token检查失败: {str(e)}"


# ==================== 统一响应格式 ====================

def success_response(data=None, msg="成功"):
    """成功响应"""
    return {"code": 200, "msg": msg, "data": data}


def error_response(msg="操作失败", code=400, data=None):
    """错误响应"""
    return {"code": code, "msg": msg, "data": data}


# ==================== API路由 ====================

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return success_response({"status": "running", "timestamp": datetime.now().isoformat()})


@app.get("/api/token/status", dependencies=[Depends(verify_api_key)])
async def token_status():
    """获取Token状态"""
    is_valid, token, message = check_token()
    
    if not token:
        return error_response(message, code=401)
    
    # 解析Token详情
    expiry = parse_token_expiry(token)
    now = datetime.now()
    
    # 判断Token类型
    try:
        import base64
        import json
        parts = token.split('.')
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        token_type = payload[1].get("type", "unknown") if isinstance(payload, list) else payload.get("type", "unknown")
        uid = payload[1].get("uid", "unknown") if isinstance(payload, list) else payload.get("uid", "unknown")
    except:
        token_type = "unknown"
        uid = "unknown"
    
    hours_left = (expiry - now).total_seconds() / 3600 if expiry else 0
    minutes_left = (expiry - now).total_seconds() / 60 if expiry else 0
    
    return success_response({
        "valid": is_valid,
        "expiry": expiry.isoformat() if expiry else None,
        "expires_in_hours": round(hours_left, 2) if hours_left > 0 else 0,
        "expires_in_minutes": round(minutes_left, 0) if minutes_left > 0 else 0,
        "type": token_type,
        "uid": uid,
        "message": message
    })


class ClassIdRequest(BaseModel):
    """班级ID请求"""
    class_id: int


# 课类英文到中文映射
COURSE_TYPE_MAP = {
    "english": "英语",
    "cantonese": "粤语",
    "taiwan": "台湾",
    "mandarin": "普通话",
    "bilingual": "中英",
    "英语": "英语",
    "粤语": "粤语",
    "台湾": "台湾",
    "普通话": "普通话",
    "中英": "中英",
}


@app.get("/api/classes/v2", dependencies=[Depends(verify_api_key)])
async def query_classes_v2(
    language: str = Query(..., description="语种: 普通话/英语/粤语/台湾/中英（支持别名：国语/英文/广东话/台/双语等）"),
    stage: str = Query(..., description="阶段，如：S2, S3, S9 或 2, 3, 9"),
    time_filter: Optional[str] = Query(None, description="时间筛选：精确时间如20:10；时间段如晚上、上午；范围如18:00以后"),
    weekday_filter: Optional[str] = Query(None, description="周期筛选：工作日、周末、周一、周一到周四等")
):
    """统一语种×阶段查班接口
    
    自动路由到正确的课类+语种组合：
    - 普通话 → 无后缀课类 + lanId=90
    - 台湾 S1-S6 → 台湾课类；S7+ → 粤语课类/无后缀 + lanId=90
    - 英语/粤语 → 对应课类 + lanId；超出范围走无后缀
    - 中英 → 无后缀课类 + lanId=91
    """
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    # 统一路由
    resolved = resolve_class_query(language, stage)
    if not resolved:
        return error_response(f"无法匹配语种「{language}」+阶段「{stage}」，请检查输入")
    
    # 查询班级（中英班需多课类合并）
    cst = 0 if resolved.get("show_locked") else 1
    _multi_cate = resolved.get("cate_sids", [])
    if _multi_cate:
        _seen = set()
        classes = []
        for _cs in _multi_cate:
            _cls = query_classes(token, _cs["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
            if _cls:
                for c in _cls:
                    if c.get("id") not in _seen:
                        _seen.add(c.get("id"))
                        classes.append(c)
    else:
        classes = query_classes(token, resolved["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
    
    # 解析时间范围
    from crm_query import parse_time_range
    time_range = parse_time_range(time_filter) if time_filter else None
    
    # 筛选可插班班级
    valid_classes = filter_insertable_classes(
        classes,
        course_type=resolved["language"],
        time_filter="",
        weekday_filter=weekday_filter or "",
        time_range=time_range,
        token=token
    )
    
    return success_response({
        "total": len(valid_classes),
        "language": resolved["language"],
        "stage": resolved["stage"],
        "course_type": resolved["course_type"],
        "cate_sid": resolved["cate_sid"],
        "lan_id": resolved["lan_id"],
        "classes": valid_classes
    })


@app.get("/api/classes/v2/text", dependencies=[Depends(verify_api_key)])
async def query_classes_v2_text(
    language: str = Query(..., description="语种: 普通话/英语/粤语/台湾/中英"),
    stage: str = Query(..., description="阶段，如：S2, S3, S9"),
    time_filter: Optional[str] = Query(None, description="时间筛选"),
    weekday_filter: Optional[str] = Query(None, description="周期筛选")
):
    """统一语种×阶段查班接口（文本格式返回）"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    resolved = resolve_class_query(language, stage)
    if not resolved:
        return error_response(f"无法匹配语种「{language}」+阶段「{stage}」")
    
    # 查询班级（中英班需多课类合并）
    cst = 0 if resolved.get("show_locked") else 1
    _multi_cate = resolved.get("cate_sids", [])
    if _multi_cate:
        _seen = set()
        classes = []
        for _cs in _multi_cate:
            _cls = query_classes(token, _cs["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
            if _cls:
                for c in _cls:
                    if c.get("id") not in _seen:
                        _seen.add(c.get("id"))
                        classes.append(c)
    else:
        classes = query_classes(token, resolved["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
    
    from crm_query import parse_time_range
    time_range = parse_time_range(time_filter) if time_filter else None
    
    filtered = filter_insertable_classes(
        classes,
        course_type=resolved["language"],
        time_filter="",
        weekday_filter=weekday_filter or "",
        time_range=time_range,
        token=token
    )
    
    lines = [f"【{resolved['language']} {resolved['stage']} 可插班班级】(课类:{resolved['course_type']} lanId:{resolved['lan_id']}) 共{len(filtered)}个："]
    for i, c in enumerate(filtered, 1):
        lines.append(f"{i}. 班级ID:{c.get('id')} | {c.get('teacher_tag','')} | {c.get('teacher','')} | {c.get('week','')} | 在读{c.get('student_count',0)}/{c.get('max_num',0)} | 剩余{c.get('remain',0)} | 首讲:{c.get('next_date','')}")
    
    if not filtered:
        lines.append("暂无可插班班级")
    
    return {
        "code": 200,
        "msg": "成功",
        "total": len(filtered),
        "language": resolved["language"],
        "stage": resolved["stage"],
        "course_type": resolved["course_type"],
        "class_list": "\n".join(lines)
    }

@app.get("/api/classes", dependencies=[Depends(verify_api_key)])
async def query_classes_api(
    course_type: str = Query(..., description="课类: english/cantonese/taiwan（也支持中文：英语/粤语/台湾）"),
    stage: str = Query(..., description="阶段，如：S1, S2, S3"),
    time_filter: Optional[str] = Query(None, description="时间筛选，支持多种格式：精确时间如20:10；时间段如晚上、上午、下午；时间范围如18:00以后、16:00-20:00"),
    weekday_filter: Optional[str] = Query(None, description="周期筛选，支持：工作日、周末、周一、周一到周四、周五/周日等组合，用/或逗号分隔多个")
):
    """查询可插班班级"""
    # 英文参数映射为中文
    course_type = COURSE_TYPE_MAP.get(course_type.lower(), course_type)
    
    # 检查Token
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    # 获取阶段ID
    stage_id = get_stage_id(course_type, stage)
    if not stage_id:
        return error_response(f"未找到课类「{course_type}」阶段「{stage}」的ID")
    
    # 查询班级
    classes = query_classes(token, stage_id)
    
    # 解析时间范围
    from crm_query import parse_time_range
    time_range = parse_time_range(time_filter) if time_filter else None
    
    # 筛选可插班班级
    valid_classes = filter_insertable_classes(
        classes, 
        course_type=course_type,
        time_filter="",
        weekday_filter=weekday_filter or "",
        time_range=time_range,
        token=token
    )
    
    return success_response({
        "total": len(valid_classes),
        "course_type": course_type,
        "stage": stage,
        "classes": valid_classes
    })


@app.get("/api/classes/text", dependencies=[Depends(verify_api_key)])
async def query_classes_text_api(
    course_type: str = Query(..., description="课类: english/cantonese/taiwan（也支持中文：英语/粤语/台湾）"),
    stage: str = Query(..., description="阶段，如：S1, S2, S3"),
    time_filter: Optional[str] = Query(None, description="时间筛选，支持多种格式：精确时间如20:10；时间段如晚上、上午、下午；时间范围如18:00以后、16:00-20:00"),
    weekday_filter: Optional[str] = Query(None, description="周期筛选，支持：工作日、周末、周一、周一到周四、周五/周日等组合，用/或逗号分隔多个")
):
    """查询可插班班级（文本格式，便于AI阅读）"""
    # 英文参数映射为中文
    course_type = COURSE_TYPE_MAP.get(course_type.lower(), course_type)
    
    # 检查Token
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return {"code": 401, "msg": f"查询失败：{message}", "data": None}
    
    # 获取阶段ID
    stage_id = get_stage_id(course_type, stage)
    if not stage_id:
        return {"code": 404, "msg": f"未找到课类「{course_type}」阶段「{stage}」的ID", "data": None}
    
    # 查询班级
    classes = query_classes(token, stage_id)
    
    # 解析时间范围
    from crm_query import parse_time_range
    time_range = parse_time_range(time_filter) if time_filter else None
    
    # 筛选可插班班级
    valid_classes = filter_insertable_classes(
        classes, 
        course_type=course_type,
        time_filter="",
        weekday_filter=weekday_filter or "",
        time_range=time_range,
        token=token
    )
    
    # 生成文本描述
    lines = [f"【{course_type} {stage} 可插班班级】共{len(valid_classes)}个："]
    for i, c in enumerate(valid_classes, 1):
        chapter = c.get('next_chapter', '')
        chapter_info = f" | 讲次:{chapter}" if chapter else ""
        lines.append(f"{i}. 班级ID:{c.get('id','')} | {c.get('week','')} | 在读{c.get('student_count','')}/{c.get('max_num','')} | 剩余{c.get('remain','')} | 首讲:{c.get('next_date','')}")
    
    if not valid_classes:
        lines.append("暂无可插班班级")
    
    return {
        "code": 200,
        "msg": "成功",
        "total": len(valid_classes),
        "course_type": course_type,
        "stage": stage,
        "class_list": "\n".join(lines)
    }


@app.post("/api/class/unlock", dependencies=[Depends(verify_api_key)])
async def unlock_class(req: ClassIdRequest):
    """解锁班级（允许插班）"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    result = set_insertable(token, str(req.class_id), allow=True)
    if result["success"]:
        return success_response({"class_id": req.class_id}, result["msg"])
    else:
        return error_response(result["msg"])


@app.post("/api/class/lock", dependencies=[Depends(verify_api_key)])
async def lock_class(req: ClassIdRequest):
    """锁班（禁止插班）"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    result = set_insertable(token, str(req.class_id), allow=False)
    if result["success"]:
        return success_response({"class_id": req.class_id}, result["msg"])
    else:
        return error_response(result["msg"])


@app.post("/api/class/allow-makeup", dependencies=[Depends(verify_api_key)])
async def allow_makeup(req: ClassIdRequest):
    """允许补课"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    result = set_makeup(token, str(req.class_id), allow=True)
    if result["success"]:
        return success_response({"class_id": req.class_id}, result["msg"])
    else:
        return error_response(result["msg"])


@app.post("/api/class/disallow-makeup", dependencies=[Depends(verify_api_key)])
async def disallow_makeup(req: ClassIdRequest):
    """禁止补课"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    result = set_makeup(token, str(req.class_id), allow=False)
    if result["success"]:
        return success_response({"class_id": req.class_id}, result["msg"])
    else:
        return error_response(result["msg"])


class TeacherRequest(BaseModel):
    """老师批量操作请求"""
    teacher_name: str
    course_type: Optional[str] = None


@app.post("/api/teacher/unlock", dependencies=[Depends(verify_api_key)])
async def teacher_unlock(req: TeacherRequest):
    """按老师解锁（批量）"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    # 查询该老师的锁班（禁止插班的班级）
    locked_classes = query_classes_by_teacher(
        token, req.teacher_name, req.course_type, class_stu_type=0
    )
    
    if not locked_classes:
        return success_response({
            "teacher": req.teacher_name,
            "course_type": req.course_type,
            "affected": 0,
            "message": f"未找到「{req.teacher_name}」的锁班"
        })
    
    # 提取班级ID
    class_ids = [c["classId"] for c in locked_classes]
    
    # 批量解锁
    result = batch_set_insertable(token, class_ids, allow=True)
    
    return success_response({
        "teacher": req.teacher_name,
        "course_type": req.course_type,
        "total_locked": len(class_ids),
        "success": result["success"],
        "failed": result["failed"],
        "failed_ids": result["failed_ids"]
    }, f"解锁「{req.teacher_name}」{result['success']}个班级")


@app.post("/api/teacher/lock", dependencies=[Depends(verify_api_key)])
async def teacher_lock(req: TeacherRequest):
    """按老师锁班（批量）"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    # 查询该老师的解锁班（允许插班的班级）
    unlocked_classes = query_classes_by_teacher(
        token, req.teacher_name, req.course_type, class_stu_type=1
    )
    
    if not unlocked_classes:
        return success_response({
            "teacher": req.teacher_name,
            "course_type": req.course_type,
            "affected": 0,
            "message": f"未找到「{req.teacher_name}」的解锁班"
        })
    
    # 提取班级ID
    class_ids = [c["classId"] for c in unlocked_classes]
    
    # 批量锁定
    result = batch_set_insertable(token, class_ids, allow=False)
    
    return success_response({
        "teacher": req.teacher_name,
        "course_type": req.course_type,
        "total_unlocked": len(class_ids),
        "success": result["success"],
        "failed": result["failed"],
        "failed_ids": result["failed_ids"]
    }, f"锁定「{req.teacher_name}」{result['success']}个班级")


# ==================== 排课相关API ====================

import httpx

CRM_BASE_URL = "https://ems.vipthink.cn/gateway/route__jw/api"
CRM_WORK_URL = "https://ems.vipthink.cn/gateway/route__jw/work"


# ==================== 万能统一接口 ====================

class CommandRequest(BaseModel):
    """万能命令请求"""
    command: str  # 操作类型: query/preview/enroll/remove/unlock/lock/allow_makeup/disallow_makeup/teacher_unlock/teacher_lock
    course_type: Optional[str] = None  # 课类: english/cantonese/taiwan（query时必填）
    stage: Optional[str] = None  # 阶段: S1-S7（query时必填）
    time_filter: Optional[str] = None  # 时间筛选
    weekday_filter: Optional[str] = None  # 星期筛选
    class_id: Optional[str] = None  # 班级ID（排课/锁班等操作必填）
    user_id: Optional[str] = None  # 学员ID（排课/移出操作必填）
    teacher_name: Optional[str] = None  # 老师名称（按老师操作时必填）


@app.post("/api/command", dependencies=[Depends(verify_api_key)])
async def crm_command(req: CommandRequest):
    """CRM统一操作接口：通过command参数指定操作类型，所有操作走一个入口
    
    支持的command:
    - query: 查询可插班班级（需要course_type、stage）
    - preview: 预览排课信息（需要class_id、user_id）
    - enroll: 执行排课（需要class_id、user_id）
    - remove: 移出学员（需要class_id、user_id）
    - unlock: 解锁班级（需要class_id）
    - lock: 锁班（需要class_id）
    - allow_makeup: 允许补课（需要class_id）
    - disallow_makeup: 禁止补课（需要class_id）
    - teacher_unlock: 按老师解锁（需要teacher_name）
    - teacher_lock: 按老师锁班（需要teacher_name）
    """
    logger.info(f"[CRM COMMAND] command={req.command}, course_type={req.course_type}, stage={req.stage}, time_filter={req.time_filter}, weekday_filter={req.weekday_filter}, class_id={req.class_id}, user_id={req.user_id}")
    cmd = req.command.lower().strip()
    
    if cmd == "query":
        if not req.course_type or not req.stage:
            return error_response("query操作需要course_type和stage参数")
        # 复用现有查询逻辑
        return await _query_classes_internal(req.course_type, req.stage, req.time_filter, req.weekday_filter)
    
    elif cmd == "preview":
        if not req.class_id or not req.user_id:
            return error_response("preview操作需要class_id和user_id参数")
        enroll_req = EnrollRequest(class_id=req.class_id, user_id=req.user_id)
        return await enroll_preview(enroll_req)
    
    elif cmd == "enroll":
        if not req.class_id or not req.user_id:
            return error_response("enroll操作需要class_id和user_id参数")
        enroll_req = EnrollRequest(class_id=req.class_id, user_id=req.user_id)
        return await enroll_execute(enroll_req)
    
    elif cmd == "remove":
        if not req.class_id or not req.user_id:
            return error_response("remove操作需要class_id和user_id参数")
        remove_req = RemoveRequest(class_id=req.class_id, user_id=req.user_id)
        return await enroll_remove(remove_req)
    
    elif cmd == "unlock":
        if not req.class_id:
            return error_response("unlock操作需要class_id参数")
        return await _class_operation_internal(req.class_id, "unlock")
    
    elif cmd == "lock":
        if not req.class_id:
            return error_response("lock操作需要class_id参数")
        return await _class_operation_internal(req.class_id, "lock")
    
    elif cmd == "allow_makeup":
        if not req.class_id:
            return error_response("allow_makeup操作需要class_id参数")
        return await _class_operation_internal(req.class_id, "allow_makeup")
    
    elif cmd == "disallow_makeup":
        if not req.class_id:
            return error_response("disallow_makeup操作需要class_id参数")
        return await _class_operation_internal(req.class_id, "disallow_makeup")
    
    elif cmd == "teacher_unlock":
        if not req.teacher_name:
            return error_response("teacher_unlock操作需要teacher_name参数")
        return await _teacher_operation_internal(req.teacher_name, "unlock")
    
    elif cmd == "teacher_lock":
        if not req.teacher_name:
            return error_response("teacher_lock操作需要teacher_name参数")
        return await _teacher_operation_internal(req.teacher_name, "lock")
    
    else:
        return error_response(f"未知操作类型: {cmd}，支持: query/preview/enroll/remove/unlock/lock/allow_makeup/disallow_makeup/teacher_unlock/teacher_lock")


async def _query_classes_internal(course_type: str, stage: str, time_filter: str = None, weekday_filter: str = None):
    """内部查班方法 - 复用现有接口的逻辑"""
    # 英文参数映射为中文
    course_type = COURSE_TYPE_MAP.get(course_type.lower(), course_type)
    
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    resolved = resolve_class_query(course_type, stage)
    if not resolved:
        return error_response(f"无法匹配语种「{course_type}」+阶段「{stage}」")
    
    # 查询班级（中英班需多课类合并）
    _multi_cate = resolved.get("cate_sids", [])
    if _multi_cate:
        _seen = set()
        classes = []
        for _cs in _multi_cate:
            _cls = query_classes(token, _cs["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=1)
            if _cls:
                for c in _cls:
                    if c.get("id") not in _seen:
                        _seen.add(c.get("id"))
                        classes.append(c)
    else:
        classes = query_classes(token, resolved["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=1)
    
    from crm_query import parse_time_range
    time_range = parse_time_range(time_filter) if time_filter else None
    filtered = filter_insertable_classes(
        classes,
        course_type=resolved["language"],
        time_filter="",
        weekday_filter=weekday_filter or "",
        time_range=time_range,
        token=token
    )
    
    # 限制返回条数，避免响应体过大导致企微智能体平台超时
    MAX_RETURN = 15
    display_classes = filtered[:MAX_RETURN]
    has_more = len(filtered) > MAX_RETURN
    
    lines = [f"【{course_type} {stage} 可插班班级】共{len(filtered)}个："]
    for i, c in enumerate(display_classes, 1):
        lines.append(f"{i}. ID:{c.get('id')} | {c.get('teacher_tag','')} | {c.get('teacher','')} | {c.get('week','')} | 在读{c.get('student_count',0)}/{c.get('max_num',0)} | 剩余{c.get('remain',0)} | 首讲:{c.get('next_date','')}")
    
    if has_more:
        lines.append(f"...还有{len(filtered)-MAX_RETURN}个班级未显示，可加时间/星期筛选缩小范围")
    
    if not filtered:
        lines.append("暂无可插班班级")
    
    # 精简返回：文本摘要 + 精简班级列表（兼容wecom_ai.py）
    compact_classes = [
        {"id": c.get("id"), "teacher": c.get("teacher",""), "teacher_tag": c.get("teacher_tag",""),
         "week": c.get("week",""), "remain": c.get("remain",0), "next_date": c.get("next_date","")}
        for c in display_classes
    ]
    
    return {
        "code": 0,
        "message": "查询成功" if filtered else "未找到符合条件的班级",
        "total": len(filtered),
        "result": "\n".join(lines),
        "classes": compact_classes
    }


async def _class_operation_internal(class_id: str, operation: str):
    """内部班级操作方法"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    class_id = int(class_id)
    
    if operation == "unlock":
        result = set_insertable(token, class_id, True)
    elif operation == "lock":
        result = set_insertable(token, class_id, False)
    elif operation == "allow_makeup":
        result = set_makeup(token, class_id, True)
    elif operation == "disallow_makeup":
        result = set_makeup(token, class_id, False)
    else:
        return error_response(f"未知操作: {operation}")
    
    if result:
        op_names = {"unlock": "解锁", "lock": "锁班", "allow_makeup": "允许补课", "disallow_makeup": "禁止补课"}
        return {"code": 200, "msg": f"{op_names.get(operation, operation)}成功", "class_id": class_id}
    else:
        return error_response(f"操作失败")


async def _teacher_operation_internal(teacher_name: str, operation: str):
    """内部按老师操作方法"""
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    insertable = (operation == "unlock")
    results = batch_set_insertable(token, teacher_name, insertable)
    
    if results:
        op_name = "解锁" if insertable else "锁班"
        success_count = sum(1 for r in results if r.get("success"))
        return {"code": 200, "msg": f"{op_name}完成", "teacher": teacher_name, "success_count": success_count, "total": len(results)}
    else:
        return error_response(f"未找到老师 {teacher_name} 的班级")


class EnrollRequest(BaseModel):
    user_id: str
    class_id: str


class RemoveRequest(BaseModel):
    class_id: str
    user_id: str
    reason: str = "排课调整"


class SearchStudentRequest(BaseModel):
    keyword: str


@app.post("/api/enroll/preview", dependencies=[Depends(verify_api_key)])
async def enroll_preview(req: EnrollRequest):
    """排课预览：获取班级课节列表中4X+1首讲课节，供确认后排课"""
    class_id = int(req.class_id)
    user_id = int(req.user_id)
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        # 获取班级课节列表
        resp = await client.post(
            f"{CRM_BASE_URL}/classs/getLiveList",
            headers=headers,
            json={"classId": class_id, "liveStatus": 0}  # 0=全部
        )
        data = resp.json()
        
        if data.get("code") != 200:
            return error_response(f"获取课节列表失败: {data.get('msg', '未知错误')}")
        
        lives = data.get("data", [])
        if not lives:
            return error_response("该班级没有待上课的课节")
        
        # 筛选从首讲开始的课节（首讲+后续课节都排入）
        first_lecture_lives = []
        live_list = []
        for live in lives:
            chapter_number = live.get("chapterNumber", "")
            chapter_num = parse_chapter_number_from_live(chapter_number)
            live_list.append({
                "live_id": live.get("liveId"),
                "chapter_number": chapter_number,
                "chapter_name": live.get("chapterName", ""),
                "chapter_num": chapter_num,
                "start_time": f"{live.get('classDate', '')} {live.get('startTime', '')}",
                "status": live.get("liveStatusStr", "")
            })
        
        # 找到第一个首讲，从该首讲开始排入所有后续课节
        first_lecture_idx = -1
        for i, live in enumerate(live_list):
            if live["chapter_num"] > 0 and live["chapter_num"] % 4 == 1:
                first_lecture_idx = i
                break
        
        if first_lecture_idx >= 0:
            # 从首讲开始，所有后续课节都排入
            first_lecture_lives = live_list[first_lecture_idx:]
        
        # 验证学员是否可以加入
        warnings = []
        for fl in first_lecture_lives:
            try:
                val_resp = await client.post(
                    f"{CRM_BASE_URL}/live_student/validateLiveStudent",
                    headers=headers,
                    json={"liveId": fl["live_id"], "userId": user_id}
                )
                val_data = val_resp.json()
                if val_data.get("code") != 200:
                    fl["can_join"] = False
                    fl["reason"] = val_data.get("msg", "验证失败")
                    warnings.append(f"{fl['chapter_number']}: {val_data.get('msg', '验证失败')}")
                else:
                    fl["can_join"] = True
            except:
                fl["can_join"] = None
                fl["reason"] = "验证请求失败"
    
    # 生成文本描述
    lines = [f"【排课预览】班级ID:{class_id}，学员ID:{user_id}"]
    lines.append(f"待上课首讲课节共{len(first_lecture_lives)}个：")
    for fl in first_lecture_lives:
        status = "✅可排" if fl.get("can_join") else f"❌{fl.get('reason','未知')}"
        lines.append(f"  - {fl['chapter_number']}({fl.get('chapter_name','')}) | {fl.get('start_time','')} | {status}")
    
    if warnings:
        lines.append(f"\n⚠️ 注意: {'; '.join(warnings)}")
    
    return {
        "code": 200,
        "msg": "成功",
        "total_first_lectures": len(first_lecture_lives),
        "class_id": class_id,
        "user_id": user_id,
        "live_ids": [fl["live_id"] for fl in first_lecture_lives if fl.get("can_join") is not False],
        "preview": "\n".join(lines)
    }


@app.post("/api/enroll/execute", dependencies=[Depends(verify_api_key)])
async def enroll_execute(req: EnrollRequest):
    """执行排课：将学员排入班级的4X+1首讲课节"""
    req.class_id = int(req.class_id)
    req.user_id = int(req.user_id)
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        # 1. 获取班级课节列表
        resp = await client.post(
            f"{CRM_BASE_URL}/classs/getLiveList",
            headers=headers,
            json={"classId": req.class_id, "liveStatus": 0}
        )
        data = resp.json()
        
        if data.get("code") != 200:
            return error_response(f"获取课节列表失败: {data.get('msg', '未知错误')}")
        
        lives = data.get("data", [])
        if not lives:
            return error_response("该班级没有课节")
        
        # 2. 筛选从首讲开始的课节（首讲+后续都排入）
        live_list = []
        for live in lives:
            chapter_number = live.get("chapterNumber", "")
            chapter_num = parse_chapter_number_from_live(chapter_number)
            live_list.append({
                "live_id": live.get("liveId"),
                "chapter_num": chapter_num
            })
        
        first_lecture_idx = -1
        for i, live in enumerate(live_list):
            if live["chapter_num"] > 0 and live["chapter_num"] % 4 == 1:
                first_lecture_idx = i
                break
        
        if first_lecture_idx < 0:
            return error_response("该班级没有可排入的首讲课节")
        
        # 从首讲开始，所有后续课节都排入
        first_lecture_live_ids = [live["live_id"] for live in live_list[first_lecture_idx:]]
        
        # 3. 执行排课
        enroll_resp = await client.post(
            f"{CRM_BASE_URL}/grade_student/joinlives",
            headers=headers,
            json={
                "userId": req.user_id,
                "classId": req.class_id,
                "liveIds": first_lecture_live_ids
            }
        )
        enroll_data = enroll_resp.json()
        
        if enroll_data.get("code") != 200:
            return error_response(f"排课失败: {enroll_data.get('msg', '未知错误')}")
    
    return {
        "code": 200,
        "msg": "排课成功",
        "class_id": req.class_id,
        "user_id": req.user_id,
        "enrolled_live_count": len(first_lecture_live_ids),
        "detail": f"已将学员{req.user_id}排入班级{req.class_id}的{len(first_lecture_live_ids)}个首讲课节"
    }


def parse_chapter_number_from_live(chapter_name: str) -> int:
    """从课节名称解析讲次编号"""
    import re
    match = re.search(r'_(\d+)', chapter_name)
    if match:
        return int(match.group(1))
    return -1


@app.post("/api/enroll/remove", dependencies=[Depends(verify_api_key)])
async def enroll_remove(req: RemoveRequest):
    """移出学员：将学员从班级中移出"""
    req.class_id = int(req.class_id)
    req.user_id = int(req.user_id)
    is_valid, token, message = check_token()
    if not is_valid or not token:
        return error_response(message, code=401)
    
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        # 调用移出API - 直接从班级移出学员
        remove_resp = await client.post(
            f"{CRM_BASE_URL}/grade_student/del",
            headers=headers,
            json={
                "classId": req.class_id,
                "studentId": req.user_id
            }
        )
        remove_data = remove_resp.json()
        
        if remove_data.get("code") != 200:
            return error_response(f"移出失败: {remove_data.get('msg', '未知错误')}")
    
    return {
        "code": 200,
        "msg": "移出成功",
        "class_id": req.class_id,
        "user_id": req.user_id,
        "detail": f"已将学员{req.user_id}从班级{req.class_id}中移出"
    }


# ==================== 主入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)


# ==================== 工单轮询模块API ====================

from work_order_poller import get_poller, init_poller, WorkOrderPoller

# 工单ID请求
class WorkOrderIdRequest(BaseModel):
    work_order_id: int


@app.on_event("startup")
async def startup_event():
    """服务启动时初始化工单轮询器和老师缓存"""
    try:
        poller = init_poller()
        logger.info(f"工单轮询器已初始化，状态: {poller.get_status()}")
    except Exception as e:
        print(f"初始化工单轮询器失败: {e}")
    
    # 后台预加载老师名→ID缓存（不阻塞启动）
    try:
        import threading
        from crm_query import _build_teacher_cache
        token = load_token()
        if token:
            def _load_cache():
                try:
                    _build_teacher_cache(token)
                    from crm_query import _teacher_cache
                    logger.info(f"老师缓存已加载，共{len(_teacher_cache)}位老师")
                except Exception as e:
                    logger.warning(f"加载老师缓存失败: {e}")
            t = threading.Thread(target=_load_cache, daemon=True)
            t.start()
            logger.info("老师缓存后台加载中...")
    except Exception as e:
        logger.warning(f"启动老师缓存线程失败: {e}")


@app.post("/api/work-order/poll", dependencies=[Depends(verify_api_key)])
async def poll_work_orders():
    """手动触发一次工单轮询"""
    try:
        poller = get_poller()
        result = poller.poll_once()
        return success_response(result, "轮询完成")
    except Exception as e:
        return error_response(f"轮询失败: {str(e)}")


@app.get("/api/work-order/list", dependencies=[Depends(verify_api_key)])
async def list_pending_work_orders():
    """获取当前未处理的DEMO绿色通道工单列表"""
    try:
        poller = get_poller()
        pending_orders = poller.get_pending_orders()
        return success_response({
            "total": len(pending_orders),
            "orders": pending_orders
        })
    except Exception as e:
        return error_response(f"获取工单列表失败: {str(e)}")


@app.post("/api/work-order/{order_id}/process", dependencies=[Depends(verify_api_key)])
async def process_work_order(order_id: int):
    """手动处理指定工单（执行排课操作，第一阶段仅发送通知）"""
    try:
        poller = get_poller()
        result = poller.process_order(order_id)
        if result.get("success"):
            return success_response(result)
        else:
            return error_response(result.get("message", "处理失败"))
    except Exception as e:
        return error_response(f"处理工单失败: {str(e)}")


@app.post("/api/work-order/{order_id}/close", dependencies=[Depends(verify_api_key)])
async def close_work_order(order_id: int):
    """关闭指定工单"""
    try:
        token = load_token()
        if not token:
            return error_response("无法加载Token", code=401)
        
        from work_order_poller import call_ticket_api
        result = call_ticket_api("POST", "/v-ticket/work-order/close", token, {"id": order_id})
        
        if result.get("code") == 200:
            return success_response({"order_id": order_id}, "工单已关闭")
        else:
            return error_response(result.get("msg", "关闭工单失败"))
    except Exception as e:
        return error_response(f"关闭工单失败: {str(e)}")


@app.get("/api/work-order/status", dependencies=[Depends(verify_api_key)])
async def get_poller_status():
    """获取工单轮询器状态"""
    try:
        poller = get_poller()
        return success_response(poller.get_status())
    except Exception as e:
        return error_response(f"获取状态失败: {str(e)}")


# 添加logger定义（如果还没有的话）
try:
    logger
except NameError:
    import logging
    logger = logging.getLogger("CRM-API")


# ==================== 主入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)