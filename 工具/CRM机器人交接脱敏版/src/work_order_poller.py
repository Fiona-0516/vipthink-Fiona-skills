#!/usr/bin/env python3
"""
工单轮询模块 - DEMO绿色通道工单自动处理
后台线程每5分钟轮询一次，检测新工单并通过钉钉通知
"""

import os
import sys
import json
import time
import threading
import logging
import requests
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [工单轮询] %(levelname)-8s %(message)s'
)
logger = logging.getLogger("工单轮询")

# ==================== 配置 ====================

# 工单API配置
TICKET_API_BASE = "https://ticket.vipthink.cn"
# DEMO绿色通道类型ID（workOrderTypeId）
DEMO_GREEN_CHANNEL_TYPE_ID = 1
# DEMO绿色通道服务目录ID（serviceCatalogId，用于筛选）
DEMO_GREEN_CHANNEL_CATALOG_ID = 485

# Token文件
TOKEN_FILE = current_dir / "crm_token.json"

# 已处理工单记录文件
PROCESSED_ORDERS_FILE = current_dir / "processed_orders.json"

# 钉钉WebHook
DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")

# 轮询间隔（秒）
POLL_INTERVAL = 300  # 5分钟

# 轮询ID范围
POLL_ID_MIN = 200000  # 轮询起始ID
POLL_ID_MAX = 210000  # 轮询最大ID（会动态扩展）
POLL_BATCH_SIZE = 50  # 每次轮询扫描的ID数量


# ==================== Token管理 ====================

def load_token() -> str:
    """从文件加载Token"""
    try:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("token", "")
    except Exception as e:
        logger.error(f"加载Token失败: {e}")
        return ""


def parse_token_expiry(token: str) -> Optional[datetime]:
    """解析Token过期时间"""
    try:
        import base64
        parts = token.split('.')
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        
        # 处理不同的payload格式
        if isinstance(payload, list):
            for p in payload:
                if isinstance(p, dict) and 'exp' in p:
                    return datetime.fromtimestamp(p['exp'])
        elif isinstance(payload, dict) and 'exp' in payload:
            return datetime.fromtimestamp(payload['exp'])
        
        return None
    except Exception as e:
        logger.debug(f"解析Token过期时间失败: {e}")
        return None


def is_valid_token(token: str) -> bool:
    """检查Token是否有效"""
    if not token:
        return False
    
    expiry = parse_token_expiry(token)
    if not expiry:
        return True  # 无法解析时假设有效
    
    return expiry > datetime.now()


# ==================== 已处理工单管理 ====================

def load_processed_orders() -> set:
    """加载已处理工单ID集合"""
    try:
        if PROCESSED_ORDERS_FILE.exists():
            with open(PROCESSED_ORDERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get("processed_ids", []))
    except Exception as e:
        logger.error(f"加载已处理工单失败: {e}")
    return set()


def save_processed_orders(order_ids: set):
    """保存已处理工单ID集合"""
    try:
        with open(PROCESSED_ORDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "processed_ids": list(order_ids),
                "updated_at": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存已处理工单失败: {e}")


# ==================== 工单API调用 ====================

def call_ticket_api(method: str, endpoint: str, token: str, data: dict = None, retry: int = 1) -> dict:
    """调用工单API（带重试）
    
    Args:
        method: HTTP方法 GET/POST
        endpoint: API端点（如 /v-ticket/work-order/allWorkOrderList）
        token: Bearer token
        data: 请求数据（POST时使用）
        retry: 重试次数
    
    Returns:
        API响应结果
    """
    url = f"{TICKET_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8"
    }
    
    for attempt in range(retry + 1):
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=15)
            else:
                resp = requests.post(url, headers=headers, json=data, timeout=15)
            
            result = resp.json()
            
            # 检查Token过期
            if result.get("code") == 401 or "token" in str(result.get("msg", "")).lower():
                logger.warning("Token可能已过期")
            
            return result
            
        except requests.exceptions.Timeout:
            logger.warning(f"API调用超时（尝试 {attempt + 1}/{retry + 1}）")
        except requests.exceptions.RequestException as e:
            logger.error(f"API调用失败: {e}")
        except Exception as e:
            logger.error(f"API调用异常: {e}")
        
        if attempt < retry:
            time.sleep(1)
    
    return {"code": -1, "msg": "API调用失败"}


def get_demo_green_orders(token: str, status: int = None, relate_me: int = 1) -> List[Dict]:
    """获取DEMO绿色通道工单列表（通过allWorkOrderList API查询）
    
    Args:
        token: Bearer token
        status: 工单状态筛选（4=未分配, 7=处理中, 不传=所有）
        relate_me: 关联类型（1=待我处理, 2=我处理中, 5=抄送我的）
    
    Returns:
        DEMO绿色通道工单列表
    """
    all_orders = []
    page = 1
    page_size = 50
    
    while True:
        params = {
            "page": page,
            "limit": page_size,
            "relateMe": relate_me,
            "workOrderTypeId": DEMO_GREEN_CHANNEL_TYPE_ID,
        }
        if status is not None:
            params["status"] = status
        
        result = call_ticket_api("POST", "/v-ticket/work-order/allWorkOrderList", token, params)
        
        if result.get("code") != 0:
            logger.warning(f"查询工单列表失败: code={result.get('code')} msg={result.get('msg')}")
            break
        
        orders = result.get("data", [])
        if not orders:
            break
        
        all_orders.extend(orders)
        
        # 如果返回数量小于页大小，说明没有更多了
        if len(orders) < page_size:
            break
        page += 1
    
    logger.info(f"查询DEMO绿色通道工单: status={status}, relateMe={relate_me}, 共{len(all_orders)}个")
    return all_orders


def get_order_detail(order_id: int, token: str) -> Optional[Dict]:
    """获取工单详情（包含fieldValues）"""
    
    result = call_ticket_api("GET", f"/v-ticket/work-order/detail?id={order_id}", token)
    
    # 工单详情API返回 code=0 表示成功
    if result.get("code") == 0:
        return result.get("data", {})
    else:
        logger.error(f"获取工单详情失败: {result.get('message', '未知错误')}")
        return None


# ==================== 工单信息解析 ====================

def parse_field_values(detail: Dict) -> Dict:
    """解析工单fieldValues字段，提取关键信息
    
    fieldId映射:
    - 274: 可选择学员（学员ID）
    - 275: 意向时间（周X-xx:xx）
    - 276: 备选时间（周X-xx:xx）
    - 277: 原因
    - 278: 意向课件
    - 286: 是否接受同阶阶段其他课件（是/否）
    - 287: 特殊诉求
    - 1005: 特殊语种选择
    """
    field_values = detail.get("fieldValues", [])
    
    # 构建fieldId到值的映射
    field_map = {}
    for fv in field_values:
        field_id = fv.get("fieldId")
        value = fv.get("value", "")
        field_map[field_id] = value
    
    return {
        "stu_id": field_map.get(274, ""),  # 学员ID
        "意向时间": field_map.get(275, ""),
        "备选时间": field_map.get(276, ""),
        "原因": field_map.get(277, ""),
        "意向课件": field_map.get(278, ""),
        "是否接受同阶其他课件": field_map.get(286, "否"),
        "特殊诉求": field_map.get(287, ""),
        "特殊语种选择": field_map.get(1005, "")
    }


# ==================== 钉钉通知 ====================

def send_dingtalk_notification(message: str) -> bool:
    """发送钉钉群消息通知
    
    Args:
        message: 消息内容
    
    Returns:
        是否发送成功
    """
    try:
        # 钉钉webhook需要包含关键词才能发送成功
        # 尝试添加常见关键词，如果失败则记录日志
        keywords_to_try = ['工单', 'DEMO', '通知', 'CRM']
        
        for keyword in keywords_to_try:
            try:
                data = {
                    "msgtype": "text",
                    "text": {
                        "content": f"【{keyword}】\n{message}"
                    }
                }
                
                resp = requests.post(DINGTALK_WEBHOOK_URL, json=data, timeout=10)
                result = resp.json()
                
                if result.get("errcode") == 0:
                    logger.info(f"钉钉通知发送成功 (关键词: {keyword})")
                    return True
                elif result.get("errcode") == 310000:
                    # 关键词不匹配，继续尝试下一个
                    continue
                else:
                    logger.error(f"钉钉通知发送失败: {result.get('errmsg', '未知错误')}")
                    return False
                    
            except Exception as e:
                logger.warning(f"尝试关键词 {keyword} 失败: {e}")
                continue
        
        # 所有关键词都失败，记录到日志
        logger.warning(f"钉钉webhook通知失败，所有关键词均不匹配。消息内容:\n{message}")
        return False
            
    except Exception as e:
        logger.error(f"钉钉通知发送异常: {e}")
        return False


def format_order_notification(order: Dict, detail: Dict, fields: Dict) -> str:
    """格式化工单通知消息"""
    
    message = f"""📋 新DEMO绿色通道工单
━━━━━━━━━━━━━━━
工单ID: {order.get('id', '')}
学员ID: {fields.get('stu_id', order.get('stuId', '未知'))}
━━━━━━━━━━━━━━━
⏰ 意向时间: {fields.get('意向时间', '未填写')}
🔄 备选时间: {fields.get('备选时间', '未填写')}
📚 意向课件: {fields.get('意向课件', '未填写')}
━━━━━━━━━━━━━━━
❓ 是否接受同阶其他课件: {fields.get('是否接受同阶其他课件', '否')}
💬 原因: {fields.get('原因', '未填写')}
━━━━━━━━━━━━━━━
📝 特殊诉求: {fields.get('特殊诉求', '无')}
🌐 特殊语种: {fields.get('特殊语种选择', '无')}
━━━━━━━━━━━━━━━
📄 描述: {order.get('description', '无')}
👤 创建人: {order.get('createUsername', '未知')}
🕐 创建时间: {order.get('createTime', '未知')}
━━━━━━━━━━━━━━━"""
    
    return message


# ==================== 工单处理核心 ====================

def process_single_order(order: Dict, token: str, processed_ids: set) -> bool:
    """处理单个工单
    
    Args:
        order: 工单完整信息（包含fieldValues）
        token: CRM token
        processed_ids: 已处理工单ID集合（引用传递）
    
    Returns:
        是否成功处理
    """
    order_id = order.get("id")
    
    if not order_id:
        logger.warning("工单缺少ID，跳过")
        return False
    
    # 检查是否已处理
    if order_id in processed_ids:
        logger.debug(f"工单 {order_id} 已处理过，跳过")
        return False
    
    # order已经包含完整信息，直接解析fieldValues
    detail = order  # 使用order作为detail
    fields = parse_field_values(detail)
    
    # 构造通知消息
    message = format_order_notification(order, detail, fields)
    
    # 发送钉钉通知
    success = send_dingtalk_notification(message)
    
    if success:
        # 标记为已处理
        processed_ids.add(order_id)
        save_processed_orders(processed_ids)
        logger.info(f"工单 {order_id} 处理完成")
        return True
    else:
        logger.warning(f"工单 {order_id} 通知发送失败，但标记为已处理")
        # 即使通知失败，也标记为已处理，避免重复通知
        processed_ids.add(order_id)
        save_processed_orders(processed_ids)
        return True  # 返回True因为已经记录了


# ==================== WorkOrderPoller 类 ====================

class WorkOrderPoller:
    """工单轮询器 - 后台线程定期检查新工单"""
    
    def __init__(self, interval: int = POLL_INTERVAL, poll_status: int = 4):
        """初始化轮询器
        
        Args:
            interval: 轮询间隔（秒），默认300秒（5分钟）
            poll_status: 轮询的工单状态（4=未分配, 7=处理中, None=所有）
        """
        self.interval = interval
        self.poll_status = poll_status
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._processed_ids: set = set()
        self._last_poll_time: Optional[datetime] = None
        self._poll_count = 0
        
        # 加载已处理工单
        self._processed_ids = load_processed_orders()
        logger.info(f"初始化完成，已加载 {len(self._processed_ids)} 个已处理工单，轮询状态: {poll_status}")
    
    def start(self):
        """启动轮询线程"""
        if self._running:
            logger.warning("轮询器已在运行中")
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._running = True
        logger.info(f"工单轮询器已启动，轮询间隔: {self.interval}秒")
    
    def stop(self):
        """停止轮询线程"""
        if not self._running:
            return
        
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._running = False
        logger.info("工单轮询器已停止")
    
    def poll_once(self) -> dict:
        """手动触发一次轮询（同步执行）
        
        Returns:
            轮询结果统计
        """
        logger.info("执行手动轮询...")
        
        token = load_token()
        if not token:
            return {"success": False, "message": "无法加载Token", "new_orders": 0}
        
        if not is_valid_token(token):
            return {"success": False, "message": "Token无效或已过期", "new_orders": 0}
        
        # 查询指定状态的工单
        orders = get_demo_green_orders(token, status=self.poll_status)
        
        if not orders:
            return {"success": True, "message": "没有新的工单", "new_orders": 0, "total": 0, "poll_status": self.poll_status}
        
        # 处理新工单
        processed_count = 0
        skipped_count = 0
        
        for order in orders:
            order_id = order.get("id")
            if order_id in self._processed_ids:
                skipped_count += 1
                continue
            
            # 过滤旧工单：只通知3天内创建的工单
            create_time_str = order.get("createTime", "")
            if create_time_str:
                try:
                    from datetime import timedelta
                    # 解析 createTime 格式: "2020-12-29 11:03:13"
                    create_dt = datetime.strptime(create_time_str, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() - create_dt > timedelta(days=3):
                        logger.debug(f"工单 {order_id} 创建于 {create_time_str}，超过3天，跳过")
                        # 也标记为已处理，避免下次再查
                        self._processed_ids.add(order_id)
                        save_processed_orders(self._processed_ids)
                        skipped_count += 1
                        continue
                except ValueError:
                    pass
            
            if process_single_order(order, token, self._processed_ids):
                processed_count += 1
        
        self._last_poll_time = datetime.now()
        self._poll_count += 1
        
        result = {
            "success": True,
            "message": f"轮询完成",
            "total_orders": len(orders),
            "new_orders": processed_count,
            "skipped": skipped_count,
            "poll_time": self._last_poll_time.isoformat(),
            "poll_count": self._poll_count,
            "poll_status": self.poll_status
        }
        
        logger.info(f"轮询完成: 新处理 {processed_count} 个，跳过 {skipped_count} 个")
        return result
    
    def get_status(self) -> dict:
        """获取轮询器状态"""
        return {
            "running": self._running,
            "interval": self.interval,
            "processed_count": len(self._processed_ids),
            "last_poll_time": self._last_poll_time.isoformat() if self._last_poll_time else None,
            "poll_count": self._poll_count
        }
    
    def get_pending_orders(self) -> List[Dict]:
        """获取当前未处理的工单列表"""
        token = load_token()
        if not token or not is_valid_token(token):
            return []
        
        orders = get_demo_green_orders(token, status=self.poll_status)
        
        # 过滤出未处理的工单
        pending = []
        for order in orders:
            if order.get("id") not in self._processed_ids:
                pending.append(order)
        
        return pending
    
    def process_order(self, order_id: int) -> dict:
        """手动处理指定工单
        
        Args:
            order_id: 工单ID
        
        Returns:
            处理结果
        """
        token = load_token()
        if not token:
            return {"success": False, "message": "无法加载Token"}
        
        order = {"id": order_id}
        if process_single_order(order, token, self._processed_ids):
            return {"success": True, "message": f"工单 {order_id} 处理完成"}
        else:
            return {"success": False, "message": f"工单 {order_id} 处理失败"}
    
    def _poll_loop(self):
        """轮询主循环（在后台线程中运行）"""
        logger.info("轮询线程已启动")
        
        while not self._stop_event.is_set():
            try:
                # 执行一次轮询
                self.poll_once()
                
            except Exception as e:
                logger.error(f"轮询异常: {e}")
            
            # 等待下一次轮询或停止信号
            self._stop_event.wait(self.interval)
        
        logger.info("轮询线程退出")


# ==================== 全局单例 ====================

_poller_instance: Optional[WorkOrderPoller] = None


def get_poller() -> WorkOrderPoller:
    """获取轮询器全局单例"""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = WorkOrderPoller()
    return _poller_instance


def init_poller(interval: int = POLL_INTERVAL) -> WorkOrderPoller:
    """初始化并启动轮询器"""
    poller = get_poller()
    if not poller._running:
        poller.start()
    return poller


# ==================== 主入口（测试用） ====================

if __name__ == "__main__":
    # 测试用：手动执行一次轮询
    print("=" * 50)
    print("工单轮询模块测试")
    print("=" * 50)
    
    poller = WorkOrderPoller()
    result = poller.poll_once()
    
    print("\n轮询结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
