#!/usr/bin/env python3
"""
钉钉企业机器人 - 教务小助手
基于 Stream 模式接收群消息
"""

import os
import sys
import json
import logging
import re
import asyncio
import httpx
import dingtalk_stream
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入自定义模块
from crm_query import get_stage_id, query_classes, filter_insertable_classes, format_result, lock_class, set_insertable, set_makeup, parse_token_expiry, is_token_expiring_soon, check_and_refresh_token_if_needed, resolve_class_query, query_classes_by_teacher, batch_set_insertable, batch_set_makeup
from notify import send_message_with_image

# 配置日志
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s %(name)-8s %(levelname)-8s %(message)s'
)
logger = logging.getLogger("教务小助手")

# 钉钉应用凭证
CLIENT_ID = os.getenv("DINGTALK_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DINGTALK_CLIENT_SECRET", "")

# CRM Token（动态从crm_token.json加载，不再硬编码）
CRM_TOKEN = ""
# Token 存储文件
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm_token.json")


def load_token_from_file():
    """从crm_token.json加载Token"""
    global CRM_TOKEN
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            token = data.get('token', '')
            if token:
                CRM_TOKEN = token
                return True
    except Exception as e:
        logger.error(f"加载Token文件失败: {e}")
    return False


def get_crm_token():
    """获取当前有效的CRM Token，自动检查并从文件重新加载"""
    global CRM_TOKEN
    # 检查Token是否过期或类型是否正确
    expiry = parse_token_expiry(CRM_TOKEN) if CRM_TOKEN else None
    
    need_reload = False
    if not CRM_TOKEN:
        need_reload = True
    elif expiry and expiry < datetime.now():
        need_reload = True
    elif CRM_TOKEN and not is_cst_token(CRM_TOKEN):
        need_reload = True
    
    if need_reload:
        # 尝试从文件重新加载
        if load_token_from_file():
            # 验证新Token
            new_expiry = parse_token_expiry(CRM_TOKEN)
            if new_expiry and new_expiry > datetime.now() and is_cst_token(CRM_TOKEN):
                logger.info(f"✅ Token已从文件重新加载，过期时间: {new_expiry}")
            else:
                logger.warning(f"⚠️ 文件中的Token也无效")
    
    return CRM_TOKEN


def is_cst_token(token: str) -> bool:
    """检查Token是否是CST类型（有效），而非TCT类型（无效）"""
    try:
        import base64
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.b64decode(payload).decode('utf-8')
        return 'CST' in decoded and 'TCT' not in decoded
    except Exception:
        return False

# 任务文件路径
TASK_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/pending_task.json"
# 操作日志文件路径
OPERATION_LOG_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/operation_log.json"
# 权限配置文件路径
PERMISSION_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/permission_config.json"
# 管理员列表文件
ADMIN_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/admin_list.json"


def load_admin_list():
    """加载管理员列表"""
    if os.path.exists(ADMIN_FILE):
        try:
            with open(ADMIN_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}  # 改为 {staff_id: name} 格式


def save_admin_list(admins: dict):
    """保存管理员列表"""
    with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
        json.dump(admins, f, ensure_ascii=False, indent=2)


def is_admin(sender_staff_id: str) -> bool:
    """检查是否是管理员"""
    admins = load_admin_list()
    return sender_staff_id in admins


def save_permission_config(config: dict):
    """保存权限配置"""
    with open(PERMISSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_permission_config():
    """加载权限配置"""
    if os.path.exists(PERMISSION_FILE):
        try:
            with open(PERMISSION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    # 默认配置：所有群所有人都可以执行所有操作
    return {
        "default": {
            "actions": ["query", "lock_class", "unlock_class", "allow_transfer", "disallow_transfer",
                       "allow_makeup", "disallow_makeup", "find_class"]
        },
        "groups": {}
    }


def check_permission(conversation_id: str, sender_staff_id: str, action: str, config: dict) -> tuple:
    """检查权限
    
    Args:
        conversation_id: 群聊ID
        sender_staff_id: 发送者工号
        action: 操作类型
        config: 权限配置
    
    Returns:
        (has_permission: bool, reason: str)
    """
    # 0. 管理员拥有所有权限
    admin_list = load_admin_list()
    if sender_staff_id in admin_list:
        return True, f"管理员 {admin_list[sender_staff_id]} 拥有所有权限"
    
    # 获取默认权限
    default_actions = config.get("default", {}).get("actions", [])
    
    # 检查群聊权限
    group_config = config.get("groups", {}).get(conversation_id, {})
    
    # 1. 先检查用户级权限（用户配置叠加默认权限，而非替代）
    user_has_explicit_deny = False
    if sender_staff_id:
        user_config = group_config.get("users", {}).get(sender_staff_id, {})
        if user_config:
            user_actions = user_config.get("actions", [])
            # 查询权限(query)始终继承默认权限，不受用户级配置限制
            if action == "query" and action in default_actions:
                return True, f"用户 {user_config.get('name', sender_staff_id)} 查询权限（继承默认）"
            if action in user_actions:
                return True, f"用户 {user_config.get('name', sender_staff_id)} 有权限"
            elif user_actions:  # 用户有配置但不含此操作
                user_has_explicit_deny = True
    
    # 2. 检查群聊级权限
    group_actions = group_config.get("actions", [])
    if group_actions:
        if action in group_actions:
            return True, f"群聊 {group_config.get('name', conversation_id[:10])} 有权限"
        elif not user_has_explicit_deny:
            return False, f"群聊 {group_config.get('name', conversation_id[:10])} 无此操作权限"
    
    # 3. 使用默认权限
    if action in default_actions:
        return True, "使用默认权限"
    
    if user_has_explicit_deny:
        return False, f"用户 {user_config.get('name', sender_staff_id)} 无此操作权限"
    
    return False, "无权限"


def log_operation(action: str, sender: str, conversation_id: str, content: str, result: str, extra: dict = None):
    """记录操作日志
    
    Args:
        action: 操作类型（query/lock/unlock/set_permission）
        sender: 发起人
        conversation_id: 群聊ID
        content: 指令内容
        result: 执行结果
        extra: 额外信息
    """
    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "sender": sender,
        "conversation_id": conversation_id,
        "content": content,
        "result": result,
        "extra": extra or {}
    }
    
    # 读取现有日志
    logs = []
    if os.path.exists(OPERATION_LOG_FILE):
        try:
            with open(OPERATION_LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except:
            logs = []
    
    # 添加新日志
    logs.append(log_entry)
    
    # 分类型保留策略
    # 锁班/解锁/权限操作保留2000条，查班操作保留500条
    important_actions = ["lock_class", "unlock_class", "allow_transfer", "disallow_transfer", 
                         "allow_makeup", "disallow_makeup"]
    
    important_logs = [l for l in logs if l["action"] in important_actions][-2000:]
    query_logs = [l for l in logs if l["action"] == "query"][-500:]
    other_logs = [l for l in logs if l["action"] not in important_actions and l["action"] != "query"][-500:]
    
    logs = important_logs + query_logs + other_logs
    
    # 按时间排序
    logs.sort(key=lambda x: x["timestamp"])
    
    with open(OPERATION_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


class DingTalkBotHandler(dingtalk_stream.ChatbotHandler):
    """钉钉机器人消息处理器"""
    
    def __init__(self, logger: logging.Logger = None):
        super(dingtalk_stream.ChatbotHandler, self).__init__()
        if logger:
            self.logger = logger

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        """处理接收到的消息"""
        try:
            # 解析消息
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            
            # 获取消息信息
            conversation_type = incoming_message.conversation_type  # 1=单聊, 2=群聊
            conversation_id = incoming_message.conversation_id or ""  # 群聊ID
            sender_nick = incoming_message.sender_nick or "未知用户"
            sender_staff_id = incoming_message.sender_staff_id or ""
            
            # 获取消息文本
            text = ""
            if incoming_message.text:
                text = incoming_message.text.content.strip()
            
            self.logger.info(f"收到消息 - 会话类型:{conversation_type} 群聊ID:{conversation_id} 发送者:{sender_nick} 工号:{sender_staff_id} 内容:{text}")
            
            # 加载权限配置
            permission_config = load_permission_config()
            
            # 解析指令并执行
            response = await self._parse_command(text, sender_nick, sender_staff_id, conversation_id, permission_config)
            
            # 回复消息 - 优先使用markdown格式
            self.logger.info(f"准备回复: {response[:50]}...")
            try:
                # 判断是否使用markdown格式（查班结果等长文本用markdown，短文本用text）
                use_markdown = len(response) > 50 or '【' in response or '❌' in response or '✅' in response
                if use_markdown:
                    result = self.reply_markdown("教务小助手", response, incoming_message)
                else:
                    result = self.reply_text(response, incoming_message)
                self.logger.info(f"回复结果: {result}")
            except Exception as reply_err:
                self.logger.error(f"回复失败: {reply_err}")
            
            return dingtalk_stream.AckMessage.STATUS_OK, 'OK'
            
        except Exception as e:
            self.logger.error(f"处理消息失败: {e}", exc_info=True)
            return dingtalk_stream.AckMessage.STATUS_OK, 'ERROR'
    
    async def _parse_command(self, text: str, sender_nick: str, sender_staff_id: str, conversation_id: str = "", permission_config: dict = None) -> str:
        """解析并执行指令"""
        if not text:
            return f"你好 {sender_nick}！我是教务小助手。\n发送「帮助」查看我能做什么~"
        
        text = text.strip()
        permission_config = permission_config or load_permission_config()
        
        # 帮助指令
        if text in ["帮助", "help", "?", "？"]:
            return self._get_help()
        
        # ==================== 权限配置指令（仅管理员可用）====================
        
        # 查看工号（显示当前群聊ID和自己的工号，方便配置）
        if text == "查看工号":
            return f"📋 当前信息：\n• 你的工号：{sender_staff_id}\n• 你的昵称：{sender_nick}\n• 群聊ID：{conversation_id}"
        
        # 添加管理员
        if text.startswith("添加管理员 "):
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            # 格式：添加管理员 工号 姓名
            parts = text.replace("添加管理员 ", "").strip().split(None, 1)
            if len(parts) < 2:
                return "❌ 格式：添加管理员 工号 姓名\n示例：添加管理员 15505729691213213 张三"
            staff_id = parts[0]
            name = parts[1]
            admins = load_admin_list()
            if staff_id not in admins:
                admins[staff_id] = name
                save_admin_list(admins)
                return f"✅ 已添加管理员：{name}({staff_id})"
            return f"⚠️ {admins.get(staff_id, staff_id)} 已是管理员"
        
        # 移除管理员
        if text.startswith("移除管理员 "):
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            staff_id = text.replace("移除管理员 ", "").strip()
            admins = load_admin_list()
            if staff_id in admins:
                name = admins[staff_id]
                del admins[staff_id]
                save_admin_list(admins)
                return f"✅ 已移除管理员：{name}({staff_id})"
            return f"⚠️ 工号 {staff_id} 不是管理员"
        
        # 查看管理员
        if text == "查看管理员":
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            admins = load_admin_list()
            if not admins:
                return "📋 当前没有管理员"
            lines = ["📋 管理员列表："]
            for staff_id, name in admins.items():
                lines.append(f"• {name}（{staff_id}）")
            return "\n".join(lines)
        
        # 设置默认权限
        if text.startswith("设置默认权限 "):
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            actions_str = text.replace("设置默认权限 ", "").strip()
            actions = [a.strip() for a in actions_str.split(",") if a.strip()]
            permission_config["default"]["actions"] = actions
            save_permission_config(permission_config)
            return f"✅ 已设置默认权限：{', '.join(actions)}"
        
        # 设置群权限：设置群权限 群ID 操作1,操作2
        if text.startswith("设置群权限 "):
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            parts = text.replace("设置群权限 ", "").split()
            if len(parts) < 2:
                return "❌ 格式：设置群权限 群ID 操作1,操作2\n可用操作：query,lock_class,unlock_class,allow_transfer,disallow_transfer,allow_makeup,disallow_makeup"
            group_id = parts[0]
            actions = [a.strip() for a in parts[1].split(",") if a.strip()]
            if "groups" not in permission_config:
                permission_config["groups"] = {}
            if group_id not in permission_config["groups"]:
                permission_config["groups"][group_id] = {}
            permission_config["groups"][group_id]["actions"] = actions
            save_permission_config(permission_config)
            return f"✅ 已设置群 {group_id[:20]}... 权限：{', '.join(actions)}"
        
        # 设置用户权限：设置用户权限 群ID 员工工号 姓名 操作1,操作2
        match = re.match(r'设置用户权限\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)', text)
        if match:
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            group_id = match.group(1)
            staff_id = match.group(2)
            user_name = match.group(3)
            actions = [a.strip() for a in match.group(4).split(",") if a.strip()]
            
            if "groups" not in permission_config:
                permission_config["groups"] = {}
            if group_id not in permission_config["groups"]:
                permission_config["groups"][group_id] = {}
            if "users" not in permission_config["groups"][group_id]:
                permission_config["groups"][group_id]["users"] = {}
            
            permission_config["groups"][group_id]["users"][staff_id] = {
                "name": user_name,
                "actions": actions
            }
            save_permission_config(permission_config)
            return f"✅ 已设置用户 {user_name}({staff_id}) 权限：{', '.join(actions)}"
        
        # 查看权限配置
        if text == "查看权限" or text.startswith("查看权限 "):
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            
            if text == "查看权限":
                # 显示所有群
                groups = permission_config.get("groups", {})
                default = permission_config.get("default", {}).get("actions", [])
                lines = [f"📋 默认权限：{', '.join(default) if default else '无'}"]
                if groups:
                    lines.append("\n群聊权限：")
                    for gid, gconf in groups.items():
                        g_actions = gconf.get("actions", [])
                        lines.append(f"• {gid[:20]}...: {', '.join(g_actions) if g_actions else '继承默认'}")
                        users = gconf.get("users", {})
                        for uid, uconf in users.items():
                            u_actions = uconf.get("actions", [])
                            lines.append(f"  └ {uconf.get('name', uid)}: {', '.join(u_actions)}")
                return "\n".join(lines)
            else:
                # 查看指定群
                group_id = text.replace("查看权限 ", "").strip()
                groups = permission_config.get("groups", {})
                if group_id not in groups:
                    return f"❌ 群 {group_id} 未配置权限"
                gconf = groups[group_id]
                lines = [f"📋 群 {group_id[:20]}... 权限配置："]
                g_actions = gconf.get("actions", [])
                lines.append(f"群权限：{', '.join(g_actions) if g_actions else '继承默认'}")
                users = gconf.get("users", {})
                if users:
                    lines.append("用户权限：")
                    for uid, uconf in users.items():
                        u_actions = uconf.get("actions", [])
                        lines.append(f"• {uconf.get('name', uid)}: {', '.join(u_actions)}")
                return "\n".join(lines)
        
        # 删除群权限
        if text.startswith("删除群权限 "):
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            group_id = text.replace("删除群权限 ", "").strip()
            groups = permission_config.get("groups", {})
            if group_id in groups:
                del groups[group_id]
                permission_config["groups"] = groups
                save_permission_config(permission_config)
                return f"✅ 已删除群 {group_id[:20]}... 的权限配置"
            return f"⚠️ 群 {group_id} 未配置权限"
        
        # 删除用户权限：删除用户权限 群ID 员工工号
        match = re.match(r'删除用户权限\s+(\S+)\s+(\S+)', text)
        if match:
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            group_id = match.group(1)
            staff_id = match.group(2)
            groups = permission_config.get("groups", {})
            if group_id in groups and "users" in groups[group_id] and staff_id in groups[group_id]["users"]:
                del groups[group_id]["users"][staff_id]
                permission_config["groups"] = groups
                save_permission_config(permission_config)
                return f"✅ 已删除用户 {staff_id} 的权限配置"
            return f"⚠️ 未找到用户 {staff_id} 的权限配置"
        
        # 更新 Token：更新Token xxx
        if text.startswith("更新Token ") or text.startswith("更新token "):
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            new_token = text.replace("更新Token ", "").replace("更新token ", "").strip()
            if len(new_token) < 50:
                return "❌ Token 格式不正确，请提供完整的 Token"
            
            # 更新全局变量
            global CRM_TOKEN
            CRM_TOKEN = new_token
            
            # 保存到文件
            token_data = {
                "token": new_token,
                "updated_at": datetime.now().isoformat(),
                "updated_by": sender_nick
            }
            with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=2)
            
            # 解析过期时间
            expiry = parse_token_expiry(new_token)
            expiry_str = expiry.strftime("%Y-%m-%d %H:%M") if expiry else "未知"
            
            return f"✅ Token 已更新！\n• 过期时间：{expiry_str}\n• 更新人：{sender_nick}"
        
        # 查看 Token 状态
        if text == "查看Token" or text == "查看token":
            if not is_admin(sender_staff_id):
                return "❌ 只有管理员才能执行此操作"
            
            expiry = parse_token_expiry(CRM_TOKEN)
            if expiry:
                now = datetime.now()
                if expiry < now:
                    status = "❌ 已过期"
                    time_left = "已过期"
                else:
                    hours_left = (expiry - now).total_seconds() / 3600
                    if hours_left < 24:
                        status = "⚠️ 即将过期"
                    else:
                        status = "✅ 有效"
                    time_left = f"{int(hours_left)} 小时"
                
                return f"📋 Token 状态：\n• 状态：{status}\n• 过期时间：{expiry.strftime('%Y-%m-%d %H:%M')}\n• 剩余时间：{time_left}"
            else:
                return "⚠️ 无法解析 Token 过期时间"
        
        # ==================== 业务指令 ====================
        
        if text in ["测试", "test"]:
            return f"✅ 在线！你好 {sender_nick}，我已准备就绪~"
        
        # 提取班级ID（支持多个ID，用空格/逗号/顿号分隔）
        class_id_list = re.findall(r'\d{5,}', text)
        class_id = class_id_list[0] if class_id_list else None
        multiple_ids = class_id_list if len(class_id_list) > 1 else None
        
        # 查找班级（按班级ID）
        if class_id and re.search(r'查(?:找)?班级|查询班级', text):
            task = {
                "type": "find_class",
                "class_id": class_id,
                "sender_nick": sender_nick,
                "sender_staff_id": sender_staff_id,
                "conversation_id": conversation_id,
                "created_at": datetime.now().isoformat()
            }
            self._write_task(task)
            return f"📋 正在查找班级 {class_id}，请稍候..."
        
        # 查班（按课类+阶段筛选可插班班级）
        # 格式1：查班 {课类} {阶段} 如：查班 豌豆明思 S2
        # 格式2：查询{课类}{阶段}的可插班班级 如：查询豌豆明思2025（台湾）S3的可插班班级
        # 格式3：找班 {课类} {阶段}
        # 格式4：粤语S1 20:10 或 粤语S1 20:10的班（带时间筛选）
        # 格式5：粤语S1 工作日20:10 或 粤语S1 周一周四20:10（带周期+时间筛选）
        # 格式6：查班 粤语S2 19:20（查班+课类阶段+时间）
        # 格式7：课类S阶段+老师名 如：普通话S2奥力老师 / 英语S1Jonery
        # 格式8：老师名+查班 如：奥力老师查班 / Precious查班（查该老师所有阶段）
        
        course_type = None
        stage = None
        time_filter = None
        weekday_filter = None
        teacher_name = None  # 指定老师名字过滤
        time_range_desc = ""  # 时间范围描述文本，用于显示
        weekday_strict_mode = True  # 默认严格模式：班级的所有上课时间都必须在指定星期内。\"包含\"关键字切换为宽松模式
        
        # ============ 新解析器：正则优先，语义兜底 ============
        from query_parser import parse_query as _parse_query
        _parsed = _parse_query(text)
        
        if _parsed and (_parsed["course"] or _parsed["stage"] or _parsed["teacher"]):
            # 解析成功，使用新解析器结果
            if _parsed["teacher"] and not _parsed["course"] and not _parsed["stage"]:
                # 纯老师查班，走老逻辑
                teacher_name = _parsed["teacher"]
            elif _parsed["course"] and _parsed["stage"]:
                course_type = _parsed["course"]
                stage = _parsed["stage"]
                teacher_name = _parsed["teacher"]
                
                # 有筛选条件且含时间：直接执行多条件查询（单组多时间也需要精确过滤）
                if _parsed["filters"] and any(f["times"] or f["period"] for f in _parsed["filters"]):
                    from crm_query import resolve_class_query as _resolve, query_classes as _query_cls, parse_time_range as _parse_time_range
                    
                    _resolved = _resolve(course_type, stage)
                    if _resolved:
                        has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "query", permission_config)
                        if not has_perm:
                            return f"❌ 抱歉，您没有查班权限。{perm_reason}"
                        
                        # 中英班多课类合并查询
                        _multi_cate = _resolved.get("cate_sids", [])
                        if _multi_cate:
                            _seen = set()
                            _all_classes = []
                            for _cs in _multi_cate:
                                _cls = _query_cls(get_crm_token(), _cs["cate_sid"],
                                                  lan_id=_resolved['lan_id'], class_stu_type=1)
                                if _cls:
                                    for c in _cls:
                                        if c.get("id") not in _seen:
                                            _seen.add(c.get("id"))
                                            _all_classes.append(c)
                        else:
                            _all_classes = _query_cls(get_crm_token(), _resolved['cate_sid'], 
                                                      lan_id=_resolved['lan_id'], class_stu_type=1)
                        
                        if _all_classes is None:
                            log_operation("query", sender_nick, conversation_id, text, "失败：Token过期或查询失败")
                            return f"❌ 查询失败，可能是Token过期。请在CRM页面重新获取token。"
                        if not _all_classes:
                            log_operation("query", sender_nick, conversation_id, text, "失败：未找到符合条件的班级")
                            return f"❌ 未找到 {_resolved['language']}{_resolved['stage']} 的可插班班级"
                        
                        _seen_ids = set()
                        _all_valid = []
                        _filter_desc_parts = []
                        
                        for mf in _parsed["filters"]:
                            _wd = mf["weekday"]
                            _times = mf["times"]
                            _period = mf["period"]
                            
                            _tr = _parse_time_range(_period) if _period else None
                            _tf = _times[0] if len(_times) == 1 else ""
                            
                            _filtered = filter_insertable_classes(
                                _all_classes, course_type, _tf, _wd, _tr, 
                                weekday_strict_mode, token=get_crm_token()
                            )
                            
                            # 多精确时间匹配（兼容前导零：7:00 匹配 07:00）
                            if _times and len(_times) >= 1:
                                _time_matched = []
                                for v in _filtered:
                                    week_str = v.get("week", "")
                                    for _t in _times:
                                        _t_norm = f'{int(_t.split(":")[0]):02d}:{_t.split(":")[1]}' if ':' in _t else _t
                                        if _t in week_str or _t_norm in week_str:
                                            _time_matched.append(v)
                                            break
                                if _time_matched:
                                    _filtered = _time_matched
                            
                            for v in _filtered:
                                if v["id"] not in _seen_ids:
                                    _seen_ids.add(v["id"])
                                    _all_valid.append(v)
                            
                            _desc = ""
                            if _wd:
                                _desc += _wd + " "
                            if _times:
                                _desc += "/".join(_times) + " "
                            if _period:
                                _desc += _period
                            _filter_desc_parts.append(_desc.strip())
                        
                        msg = format_result(_all_valid, course_type, stage)
                        log_operation("query", sender_nick, conversation_id, text, 
                                     f"成功：多条件查询找到{len(_all_valid)}个班级", {
                            "course_type": course_type, "stage": stage, 
                            "filters": " | ".join(_filter_desc_parts), "count": len(_all_valid)
                        })
                        return msg
                    else:
                        return f"❌ 未找到 {course_type}{stage} 对应的课程配置"
                
                # 单组条件：走原有查询流程（兼容）
                if _parsed["filters"]:
                    f = _parsed["filters"][0]
                    weekday_filter = f["weekday"]
                    if f["period"]:
                        time_range_desc = f["period"]
                    elif f["times"]:
                        time_range_desc = " ".join(f["times"])
                    if len(f["times"]) == 1:
                        time_filter = f["times"][0]
                
                # 跳过老解析逻辑，直接到查询执行
                query_text = f"{course_type}{stage}"  # 用于后续匹配
        
        # ============ 老解析逻辑（兜底） ============
        _use_new_parser = bool(course_type and stage)  # 新解析器是否已成功
        
        # 预处理：智能识别查班指令（老逻辑专用）
        query_text = text
        query_text = query_text.replace('台灣', '台湾').replace('台灣', '台湾')  # 繁体转简体
        query_text = query_text.replace('英語', '英语').replace('粵語', '粤语')  # 繁体转简体
        query_text = query_text.replace('週', '周')  # 繁体"週"→简体"周"，修复"週六日"等周期筛选
        query_text = query_text.replace('国语', '普通话').replace('广东话', '粤语')  # 别名
        query_text = query_text.replace('双语', '中英')  # 别名
        query_text = query_text.replace('明思', '豌豆明思').replace('豌豆豌豆明思', '豌豆明思')  # 别名
        
        # 步骤1：去掉文本中任意位置的"查班"/"找班"关键词
        query_text_clean = re.sub(r'查班|找班', '', query_text).strip()
        
        # 如果去掉查班/找班后文本变了，说明用户确实在查班
        if query_text_clean != query_text:
            query_text = query_text_clean
        
        # 步骤1.5：去掉中文标点分隔符（逗号、顿号等），时间格式统一
        query_text = re.sub(r'[，、；,;]', ' ', query_text).strip()
        query_text = query_text.replace('：', ':')  # 中文全角冒号→英文半角冒号
        # 无冒号时间格式统一：1600→16:00，830→8:30
        # 匹配：紧跟"之后/以后/后/之前/以前/前"，或紧跟空格（独立时间参数），或紧跟查班/找班
        query_text = re.sub(r'(?<!\d)(\d{1,2})(\d{2})(?=(之后|以后|后|之前|以前|前|\s|查班|找班|$))', 
                           lambda m: f'{int(m.group(1))}:{m.group(2)}', query_text)
        # 中文时间词统一："9点"→"9:00"，"17点40"→"17:40"，"9点半"→"9:30"
        query_text = re.sub(r'(\d)点半', r'\1:30', query_text)
        query_text = re.sub(r'(\d)点(\d{1,2})(?!\d)', lambda m: f'{int(m.group(1))}:{int(m.group(2)):02d}', query_text)
        query_text = re.sub(r'(\d)点(?!\d)', r'\1:00', query_text)
        # 去掉多余空格
        query_text = re.sub(r'\s+', ' ', query_text)
        
        # 步骤2：处理 S阶段 在课类前面的情况（如 "S1英文" → "英文S1"）
        # 也处理 S阶段在后面但语种也在后面的情况（如 "周一周三16:50S2粤语" → "粤语S2 周一周三16:50"）
        
        # 先尝试：S数字+语种 在末尾（如 "xxxS2粤语" → "粤语S2 xxx"）
        s_course_end = re.search(r'S(\d+)\s*(英语|英文|粤语|台湾|普通话|国语|中英|豌豆明思)\s*$', query_text)
        if s_course_end:
            stage_part = f'S{s_course_end.group(1)}'
            course_part = s_course_end.group(2)
            prefix = query_text[:s_course_end.start()].strip()
            query_text = f'{course_part}{stage_part}'
            if prefix:
                query_text += f' {prefix}'
        else:
            # 原有逻辑：S数字+语种 在开头
            s_first_match = re.match(r'^(S?\d+)\s*(英语|英文|粤语|台湾|普通话|国语|中英|豌豆明思)(.*)$', query_text)
            if s_first_match:
                stage_part = s_first_match.group(1).upper()
                if not stage_part.startswith('S'):
                    stage_part = f'S{stage_part}'
                course_part = s_first_match.group(2)
                rest_part = s_first_match.group(3).strip()
                query_text = f'{course_part}{stage_part}'
                if rest_part:
                    query_text += f' {rest_part}'
        
        # 步骤3：确保课类和S阶段之间没有多余空格（"英文 S1" → "英文S1"）
        query_text = re.sub(r'(英语|英文|粤语|台湾|普通话|国语|中英|豌豆明思)\s+(S\d+)', r'\1\2', query_text)
        
        # 导入解析函数
        from crm_query import parse_time_range, parse_weekday_range
        
        # 尝试新格式 - 支持自然语言描述
        # 格式：课类 + 阶段 + [约束条件]
        # 如：台湾S4 仅包含周一到周四晚上
        # 如：粤语S1 周一到周五16:00以后
        # 如：英语S3 工作日晚上
        match_range = re.search(r'^(.+?)S(\d+)\s*(.+)$', query_text)
        if match_range and match_range.group(3).strip():
            course_type = match_range.group(1).strip()
            stage = "S" + match_range.group(2)
            rest = match_range.group(3).strip()
            
            # 提取老师名字（格式：XX老师/XX老師/英文名）
            teacher_name = None
            teacher_match = re.search(r'([\u4e00-\u9fff]+(?:老师|老師)|[a-zA-Z]+(?:\s+[a-zA-Z]+)*(?:老师|老師)?(?:\([\u4e00-\u9fff]+\))?)', rest)
            if teacher_match:
                teacher_name = teacher_match.group(1)
                rest = rest.replace(teacher_name, '').strip()
            
            # 周期模式判断：默认严格，"包含"切宽松
            if "包含" in rest:
                weekday_strict_mode = False
                rest = re.sub(r'包含', '', rest).strip()
            
            # 智能解析：尝试分离周期和时间
            # 可能的组合：
            # - "周一到周四晚上" -> 周期范围 + 时间段
            # - "工作日16:00以后" -> 周期 + 时间范围
            # - "晚上" -> 时间段
            # - "周一到周五" -> 周期范围
            # - "周一周三周四 16:50或者17:40 周日9点10点" -> 多组星期+时间（或者分隔）
            # - "19:20 20:10 18:30 17:40" -> 多个精确时间
            
            # 步骤A：统一"或者"为"或"，统一"点"为":00"
            rest_norm = rest.replace('或者', '或').replace('或是', '或')
            # "9点" → "9:00"，"10点" → "10:00"（仅当"点"后面不是数字时）
            rest_norm = re.sub(r'(\d)点(?!\d)', r'\1:00', rest_norm)
            # "9点半" → "9:30"
            rest_norm = re.sub(r'(\d)点半', r'\1:30', rest_norm)
            
            # 两种"或"的用法：
            # 1. "周一周三周四 16:50或者17:40 周日9点10点" 
            #    → 组1: 周一周三周四 + 16:50/17:40，组2: 周日 + 9:00/10:00
            #    "或者"连接的是同组内的时间，组之间用空格+星期词分隔
            # 2. "晚上或下午" → 两组时间段
            
            # 策略：用正则匹配 (星期组 + 时间组) 对
            # 如 "周一周三周四 16:50或17:40 周日9:00 10:00" 
            #   → [("周一周三周四", "16:50或17:40"), ("周日", "9:00 10:00")]
            
            # 按星期词分段：每个"周X"或"工作日/周末"开头新起一段
            _weekday_time_pattern = r'((?:周[一二三四五六日天])+|工作日|周末)\s*([\d:或\s点半]+(?:以后|之后|后|以前|之前|前|晚上|下午|上午|早上|中午|夜间)?)'
            _wt_matches = re.findall(_weekday_time_pattern, rest_norm)
            
            multi_filters = []
            if _wt_matches:
                for wd, time_part in _wt_matches:
                    time_part = time_part.strip()
                    # 按"或"分出备选时间
                    if '或' in time_part:
                        alternatives = re.split(r'\s*或\s*', time_part)
                    else:
                        alternatives = [time_part]
                    
                    times_in_seg = []
                    period_in_seg = ""
                    for alt in alternatives:
                        alt = alt.strip()
                        if not alt:
                            continue
                        alt_times = re.findall(r'(\d{1,2}:\d{2})', alt)
                        times_in_seg.extend(alt_times)
                        for period_name in ["晚上", "下午", "上午", "早上", "中午", "夜间"]:
                            if period_name in alt:
                                period_in_seg = period_name
                                break
                    
                    multi_filters.append({
                        "weekday": wd,
                        "times": times_in_seg,
                        "period": period_in_seg
                    })
                
                # 检查rest_norm中是否还有未被匹配的纯时间部分（没有星期词的）
                _matched_str = ""
                for wd, tp in _wt_matches:
                    _matched_str += wd + tp
                _unmatched = rest_norm
                for part in _matched_str.split():
                    _unmatched = _unmatched.replace(part, '', 1)
                _unmatched = _unmatched.strip()
                if _unmatched:
                    # 残留的纯时间/时间段
                    _rem_times = re.findall(r'(\d{1,2}:\d{2})', _unmatched)
                    _rem_period = ""
                    for period_name in ["晚上", "下午", "上午", "早上", "中午", "夜间"]:
                        if period_name in _unmatched:
                            _rem_period = period_name
                            break
                    if _rem_times or _rem_period:
                        # 如果第一组没有时间，把残留时间加到第一组
                        if multi_filters and not multi_filters[0]["times"] and not multi_filters[0]["period"]:
                            multi_filters[0]["times"] = _rem_times
                            multi_filters[0]["period"] = _rem_period
                        else:
                            multi_filters.insert(0, {
                                "weekday": "",
                                "times": _rem_times,
                                "period": _rem_period
                            })
            else:
                # 没有星期词，按"或"分出纯时间/时间段
                if '或' in rest_norm:
                    alternatives = re.split(r'\s*或\s*', rest_norm)
                else:
                    alternatives = [rest_norm]
                
                for alt in alternatives:
                    alt = alt.strip()
                    if not alt:
                        continue
                    alt_times = re.findall(r'(\d{1,2}:\d{2})', alt)
                    alt_period = ""
                    for period_name in ["晚上", "下午", "上午", "早上", "中午", "夜间"]:
                        if period_name in alt:
                            alt_period = period_name
                            break
                    if alt_times or alt_period:
                        multi_filters.append({
                            "weekday": "",
                            "times": alt_times,
                            "period": alt_period
                        })
                
                if len(multi_filters) > 1:
                    # 多组筛选条件：分别查询后合并
                    from crm_query import resolve_class_query as _resolve, query_classes as _query_cls
                    
                    _resolved = _resolve(course_type, stage)
                    if _resolved:
                        _all_classes = _query_cls(get_crm_token(), _resolved['cate_sid'], 
                                                  lan_id=_resolved['lan_id'], class_stu_type=1)
                        
                        _seen_ids = set()
                        _all_valid = []
                        _filter_desc_parts = []
                        
                        for mf in multi_filters:
                            _wd = mf["weekday"]
                            _times = mf["times"]
                            _period = mf["period"]
                            
                            # 构建筛选条件
                            _wd_filter = _wd
                            _tr = None
                            _tf = None
                            
                            if _times:
                                # 多个精确时间：用第一个作为time_filter，后续在结果中匹配
                                _tf = _times[0] if len(_times) == 1 else None
                                if not _tr and not _tf:
                                    _tf = _times[0]
                            
                            if _period:
                                _tr = parse_time_range(_period)
                            elif _times and len(_times) > 1:
                                # 多时间点构建范围
                                pass  # 后面用精确匹配
                            
                            _filtered = filter_insertable_classes(
                                _all_classes, course_type, _tf or "", _wd_filter, _tr or None, 
                                weekday_strict_mode, token=get_crm_token()
                            )
                            
                            # 如果有多个精确时间，在结果中做精确匹配（兼容前导零：7:00 匹配 07:00）
                            if _times and len(_times) >= 1:
                                import re as _re3
                                _time_matched = []
                                for v in _filtered:
                                    week_str = v.get("week", "")
                                    # 检查班级时间是否包含任意一个指定时间
                                    for _t in _times:
                                        _t_norm = f'{int(_t.split(":")[0]):02d}:{_t.split(":")[1]}' if ':' in _t else _t
                                        _t_short = _t.rstrip('0').rstrip(':')  # "17:40" → "17:4", "9:00" → "9:"
                                        if _t in week_str or _t_norm in week_str or _t_short in week_str:
                                            _time_matched.append(v)
                                            break
                                _filtered = _time_matched if _time_matched else _filtered
                            
                            # 合并去重
                            for v in _filtered:
                                if v["id"] not in _seen_ids:
                                    _seen_ids.add(v["id"])
                                    _all_valid.append(v)
                            
                            # 描述
                            _desc = ""
                            if _wd:
                                _desc += _wd
                            if _times:
                                _desc += " " + "/".join(_times)
                            if _period:
                                _desc += " " + _period
                            _filter_desc_parts.append(_desc.strip())
                        
                        # 格式化合并结果
                        filter_str = " 或 ".join(_filter_desc_parts)
                        msg = format_result(_all_valid, course_type, stage)
                        
                        log_operation("query", sender_nick, conversation_id, text, 
                                     f"成功：多条件查询找到{len(_all_valid)}个班级", {
                            "course_type": course_type, "stage": stage, 
                            "filter": filter_str, "count": len(_all_valid)
                        })
                        return msg
            
            # 以下为原有的单组解析逻辑
            # 尝试匹配周期范围（周一到周四、周一至周五）
            range_match = re.search(r'(周[一二三四五六日天]\s*(?:到|至|-|~)\s*周[一二三四五六日天])', rest_norm)
            if range_match:
                weekday_filter = range_match.group(1)
                rest_after_weekday = rest_norm[range_match.end():].strip()
                # 剩余的是时间描述
                if rest_after_weekday:
                    time_range_desc = rest_after_weekday
            else:
                # 尝试匹配简单周期（工作日、周末、周一周四）
                simple_weekday_match = re.match(r'^(工作日|周末|(?:周[一二三四五六日天])+)', rest_norm)
                if simple_weekday_match:
                    weekday_filter = simple_weekday_match.group(1)
                    rest_norm = rest_norm[len(weekday_filter):].strip()
                
                # 剩余的是时间描述
                if rest_norm:
                    time_range_desc = rest_norm
                    # 检查是否是精确时间
                    if re.match(r'^\d{1,2}:\d{2}$', rest_norm):
                        time_filter = rest_norm
        
        # 尝试格式6 - 查班 粤语S2 19:20（带时间筛选，无空格）
        elif re.search(r'^(.+?)S(\d+)\s+(\d{1,2}:\d{2})(?:的班)?$', query_text):
            match_time_nospace = re.search(r'^(.+?)S(\d+)\s+(\d{1,2}:\d{2})(?:的班)?$', query_text)
            if match_time_nospace:
                course_type = match_time_nospace.group(1).strip()
                stage = "S" + match_time_nospace.group(2)
                time_filter = match_time_nospace.group(3)
        # 尝试格式5 - 带周期+时间筛选（如：粤语S1 工作日20:10、粤语S1 周一周四20:10）
        elif re.search(r'(.+?)S(\d+)\s+(工作日|周末|(?:周[一二三四五六日天])+)\s*(\d{1,2}:\d{2})', query_text):
            match_weekday = re.search(r'(.+?)S(\d+)\s+(工作日|周末|(?:周[一二三四五六日天])+)\s*(\d{1,2}:\d{2})(?:的班)?$', query_text)
            if match_weekday:
                course_type = match_weekday.group(1).strip()
                stage = "S" + match_weekday.group(2)
                weekday_filter = match_weekday.group(3)
                time_filter = match_weekday.group(4)
        # 尝试格式2 - 查询...S数字的可插班班级（课类和阶段之间可能有空格）
        elif "的可插班班级" in text:
            match2 = re.search(r'查询(.+?)S(\d+)\s*的可插班班级', text, re.IGNORECASE)
            if match2:
                course_type = match2.group(1).strip()
                stage = "S" + match2.group(2)
        # 尝试格式1和3 - 查班/找班 课类 阶段
        elif re.match(r'^(?:查班|找班)\s+.+\s+S?\d+$', text):
            match1 = re.search(r'(?:查班|找班)\s+(.+?)\s+(S?\d+)$', text)
            if match1:
                course_type = match1.group(1).strip()
                stage = match1.group(2).strip().upper()
                if not stage.startswith('S') and stage.isdigit():
                    stage = f"S{stage}"
        # 兜底：简单的 课类S阶段+老师 格式（如 "英文S1奥力老师"、"粤语S3小腰果老师"）
        elif not course_type or not stage:
            simple_match = re.search(r'(英语|英文|粤语|广东话|台湾|普通话|国语|中英|豌豆明思)\s*S(\d+)\s*([\u4e00-\u9fff]+(?:老师|老師)|[a-zA-Z]+(?:\s+[a-zA-Z]+)*(?:老师|老師)?(?:\([\u4e00-\u9fff]+\))?)?', query_text)
            if simple_match:
                course_type = simple_match.group(1)
                stage = f"S{simple_match.group(2)}"
                if simple_match.group(3) and not teacher_name:
                    teacher_name = simple_match.group(3)
        
        # 格式8：纯老师名查班（如"奥力老师查班"、"Precious查班"、"Tess Kervin查班"）
        if not course_type and not stage:
            teacher_only_match = re.search(r'^([\u4e00-\u9fff]+(?:老师|老師)|[a-zA-Z]+(?:\s+[a-zA-Z]+)*(?:老师|老師)?)\s*(?:查班|找班)?$', query_text)
            if not teacher_only_match:
                # 也匹配"查班+老师名"
                teacher_only_match = re.search(r'(?:查班|找班)\s+([\u4e00-\u9fff]+(?:老师|老師)|[a-zA-Z]+(?:\s+[a-zA-Z]+)*(?:老师|老師)?)', query_text)
            if teacher_only_match:
                teacher_name = teacher_only_match.group(1)
        
        if teacher_name and not course_type:
            # 纯老师查班：跨所有课类查找
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "query", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有查班权限。{perm_reason}"
            
            try:
                name_key = teacher_name.replace("老师", "").replace("老師", "")
                all_classes = query_classes_by_teacher(get_crm_token(), name_key, class_stu_type=None)
                # 英文名不加"老师"后缀
                import re as _re
                _is_eng = bool(_re.match(r'^[A-Za-z]+$', name_key))
                _title_suffix = "" if _is_eng else "老师"
                if not all_classes:
                    return f"❌ 未找到 {name_key}{_title_suffix}的班级"
                
                from crm_query import format_class_detail
                all_classes = sorted(all_classes, key=lambda c: (c.get("cateStr", ""), -(c.get("studentCount", 0) / max(c.get("maxClassNum", 1), 1))))
                lines = []
                for i, c in enumerate(all_classes, 1):
                    detail = format_class_detail(c, show_teacher_tag=False, show_first_lecture=False)
                    lines.append(f"**{i}.** {detail}")
                
                msg = f"{name_key}{_title_suffix}的班级\n共找到{len(all_classes)}个班级\n\n" + "\n\n".join(lines)
                log_operation("query", sender_nick, conversation_id, text, f"成功：找到{len(all_classes)}个班级", {
                    "teacher": name_key, "count": len(all_classes)
                })
                return msg
            except Exception as e:
                return f"❌ 查询失败: {str(e)}"
        
        if course_type and stage:
            # 权限检查
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "query", permission_config)
            if not has_perm:
                self.logger.info(f"权限拒绝: {perm_reason}")
                return f"❌ 抱歉，您没有查班权限。{perm_reason}"
            
            # 直接调用API查询，秒级完成
            try:
                # 使用统一语种×阶段路由
                resolved = resolve_class_query(course_type, stage)
                if not resolved:
                    # 给出更友好的提示
                    if course_type in ('普通话', '国语') and stage in ('S1', 'S1'):
                        log_operation("query", sender_nick, conversation_id, text, "失败：普通话无S1阶段")
                        return f"❌ 普通话没有S1阶段，最早从S2开始"
                    log_operation("query", sender_nick, conversation_id, text, "失败：未找到课程阶段ID")
                    return f"❌ 未找到 {course_type} {stage} 对应的课程阶段ID"
                
                # 调用API查询（带语种筛选）
                # 中英班分布在多个课类，需合并查询
                _multi_cate = resolved.get("cate_sids", [])
                
                if teacher_name:
                    # 指定老师查班：查全部班级（含满班+锁班），不做额外过滤
                    cst = 0  # 查全部
                    if _multi_cate:
                        # 多课类合并查询（中英）
                        _seen = set()
                        classes = []
                        for _cs in _multi_cate:
                            _cls = query_classes(get_crm_token(), _cs["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
                            if _cls:
                                for c in _cls:
                                    if c.get("id") not in _seen:
                                        _seen.add(c.get("id"))
                                        classes.append(c)
                    else:
                        classes = query_classes(get_crm_token(), resolved["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
                    if classes is None:
                        log_operation("query", sender_nick, conversation_id, text, "失败：Token过期或查询失败")
                        return f"❌ 查询失败，可能是Token过期。请在CRM页面重新获取token。"
                    if not classes:
                        log_operation("query", sender_nick, conversation_id, text, "失败：未找到符合条件的班级")
                        return f"❌ 未找到 {resolved['language']}{stage} 的可插班班级"
                    
                    # 按老师名字模糊匹配
                    name_key = teacher_name.replace("老师", "").replace("老師", "")
                    valid = [c for c in classes if name_key in c.get("teacherName", "")]
                    # 英文名不加"老师"后缀
                    import re as _re2
                    _is_eng2 = bool(_re2.match(r'^[A-Za-z]+$', name_key))
                    _ts2 = "" if _is_eng2 else "老师"
                    if not valid:
                        log_operation("query", sender_nick, conversation_id, text, f"失败：未找到老师{name_key}的班级")
                        return f"❌ 未找到 {name_key}{_ts2}在 {resolved['language']}{stage} 的班级"
                    
                    # 格式化老师名下班级结果（含满班/锁班标记）
                    from crm_query import format_class_detail
                    valid = sorted(valid, key=lambda c: (-(c.get("studentCount", 0) / max(c.get("maxClassNum", 1), 1)), c.get("teacherName", "")))
                    lines = []
                    MAX_BYTES = 18000
                    current_bytes = 0
                    truncated = False
                    for i, c in enumerate(valid, 1):
                        detail = format_class_detail(c, resolved["language"], show_teacher_tag=False, show_first_lecture=False)
                        line = f"**{i}.** {detail}"
                        line_bytes = len(line.encode('utf-8')) + 2
                        if current_bytes + line_bytes > MAX_BYTES:
                            truncated = True
                            break
                        lines.append(line)
                        current_bytes += line_bytes
                    
                    filter_str = f" {name_key}{_ts2}"
                    msg = f"{resolved['language']}{stage}{filter_str}的班级\n共找到{len(valid)}个班级\n\n" + "\n\n".join(lines)
                    if truncated:
                        msg += f"\n\n⚠️ 结果过长，仅显示前 {i-1} 条，共 {len(valid)} 条"
                    
                    log_operation("query", sender_nick, conversation_id, text, f"成功：找到{len(valid)}个班级", {
                        "course_type": course_type, "stage": stage, "teacher": name_key, "count": len(valid)
                    })
                    return msg
                else:
                    # 普通查班：台湾语种展示锁班（不含满班），其他语种只查允许插班的
                    cst = 0 if resolved.get("show_locked") else 1
                    if _multi_cate:
                        # 多课类合并查询（中英）
                        _seen = set()
                        classes = []
                        for _cs in _multi_cate:
                            _cls = query_classes(get_crm_token(), _cs["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
                            if _cls:
                                for c in _cls:
                                    if c.get("id") not in _seen:
                                        _seen.add(c.get("id"))
                                        classes.append(c)
                    else:
                        classes = query_classes(get_crm_token(), resolved["cate_sid"], lan_id=resolved["lan_id"], class_stu_type=cst)
                    if classes is None:
                        log_operation("query", sender_nick, conversation_id, text, "失败：Token过期或查询失败")
                        return f"❌ 查询失败，可能是Token过期。请在CRM页面重新获取token。"
                    if not classes:
                        log_operation("query", sender_nick, conversation_id, text, "失败：未找到符合条件的班级")
                        return f"❌ 未找到 {resolved['language']}{stage} 的可插班班级"
                    
                    # 筛选可插班班级
                    time_range = parse_time_range(time_range_desc) if time_range_desc else None
                    valid = filter_insertable_classes(classes, resolved["language"], time_filter, weekday_filter, time_range, weekday_strict_mode, token=get_crm_token())
                
                # 格式化结果
                filter_str = ""
                if teacher_name:
                    name_key = teacher_name.replace("老师", "").replace("老師", "")
                    _is_eng3 = bool(re.match(r'^[A-Za-z]+$', name_key))
                    filter_str = f" {name_key}{'' if _is_eng3 else '老师'}"
                if weekday_strict_mode and weekday_filter:
                    filter_str = f" 仅包含{weekday_filter}"
                elif weekday_filter:
                    filter_str = f" {weekday_filter}"
                if time_filter:
                    filter_str += f" {time_filter}"
                elif time_range_desc:
                    filter_str += f" {time_range_desc}"
                msg = format_result(valid, resolved["language"], f"{stage}{filter_str}")
                
                # 记录操作日志
                log_operation("query", sender_nick, conversation_id, text, f"成功：找到{len(valid)}个可插班班级", {
                    "course_type": course_type,
                    "stage": stage,
                    "time_filter": time_filter,
                    "time_range_desc": time_range_desc,
                    "weekday_filter": weekday_filter,
                    "count": len(valid)
                })
                
                # 异步发送消息（机器人回复）
                time_log = f" {time_filter}" if time_filter else f" {time_range_desc}" if time_range_desc else ""
                self.logger.info(f"查询完成：{course_type} {stage}{time_log}，找到 {len(valid)} 个可插班班级")
                
                # 直接返回结果，机器人会自动回复
                return msg
                
            except Exception as e:
                self.logger.error(f"查询失败: {e}")
                log_operation("query", sender_nick, conversation_id, text, f"异常：{str(e)}")
                return f"❌ 查询出错：{str(e)}"
        
        # 允许补课（直接调用API，秒级响应）
        if class_id and re.search(r'(?:允许|开启|打开).*补课', text):
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "allow_makeup", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有开启补课权限。{perm_reason}"
            result = set_makeup(get_crm_token(), class_id, allow=True)
            log_operation("allow_makeup", sender_nick, conversation_id, text, f"{'成功' if result['success'] else '失败'}", {"class_id": class_id, "result": result})
            if result["success"]:
                return f"✅ 班级 {class_id} 已允许补课"
            else:
                return f"❌ 操作失败：{result['msg']}"
        
        # 禁止补课（直接调用API，秒级响应）
        if class_id and re.search(r'(?:禁止|关闭|取消).*补课', text):
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "disallow_makeup", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有关闭补课权限。{perm_reason}"
            result = set_makeup(get_crm_token(), class_id, allow=False)
            log_operation("disallow_makeup", sender_nick, conversation_id, text, f"{'成功' if result['success'] else '失败'}", {"class_id": class_id, "result": result})
            if result["success"]:
                return f"✅ 班级 {class_id} 已禁止补课"
            else:
                return f"❌ 操作失败：{result['msg']}"
        
        # 允许插班（直接调用API，秒级响应）
        if class_id and re.search(r'(?:允许|开启|打开).*插班', text):
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "allow_transfer", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有允许插班权限。{perm_reason}"
            result = set_insertable(get_crm_token(), class_id, allow=True)
            log_operation("allow_transfer", sender_nick, conversation_id, text, f"{'成功' if result['success'] else '失败'}", {"class_id": class_id, "result": result})
            if result["success"]:
                return f"✅ 班级 {class_id} 已允许插班"
            else:
                return f"❌ 操作失败：{result['msg']}"
        
        # 禁止插班（直接调用API，秒级响应）
        if class_id and re.search(r'(?:禁止|关闭|取消).*插班', text):
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "disallow_transfer", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有禁止插班权限。{perm_reason}"
            result = set_insertable(get_crm_token(), class_id, allow=False)
            log_operation("disallow_transfer", sender_nick, conversation_id, text, f"{'成功' if result['success'] else '失败'}", {"class_id": class_id, "result": result})
            if result["success"]:
                return f"✅ 班级 {class_id} 已禁止插班"
            else:
                return f"❌ 操作失败：{result['msg']}"
        
        # 锁班（禁止插班）— 支持批量多班级ID
        if class_id and re.search(r'(?<!解)锁(?:定)?班', text):
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "lock_class", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有锁班权限。{perm_reason}"
            if multiple_ids:
                result = batch_set_insertable(get_crm_token(), multiple_ids, allow=False)
                log_operation("batch_lock", sender_nick, conversation_id, text, f"成功{result['success']}个", {"class_ids": multiple_ids, "result": result})
                msg = f"✅ 批量锁班完成：共{result['total']}个班级，成功{result['success']}个"
                if result['failed'] > 0:
                    msg += f"，失败{result['failed']}个（ID: {', '.join(result['failed_ids'])}）"
                return msg
            result = set_insertable(get_crm_token(), class_id, allow=False)
            log_operation("lock_class", sender_nick, conversation_id, text, f"{'成功' if result['success'] else '失败'}", {"class_id": class_id, "result": result})
            if result["success"]:
                return f"✅ 班级 {class_id} 已锁定（禁止插班）"
            else:
                return f"❌ 锁班失败：{result['msg']}"
        
        # 解锁班（允许插班）— 支持批量多班级ID
        if class_id and re.search(r'解(?:除)?锁', text):
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "unlock_class", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有解锁班权限。{perm_reason}"
            if multiple_ids:
                result = batch_set_insertable(get_crm_token(), multiple_ids, allow=True)
                log_operation("batch_unlock", sender_nick, conversation_id, text, f"成功{result['success']}个", {"class_ids": multiple_ids, "result": result})
                msg = f"✅ 批量解锁完成：共{result['total']}个班级，成功{result['success']}个"
                if result['failed'] > 0:
                    msg += f"，失败{result['failed']}个（ID: {', '.join(result['failed_ids'])}）"
                return msg
            result = set_insertable(get_crm_token(), class_id, allow=True)
            log_operation("unlock_class", sender_nick, conversation_id, text, f"{'成功' if result['success'] else '失败'}", {"class_id": class_id, "result": result})
            if result["success"]:
                return f"✅ 班级 {class_id} 已解锁（允许插班）"
            else:
                return f"❌ 解锁失败：{result['msg']}"
        
        # ==================== 按老师批量操作 ====================
        # query_classes_by_teacher, batch_set_insertable, batch_set_makeup 已在顶部全局导入
        
        # 按老师解锁班级：解锁 老师名 的班 / 解锁老师名的班 / 解除锁...
        match_unlock_teacher = re.search(r'^解(?:除)?锁\s*(.+?)\s*(?:英语|粤语|台湾)?\s*的班$', text)
        if match_unlock_teacher:
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "unlock_class", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有解锁班权限。{perm_reason}"
            
            teacher_name = match_unlock_teacher.group(1).strip()
            # 不再去掉"老师"后缀，精确匹配
            
            # 检查是否指定了课类
            course_type = None
            if "英语" in text:
                course_type = "英语"
            elif "粤语" in text:
                course_type = "粤语"
            elif "台湾" in text:
                course_type = "台湾"
            
            # 查询该老师的锁班（只查询需要解锁的班级）
            locked_classes = query_classes_by_teacher(get_crm_token(), teacher_name, course_type, class_stu_type=0)
            # 同时查询已解锁的班级数量（用于统计分解）
            unlocked_classes_all = query_classes_by_teacher(get_crm_token(), teacher_name, course_type, class_stu_type=1)
            already_unlocked = len(unlocked_classes_all)
            
            if not locked_classes:
                if already_unlocked > 0:
                    return f"ℹ️ {teacher_name} 的 {already_unlocked} 个班级已全部解锁，无需重复操作"
                return f"❌ 未找到 {teacher_name} 的已锁定班级"
            
            # 批量解锁
            class_ids = [str(c["classId"]) for c in locked_classes]
            result = batch_set_insertable(get_crm_token(), class_ids, allow=True)
            
            log_operation("batch_unlock", sender_nick, conversation_id, text, 
                         f"成功{result['success']}个，失败{result['failed']}个", 
                         {"teacher": teacher_name, "course_type": course_type, "result": result, "already_unlocked": already_unlocked})
            
            total_unlocked = already_unlocked + result['success']
            msg = f"✅ {teacher_name} 共 {total_unlocked} 个班级已解锁"
            if already_unlocked > 0:
                msg += f"（其中 {already_unlocked} 个原已解锁，本次新解锁 {result['success']} 个）"
            if result['failed'] > 0:
                msg += f"\n⚠️ {result['failed']} 个失败"
            return msg
        
        # 按老师锁定班级：锁定 老师名 的班 / 锁定老师名的班 / 上锁老师名的班
        match_lock_teacher = re.search(r'^(?:上锁|锁(?:定)?)\s*(.+?)\s*(?:英语|粤语|台湾)?\s*的班$', text)
        if match_lock_teacher:
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "lock_class", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有锁班权限。{perm_reason}"
            
            teacher_name = match_lock_teacher.group(1).strip()
            # 不再去掉"老师"后缀，精确匹配
            
            course_type = None
            if "英语" in text:
                course_type = "英语"
            elif "粤语" in text:
                course_type = "粤语"
            elif "台湾" in text:
                course_type = "台湾"
            
            # 查询未锁定的班级（待锁定）
            unlocked_classes = query_classes_by_teacher(get_crm_token(), teacher_name, course_type, class_stu_type=1)
            # 同时查询已锁定的班级数量
            locked_classes = query_classes_by_teacher(get_crm_token(), teacher_name, course_type, class_stu_type=0)
            already_locked = len(locked_classes)
            
            if not unlocked_classes:
                if already_locked > 0:
                    return f"ℹ️ {teacher_name} 的 {already_locked} 个班级已全部锁定，无需重复操作"
                return f"❌ 未找到 {teacher_name} 的班级"
            
            class_ids = [str(c["classId"]) for c in unlocked_classes]
            result = batch_set_insertable(get_crm_token(), class_ids, allow=False)
            
            log_operation("batch_lock", sender_nick, conversation_id, text,
                         f"成功{result['success']}个，失败{result['failed']}个",
                         {"teacher": teacher_name, "course_type": course_type, "result": result, "already_locked": already_locked})
            
            total_locked = already_locked + result['success']
            msg = f"✅ {teacher_name} 共 {total_locked} 个班级已锁定"
            if already_locked > 0:
                msg += f"（其中 {already_locked} 个原已锁，本次新锁 {result['success']} 个）"
            if result['failed'] > 0:
                msg += f"\n⚠️ {result['failed']} 个失败"
            return msg
        
        # 按老师允许补课：允许补课 老师名 的班 / 允许补课老师名的班
        match_makeup_teacher = re.search(r'^(?:允许|开启|打开)补课\s*(.+?)\s*(?:英语|粤语|台湾)?\s*的班$', text)
        if match_makeup_teacher:
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "allow_makeup", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有开启补课权限。{perm_reason}"
            
            teacher_name = match_makeup_teacher.group(1).strip()
            # 不再去掉"老师"后缀，精确匹配
            
            course_type = None
            if "英语" in text:
                course_type = "英语"
            elif "粤语" in text:
                course_type = "粤语"
            elif "台湾" in text:
                course_type = "台湾"
            
            classes = query_classes_by_teacher(get_crm_token(), teacher_name, course_type)
            if not classes:
                return f"❌ 未找到 {teacher_name} 的执行中班级"
            
            # 筛选未开启补课的班级
            no_makeup_classes = [c for c in classes if c.get("makeup") != 1]
            if not no_makeup_classes:
                return f"✅ {teacher_name} 的所有班级都已允许补课"
            
            class_ids = [str(c["classId"]) for c in no_makeup_classes]
            result = batch_set_makeup(get_crm_token(), class_ids, allow=True)
            
            log_operation("batch_allow_makeup", sender_nick, conversation_id, text,
                         f"成功{result['success']}个，失败{result['failed']}个",
                         {"teacher": teacher_name, "course_type": course_type, "result": result})
            
            msg = f"✅ 已为 {teacher_name} 开启 {result['success']} 个班级的补课权限"
            if result['failed'] > 0:
                msg += f"\n⚠️ {result['failed']} 个失败"
            return msg
        
        # ==================== 排课功能 ====================
        # 预览排课：排课预览 班级ID 学员ID
        match_preview = re.search(r'^排课预览\s+(\d+)\s+(\d+)', text)
        if match_preview:
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "preview_schedule", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有排课预览权限。{perm_reason}"
            class_id = match_preview.group(1)
            user_id = match_preview.group(2)
            try:
                result = asyncio.get_event_loop().run_until_complete(
                    self._call_crm_api("preview", class_id=class_id, user_id=user_id)
                )
                if result.get("code") == 200:
                    return result.get("preview", "预览成功但无内容")
                else:
                    return f"❌ 预览失败：{result.get('msg', '未知错误')}"
            except Exception as e:
                self.logger.error(f"排课预览失败: {e}")
                return f"❌ 预览出错：{str(e)}"
        
        # 执行排课：排课 班级ID 学员ID
        match_enroll = re.search(r'^排课\s+(\d+)\s+(\d+)', text)
        if match_enroll:
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "schedule", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有排课权限。{perm_reason}"
            class_id = match_enroll.group(1)
            user_id = match_enroll.group(2)
            try:
                # 先预览
                preview = asyncio.get_event_loop().run_until_complete(
                    self._call_crm_api("preview", class_id=class_id, user_id=user_id)
                )
                if preview.get("code") != 200:
                    return f"❌ 预览失败：{preview.get('msg', '未知错误')}"
                
                # 执行排课
                result = asyncio.get_event_loop().run_until_complete(
                    self._call_crm_api("enroll", class_id=class_id, user_id=user_id)
                )
                if result.get("code") == 200:
                    log_operation("enroll", sender_nick, conversation_id, text, f"成功：{result.get('detail', '')}", {
                        "class_id": class_id, "user_id": user_id
                    })
                    return f"✅ {result.get('detail', '排课成功')}"
                else:
                    return f"❌ 排课失败：{result.get('msg', '未知错误')}"
            except Exception as e:
                self.logger.error(f"排课失败: {e}")
                return f"❌ 排课出错：{str(e)}"
        
        # 移出学员：移出 班级ID 学员ID
        match_remove = re.search(r'^移出\s+(\d+)\s+(\d+)', text)
        if match_remove:
            has_perm, perm_reason = check_permission(conversation_id, sender_staff_id, "remove_student", permission_config)
            if not has_perm:
                return f"❌ 抱歉，您没有移出学员权限。{perm_reason}"
            class_id = match_remove.group(1)
            user_id = match_remove.group(2)
            try:
                result = asyncio.get_event_loop().run_until_complete(
                    self._call_crm_api("remove", class_id=class_id, user_id=user_id)
                )
                if result.get("code") == 200:
                    log_operation("remove", sender_nick, conversation_id, text, f"成功：{result.get('detail', '')}", {
                        "class_id": class_id, "user_id": user_id
                    })
                    return f"✅ {result.get('detail', '移出成功')}"
                else:
                    return f"❌ 移出失败：{result.get('msg', '未知错误')}"
            except Exception as e:
                self.logger.error(f"移出失败: {e}")
                return f"❌ 移出出错：{str(e)}"
        
        # ==================== 排课功能结束 ====================
        
        # 查询老师的班级：查询 老师名 的班 / 老师名 有哪些班
        match_query_teacher = re.search(r'^(?:查询)?(.+?)(?:老师|老師)?(?:\s+(英语|粤语|台湾))?\s*(?:的班|有哪些班|的班级)$', text)
        if match_query_teacher:
            teacher_name = match_query_teacher.group(1).strip()
            course_type = match_query_teacher.group(2)
            
            classes = query_classes_by_teacher(get_crm_token(), teacher_name, course_type)
            if not classes:
                return f"❌ 未找到 {teacher_name} 的执行中班级"
            
            lines = [f"【{teacher_name}的班级】共 {len(classes)} 个"]
            for i, c in enumerate(classes[:20], 1):  # 最多显示20个
                # classStuType: 1=允许插班(解锁), 2=禁止插班(锁定)
                status = "🔒" if c.get("classStuType") == 2 else "🔓"
                makeup = "补课✓" if c.get("makeup") == 1 else "补课✗"
                lines.append(f"{i}. ID `{c['classId']}` {status} {makeup} | {c.get('weekDate', '')} | {c.get('studentCount', 0)}/{c.get('maxClassNum', 8)}人")
            
            if len(classes) > 20:
                lines.append(f"... 还有 {len(classes) - 20} 个班级")
            
            return "\n".join(lines)
        
        # 默认响应
        return f"你好 {sender_nick}！我是教务小助手。\n发送「帮助」查看我能做什么~"
    
    async def _call_crm_api(self, command: str, **kwargs) -> dict:
        """调用CRM API统一接口"""
        api_base = "https://cigarette-tell-traditions-porcelain.trycloudflare.com"
        api_key = "<CRM_API_KEY>"
        
        payload = {"command": command}
        payload.update(kwargs)
        
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{api_base}/api/command",
                json=payload,
                headers={"X-API-Key": api_key, "Content-Type": "application/json"}
            )
            return resp.json()
    
    def _write_task(self, task: dict):
        """写入任务文件，等待主 session 处理"""
        try:
            with open(TASK_FILE, 'w', encoding='utf-8') as f:
                json.dump(task, f, ensure_ascii=False, indent=2)
            self.logger.info(f"任务已写入: {task['type']} - {task.get('class_id', '')}")
        except Exception as e:
            self.logger.error(f"写入任务文件失败: {e}")
    
    def _get_help(self) -> str:
        """获取帮助信息"""
        return """【教务小助手 - 指令列表】

📋 班级查询：
• 查班级 {班级ID} - 查询指定班级信息
• 查班 {课类} {阶段} - 查询可插班班级
• 查班 台湾 S4 周一到周四晚上 - 支持时间范围
• 查班 粤语 S2 16:00以后 - 16点以后的班
• {老师名}的班 - 查询老师的所有班级

📅 排课操作：
• 排课预览 {班级ID} {学员ID} - 预览排课信息
• 排课 {班级ID} {学员ID} - 执行排课（先自动预览）
• 移出 {班级ID} {学员ID} - 将学员移出班级

⚙️ 单班操作：
• 允许补课 {班级ID} - 开启班级补课权限
• 禁止补课 {班级ID} - 关闭班级补课权限
• 允许插班 {班级ID} - 开启班级插班权限
• 禁止插班 {班级ID} - 关闭班级插班权限

🔒 锁班管理：
• 锁班 {班级ID} - 锁定班级
• 解锁 {班级ID} - 解锁班级

👨‍🏫 按老师批量操作：
• 解锁 {老师名} 的班 - 解锁该老师所有班
• 锁定 {老师名} 的班 - 锁定该老师所有班
• 解锁 {老师名} 英语的班 - 仅解锁英语课
• 允许补课 {老师名} 的班 - 批量开启补课

💡 排课示例：
• 排课预览 132220 24330914
• 排课 132220 24330914
• 移出 132220 24330914

⚡ 所有指令秒级响应"""


def main():
    """主函数"""
    # 创建处理器
    handler = DingTalkBotHandler(logger)
    
    # 创建凭证
    credential = dingtalk_stream.Credential(CLIENT_ID, CLIENT_SECRET)
    
    # 创建客户端
    client = dingtalk_stream.DingTalkStreamClient(credential)
    
    # 注册回调
    client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, handler)
    
    # 启动
    logger.info("=" * 50)
    logger.info("🤖 教务小助手机器人启动中...")
    logger.info("=" * 50)
    
    # 从文件加载Token
    load_token_from_file()
    
    # 检查 Token 是否有效
    if CRM_TOKEN and is_cst_token(CRM_TOKEN):
        expiry = parse_token_expiry(CRM_TOKEN)
        if expiry:
            if expiry < datetime.now():
                logger.warning(f"⚠️ CRM Token 已过期！过期时间：{expiry}")
            else:
                hours_left = (expiry - datetime.now()).total_seconds() / 3600
                if hours_left < 24:
                    logger.warning(f"⚠️ CRM Token 即将过期！剩余 {int(hours_left)} 小时")
                else:
                    logger.info(f"✅ CRM Token 有效，过期时间：{expiry}")
        else:
            logger.info("✅ CRM Token 已加载（无法解析过期时间）")
    elif CRM_TOKEN:
        logger.warning("⚠️ CRM Token 类型无效（TCT），需要CST类型的Token")
    else:
        logger.warning("⚠️ 未找到 CRM Token")
    
    logger.info("✅ 机器人已启动，等待消息...")
    logger.info("📌 按 Ctrl+C 停止服务")
    logger.info("=" * 50)
    
    client.start_forever()


if __name__ == "__main__":
    main()
