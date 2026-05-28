# -*- coding: utf-8 -*-
"""
企业微信客服服务 (WeChat Customer Service)
基于 sync_msg API 主动拉取消息，不依赖回调URL

核心功能:
- 消息拉取: sync_msg API 轮询
- 消息发送: send_msg API 回复客户
- AI对话: 复用 wecom_ai.py 核心逻辑
- 对话存储: SQLite 存储客户对话历史
"""

import os
import re
import json
import asyncio
import logging
import sqlite3
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
import httpx
import threading

# ============== 配置 ==============

# 企业微信配置
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")
WECOM_SECRET = os.getenv("WECOM_SECRET", "")

# 微信客服配置 (如微信客服有单独的Secret，在此填写)
# WECOM_KF_SECRET = ""  # 微信客服专用Secret（可选）

# CRM配置
CRM_API_URL = "http://localhost:8090"
CRM_API_KEY = os.getenv("CRM_API_KEY", "")

# LLM配置 (从环境变量读取，留空/占位)
LLM_API_URL = os.getenv("LLM_API_URL", "").strip() or None
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip() or None
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-3.5-turbo").strip()

# 轮询配置
SYNC_INTERVAL = 3  # 轮询间隔(秒)
TOKEN_CACHE_BEFORE = 300  # token提前刷新时间(秒)

# 日志配置
LOG_FILE = "wecom_kf_service.log"

# 服务端口
SERVICE_PORT = 8092

# 数据库路径
DB_PATH = Path(__file__).parent / "wecom_kf_conversations.db"

# 状态文件
CURSOR_FILE = Path(__file__).parent / "wecom_kf_cursor.json"

# ============== 日志设置 ==============

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============== Access Token 管理 ==============

class WeComKFTokenManager:
    """企业微信客服 Access Token 管理器"""
    
    TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    
    def __init__(self, corp_id: str, corp_secret: str):
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self._token = None
        self._expires_at = 0
        self._lock = threading.Lock()
    
    def get_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """获取 Access Token"""
        with self._lock:
            if not force_refresh and self._token and time.time() < self._expires_at - TOKEN_CACHE_BEFORE:
                return self._token
            
            return self._fetch_access_token()
    
    def _fetch_access_token(self) -> Optional[str]:
        """从企业微信API获取Access Token"""
        import time as time_module
        params = {
            'corpid': self.corp_id,
            'corpsecret': self.corp_secret
        }
        
        try:
            logger.info("Fetching access token from WeCom API...")
            with httpx.Client(timeout=30) as client:
                response = client.get(self.TOKEN_URL, params=params)
                result = response.json()
            
            if result.get('errcode') == 0:
                self._token = result['access_token']
                expires_in = result.get('expires_in', 7200)
                self._expires_at = time_module.time() + expires_in
                logger.info(f"Access token refreshed, expires in {expires_in}s")
                return self._token
            else:
                logger.error(f"Failed to get access token: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Exception while fetching access token: {e}")
            return None


# ============== 消息发送模块 ==============

class WeComKFMessageSender:
    """企业微信客服消息发送器"""
    
    SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg"
    
    def __init__(self, token_manager: WeComKFTokenManager):
        self.token_manager = token_manager
    
    def send_text(self, external_userid: str, open_kfid: str, content: str) -> Dict[str, Any]:
        """
        发送文本消息
        
        Args:
            external_userid: 外部用户ID (wm开头或wo开头)
            open_kfid: 客服账号ID
            content: 文本内容
        
        Returns:
            API响应结果
        """
        access_token = self.token_manager.get_access_token()
        if not access_token:
            return {'errcode': -1, 'errmsg': 'Failed to get access token'}
        
        data = {
            'touser': external_userid,
            'open_kfid': open_kfid,
            'msgtype': 'text',
            'text': {
                'content': content
            }
        }
        
        return self._send(access_token, data)
    
    def send_menu(self, external_userid: str, open_kfid: str, 
                  head_content: str, list_items: List[str]) -> Dict[str, Any]:
        """
        发送菜单消息
        
        Args:
            external_userid: 外部用户ID
            open_kfid: 客服账号ID
            head_content: 头部内容
            list_items: 菜单选项列表
        
        Returns:
            API响应结果
        """
        access_token = self.token_manager.get_access_token()
        if not access_token:
            return {'errcode': -1, 'errmsg': 'Failed to get access token'}
        
        data = {
            'touser': external_userid,
            'open_kfid': open_kfid,
            'msgtype': 'msgmenu',
            'msgmenu': {
                'head_content': head_content,
                'list': [{'content': item} for item in list_items]
            }
        }
        
        return self._send(access_token, data)
    
    def _send(self, access_token: str, data: dict) -> Dict[str, Any]:
        """发送消息的核心方法"""
        url = f"{self.SEND_URL}?access_token={access_token}"
        
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(url, json=data)
                result = response.json()
            
            if result.get('errcode') == 0:
                logger.info(f"Message sent successfully to {data.get('touser')}")
            else:
                logger.error(f"Failed to send message: {result}")
            
            return result
            
        except Exception as e:
            logger.error(f"Exception while sending message: {e}")
            return {'errcode': -1, 'errmsg': str(e)}


# ============== 对话存储 ==============

class ConversationManager:
    """对话历史管理器"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 客户会话表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kf_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_userid TEXT NOT NULL,
                open_kfid TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                msgid TEXT,
                msgtype TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                extra_data TEXT
            )
        ''')
        
        # 用户状态表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kf_user_states (
                external_userid TEXT PRIMARY KEY,
                open_kfid TEXT,
                stage TEXT DEFAULT 'initial',
                course_type TEXT,
                stage_level TEXT,
                time_preference TEXT,
                weekday_preference TEXT,
                recommended_classes TEXT,
                selected_class TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_external_userid_created 
            ON kf_conversations(external_userid, created_at DESC)
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized: {self.db_path}")
    
    def add_message(self, external_userid: str, open_kfid: str, role: str, 
                   content: str, msgid: str = None, msgtype: str = None,
                   extra_data: dict = None):
        """添加对话消息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO kf_conversations 
            (external_userid, open_kfid, role, content, msgid, msgtype, extra_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (external_userid, open_kfid, role, content, msgid, msgtype, 
              json.dumps(extra_data) if extra_data else None))
        conn.commit()
        conn.close()
    
    def get_conversation_history(self, external_userid: str, limit: int = 20) -> List[Dict]:
        """获取对话历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT role, content, created_at, msgid, msgtype, extra_data
            FROM kf_conversations
            WHERE external_userid = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (external_userid, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        # 反转顺序（从旧到新）
        history = []
        for row in reversed(rows):
            history.append({
                'role': row[0],
                'content': row[1],
                'created_at': row[2],
                'msgid': row[3],
                'msgtype': row[4],
                'extra_data': json.loads(row[5]) if row[5] else None
            })
        return history
    
    def get_user_state(self, external_userid: str) -> Dict:
        """获取用户状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM kf_user_states WHERE external_userid = ?', (external_userid,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'external_userid': row[0],
                'open_kfid': row[1],
                'stage': row[2],
                'course_type': row[3],
                'stage_level': row[4],
                'time_preference': row[5],
                'weekday_preference': row[6],
                'recommended_classes': json.loads(row[7]) if row[7] else None,
                'selected_class': json.loads(row[8]) if row[8] else None,
                'last_updated': row[9]
            }
        return {
            'external_userid': external_userid,
            'stage': 'initial',
            'course_type': None,
            'stage_level': None,
            'time_preference': None,
            'weekday_preference': None,
            'recommended_classes': None,
            'selected_class': None
        }
    
    def update_user_state(self, state: Dict):
        """更新用户状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO kf_user_states 
            (external_userid, open_kfid, stage, course_type, stage_level, 
             time_preference, weekday_preference, recommended_classes, selected_class, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            state['external_userid'],
            state.get('open_kfid'),
            state['stage'],
            state.get('course_type'),
            state.get('stage_level'),
            state.get('time_preference'),
            state.get('weekday_preference'),
            json.dumps(state.get('recommended_classes')) if state.get('recommended_classes') else None,
            json.dumps(state.get('selected_class')) if state.get('selected_class') else None,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()


# ============== CRM API 客户端 ==============

class CRMAPIClient:
    """CRM API 客户端"""
    
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
    
    async def call_command(self, command: str, **params) -> Dict[str, Any]:
        """调用CRM命令"""
        payload = {
            'command': command,
            **params
        }
        
        headers = {
            'Content-Type': 'application/json',
            'X-API-Key': self.api_key
        }
        
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.api_url}/api/command",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {'success': True, 'action': command, 'data': data}
                else:
                    return {
                        'success': False,
                        'action': command,
                        'error': f"HTTP {response.status_code}: {response.text[:200]}"
                    }
                    
        except Exception as e:
            logger.error(f"CRM API call failed: {e}")
            return {'success': False, 'action': command, 'error': str(e)}
    
    async def query_classes(self, course_type: str, stage: str, 
                           time_filter: str = None, weekday_filter: str = None) -> Dict:
        """查询可插班班级"""
        params = {
            'course_type': course_type,
            'stage': stage
        }
        if time_filter:
            params['time_filter'] = time_filter
        if weekday_filter:
            params['weekday_filter'] = weekday_filter
        
        return await self.call_command('query', **params)
    
    async def preview_enroll(self, class_id: str, user_id: str) -> Dict:
        """预览排课"""
        return await self.call_command('preview', class_id=class_id, user_id=user_id)
    
    async def enroll(self, class_id: str, user_id: str) -> Dict:
        """执行排课"""
        return await self.call_command('enroll', class_id=class_id, user_id=user_id)


# ============== AI 对话处理 ==============

class WeComKFAIClient:
    """企业微信客服 AI 对话处理核心类"""
    
    # 阶段常量
    STAGE_INITIAL = 'initial'
    STAGE_CONFIRM_TYPE = 'confirm_type'
    STAGE_CONFIRM_TIME = 'confirm_time'
    STAGE_QUERYING = 'querying'
    STAGE_RECOMMENDING = 'recommending'
    STAGE_PREVIEW = 'preview'
    STAGE_ENROLLED = 'enrolled'
    
    # 系统提示词
    SYSTEM_PROMPT = """你是豌豆素质的排课教务助手，负责海外学员的排课服务。

## 排课流程
1. 确认课类和阶段
2. 获取上课时间偏好
3. 查询可插班班级
4. 推荐班级并确认
5. 预览排课信息
6. 用户确认后执行排课
7. 发送确认信息

## 阶段判断标准
按年级定阶（优先）：
- 3-4岁：S1
- 4-5岁：S2
- 5-6岁：S3
- 6-7岁：S4
- 7-8岁：S5

如果一个月内上过Demo课，根据Demo课阶段判断。

## 上课时间建议
- 时差-19到-12：建议7:00-11:00
- 时差-11到+3：建议16:00-23:00
- 一周两次课，每次40分钟
- 建议两节课统一时间安排，可以更快开课

## 沟通话术参考
1. 首次触达：哈喽，家长您好，欢迎宝贝加入豌豆素质王国✨（学号：XXX），我是豌豆素质的排课教务老师，负责宝贝的排课安排，排课问题都可以来问我哦~

2. 核对信息：跟您核对下基本信息，宝贝现在是X岁，目前上X年级是吗？

3. 确认时间：咱们一周两次课，每次40分钟。您这边方便的上课时间是？建议两节课统一时间安排，可以更快开课哦~

4. 推荐班级：家长您好，根据您的时间偏好，帮您找到了以下班级：【班级信息】您看哪个时间比较方便？

5. 排课确认：宝贝家长您好，课程已安排好~接下来会匹配班主任老师，建立学习群对接后续课程。

6. 无合适班级：目前暂时没有与您时间匹配的班级，需要匹配其他学员共同开班，大约需要1-2周，安排好会第一时间联系您~

## 排课规则
- 插班必须从专题首讲开始排入
- 排课前必须先preview确认
- 用户确认后才能执行排课

## 重要规则
- 排课前必须先预览并确认
- 禁止不经确认直接排课
- 学员ID必须由用户提供
- 回复简洁，不要一次发太多信息
- 如果用户问的不是排课问题，可以简短回答后引导回排课话题

## CRM工具使用
当需要查班、排课、移出学员时，使用以下JSON格式标记，服务端会自动调用CRM：

{"crm_action": "query", "params": {"course_type": "英语", "stage": "S3", "time_filter": "晚上"}}

支持的CRM操作：
- query: 查询可插班班级，需要 course_type 和 stage
- preview: 预览排课信息，需要 class_id 和 user_id
- enroll: 执行排课，需要 class_id 和 user_id
- remove: 移出学员，需要 class_id 和 user_id
- unlock/teacher_unlock: 解锁学员
- lock/teacher_lock: 锁定学员
- allow_makeup/disallow_makeup: 允许/禁止补课"""
    
    def __init__(self, llm_api_url: str = None, llm_api_key: str = None,
                 crm_api_url: str = "http://localhost:8090", crm_api_key: str = None,
                 model: str = "gpt-3.5-turbo"):
        self.llm_api_url = llm_api_url
        self.llm_api_key = llm_api_key
        self.crm_client = CRMAPIClient(crm_api_url, crm_api_key) if crm_api_key else None
        self.conv_manager = ConversationManager()
        self.model = model
        
        # 加载知识库
        self._load_knowledge_base()
    
    def _load_knowledge_base(self):
        """加载知识库文件"""
        kb_path = Path(__file__).parent.parent / "用户上传" / "企微机器人知识库-精简版.md"
        if kb_path.exists():
            try:
                with open(kb_path, 'r', encoding='utf-8') as f:
                    kb_content = f.read()
                self.SYSTEM_PROMPT += f"\n\n## 知识库内容\n\n{kb_content}"
                logger.info(f"Knowledge base loaded from {kb_path}")
            except Exception as e:
                logger.warning(f"Failed to load knowledge base: {e}")
    
    async def process_message(self, external_userid: str, message: str) -> str:
        """
        处理用户消息
        
        Args:
            external_userid: 外部用户ID
            message: 用户消息
        
        Returns:
            AI回复文本
        """
        # 添加用户消息到历史
        self.conv_manager.add_message(external_userid, '', 'user', message)
        
        # 获取对话历史和状态
        history = self.conv_manager.get_conversation_history(external_userid)
        state = self.conv_manager.get_user_state(external_userid)
        
        # 构建LLM消息
        system_msg = {"role": "system", "content": self.SYSTEM_PROMPT}
        history_msgs = []
        for msg in history[-19:]:  # 保留最近19条
            history_msgs.append({"role": msg['role'], "content": msg['content']})
        history_msgs.append({"role": "user", "content": message})
        
        # 调用LLM
        llm_response = await self._call_llm(system_msg, history_msgs)
        
        # 检查是否需要调用CRM
        crm_result = await self._check_and_execute_crm(llm_response, state, external_userid)
        
        if crm_result:
            # 如果执行了CRM，重新生成回复
            history_msgs.append({"role": "assistant", "content": llm_response})
            history_msgs.append({"role": "system", "content": f"[CRM结果]: {json.dumps(crm_result, ensure_ascii=False)}"})
            llm_response = await self._call_llm(system_msg, history_msgs)
        
        # 更新状态
        self._update_state_from_message(state, message)
        
        # 添加助手回复到历史
        self.conv_manager.add_message(external_userid, '', 'assistant', llm_response)
        
        return llm_response
    
    async def _call_llm(self, system_msg: dict, history_msgs: List[dict]) -> str:
        """调用LLM API"""
        if not self.llm_api_url:
            return "抱歉，AI服务暂未配置，请联系管理员。"
        
        messages = [system_msg] + history_msgs
        
        headers = {
            "Content-Type": "application/json",
        }
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self.llm_api_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result['choices'][0]['message']['content']
                else:
                    logger.error(f"LLM API error: {response.status_code} - {response.text}")
                    return "抱歉，AI服务暂时不可用，请稍后再试。"
                    
        except Exception as e:
            logger.error(f"LLM API exception: {e}")
            return "抱歉，AI服务暂时不可用，请稍后再试。"
    
    async def _check_and_execute_crm(self, response: str, state: Dict, user_id: str) -> Optional[Dict]:
        """检查回复中是否需要调用CRM"""
        # 查找CRM动作标记
        pattern = r'\{[\s\n]*"crm_action"[\s:]+"(\w+)"[\s,\n]+"params"[\s:]+(\{[^}]+\})\s*\}'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if not matches:
            try:
                for line in response.split('\n'):
                    if '{"crm_action"' in line or '"crm_action":' in line:
                        start = line.find('{')
                        end = line.rfind('}') + 1
                        if start >= 0 and end > start:
                            json_str = line[start:end]
                            crm_data = json.loads(json_str)
                            if 'crm_action' in crm_data and 'params' in crm_data:
                                matches.append((crm_data['crm_action'], crm_data['params']))
            except:
                pass
        
        if not matches:
            return None
        
        # 执行CRM操作
        action, params = matches[0]
        logger.info(f"Executing CRM action: {action} with params: {params}")
        
        result = None
        if self.crm_client:
            if action == 'query':
                result = await self.crm_client.query_classes(
                    params.get('course_type'),
                    params.get('stage'),
                    params.get('time_filter'),
                    params.get('weekday_filter')
                )
                if result and result.get('success'):
                    data = result.get('data', [])
                    state['recommended_classes'] = data if isinstance(data, list) else [data]
                    state['stage'] = self.STAGE_RECOMMENDING
                    self.conv_manager.update_user_state(state)
            elif action == 'preview':
                result = await self.crm_client.preview_enroll(
                    params.get('class_id'),
                    user_id
                )
            elif action == 'enroll':
                result = await self.crm_client.enroll(
                    params.get('class_id'),
                    user_id
                )
                if result and result.get('success'):
                    state['stage'] = self.STAGE_ENROLLED
                    self.conv_manager.update_user_state(state)
            elif action == 'remove':
                result = await self.crm_client.call_command('remove', 
                    class_id=params.get('class_id'), user_id=user_id)
            elif action == 'unlock':
                result = await self.crm_client.call_command('unlock', user_id=user_id)
            elif action == 'lock':
                result = await self.crm_client.call_command('lock', user_id=user_id)
            elif action == 'allow_makeup':
                result = await self.crm_client.call_command('allow_makeup', user_id=user_id)
            elif action == 'disallow_makeup':
                result = await self.crm_client.call_command('disallow_makeup', user_id=user_id)
        
        if result:
            return result
        return None
    
    def _update_state_from_message(self, state: Dict, user_msg: str):
        """从消息中更新状态"""
        # 检测课类
        if '英语' in user_msg:
            state['course_type'] = '英语'
        elif '粤语' in user_msg:
            state['course_type'] = '粤语'
        elif '台湾' in user_msg:
            state['course_type'] = '台湾'
        
        # 检测阶段
        stage_match = re.search(r'S([1-7])', user_msg.upper())
        if stage_match:
            state['stage_level'] = f"S{stage_match.group(1)}"
        
        # 检测时间偏好
        if '晚上' in user_msg:
            state['time_preference'] = '晚上'
        elif '上午' in user_msg or '早上' in user_msg:
            state['time_preference'] = '上午'
        elif '下午' in user_msg:
            state['time_preference'] = '下午'
        
        # 检测周末/工作日
        if '周末' in user_msg or '周六' in user_msg or '周日' in user_msg:
            state['weekday_preference'] = '周末'
        elif '工作日' in user_msg:
            state['weekday_preference'] = '工作日'
        
        # 更新状态
        self.conv_manager.update_user_state(state)


# ============== 消息拉取服务 ==============

class WeComKFService:
    """企业微信客服服务主类"""
    
    SYNC_URL = "https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg"
    
    def __init__(self, corp_id: str, corp_secret: str, agent_id: str,
                 crm_api_url: str = CRM_API_URL, crm_api_key: str = CRM_API_KEY,
                 llm_api_url: str = None, llm_api_key: str = None):
        """
        初始化服务
        
        Args:
            corp_id: 企业ID
            corp_secret: 应用Secret
            agent_id: 应用AgentId
            crm_api_url: CRM API URL
            crm_api_key: CRM API Key
            llm_api_url: LLM API URL
            llm_api_key: LLM API Key
        """
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        
        # 初始化各模块
        self.token_manager = WeComKFTokenManager(corp_id, corp_secret)
        self.sender = WeComKFMessageSender(self.token_manager)
        self.conv_manager = ConversationManager()
        
        # 初始化AI客户端
        if llm_api_url:
            self.ai_client = WeComKFAIClient(
                llm_api_url=llm_api_url,
                llm_api_key=llm_api_key,
                crm_api_url=crm_api_url,
                crm_api_key=crm_api_key
            )
        else:
            self.ai_client = None
            logger.warning("LLM API URL 未配置，AI对话功能将不可用")
        
        # 游标状态
        self.cursor = self._load_cursor()
        self.token = None  # sync_msg返回的token
        
        # 运行状态
        self.running = False
        self._processed_msgids = set()  # 防止重复处理
    
    def _load_cursor(self) -> Optional[str]:
        """加载持久化的cursor"""
        try:
            if CURSOR_FILE.exists():
                with open(CURSOR_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded cursor from {CURSOR_FILE}")
                    return data.get('cursor')
        except Exception as e:
            logger.warning(f"Failed to load cursor: {e}")
        return None
    
    def _save_cursor(self):
        """保存cursor到持久化存储"""
        try:
            with open(CURSOR_FILE, 'w') as f:
                json.dump({
                    'cursor': self.cursor,
                    'token': self.token,
                    'saved_at': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cursor: {e}")
    
    async def sync_messages(self, open_kfid: str = None, limit: int = 100) -> List[Dict]:
        """
        拉取消息
        
        Args:
            open_kfid: 客服账号ID（可选）
            limit: 每次拉取数量
        
        Returns:
            消息列表
        """
        access_token = self.token_manager.get_access_token()
        if not access_token:
            logger.error("Failed to get access token")
            return []
        
        params = {
            'access_token': access_token,
            'limit': limit
        }
        
        # 使用上次的token加速
        if self.token:
            params['token'] = self.token
        
        if self.cursor:
            params['cursor'] = self.cursor
        
        if open_kfid:
            params['open_kfid'] = open_kfid
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(self.SYNC_URL, json=params)
                result = response.json()
            
            if result.get('errcode') == 0:
                # 更新cursor和token
                self.cursor = result.get('next_cursor')
                self.token = result.get('token')
                self._save_cursor()
                
                msg_list = result.get('msg_list', [])
                logger.info(f"Synced {len(msg_list)} messages, next_cursor: {self.cursor}")
                return msg_list
            else:
                logger.error(f"Sync failed: {result}")
                # 如果是token过期，强制刷新
                if result.get('errcode') == 40014:
                    self.token_manager.get_access_token(force_refresh=True)
                return []
                
        except Exception as e:
            logger.error(f"Exception while syncing messages: {e}")
            return []
    
    async def process_message(self, msg: Dict):
        """
        处理单条消息
        
        Args:
            msg: 消息对象
        """
        msgid = msg.get('msgid')
        if not msgid or msgid in self._processed_msgids:
            return
        
        self._processed_msgids.add(msgid)
        
        # 只保留最近100个已处理消息ID
        if len(self._processed_msgids) > 100:
            self._processed_msgids = set(list(self._processed_msgids)[-100:])
        
        msgtype = msg.get('msgtype')
        external_userid = msg.get('external_userid')
        open_kfid = msg.get('open_kfid')
        
        logger.info(f"Processing message: msgid={msgid}, msgtype={msgtype}, from={external_userid}")
        
        # 处理不同类型的消息
        if msgtype == 'event':
            await self._handle_event(msg)
        elif msgtype == 'text':
            await self._handle_text(msg, external_userid, open_kfid)
        else:
            logger.debug(f"Ignoring message type: {msgtype}")
    
    async def _handle_event(self, msg: Dict):
        """处理事件消息"""
        event_type = msg.get('event_type')
        external_userid = msg.get('external_userid')
        open_kfid = msg.get('open_kfid')
        
        logger.info(f"Event: {event_type} from {external_userid}")
        
        if event_type == 'enter_session':
            # 用户进入会话，发送欢迎语
            welcome = """哈喽，家长您好！👋

欢迎来到豌豆素质客服中心✨

我是您的排课教务老师，可以帮您：
📚 查询课程班级
📅 预约排课
❓ 解答疑问

请直接告诉我您想了解什么，或者选择您需要的服务：

1️⃣ 查班选课
2️⃣ 排课咨询
3️⃣ 其他问题

请问有什么可以帮到您的？"""
            
            self.sender.send_text(external_userid, open_kfid, welcome)
            logger.info(f"Sent welcome message to {external_userid}")
    
    async def _handle_text(self, msg: Dict, external_userid: str, open_kfid: str):
        """处理文本消息"""
        content = msg.get('text', {}).get('content', '').strip()
        
        if not content:
            return
        
        # 记录用户消息
        self.conv_manager.add_message(external_userid, open_kfid, 'user', content, msg.get('msgid'), 'text')
        
        # 处理AI对话
        if self.ai_client:
            try:
                response = await self.ai_client.process_message(external_userid, content)
            except Exception as e:
                logger.error(f"AI processing failed: {e}")
                response = "抱歉，服务出现了一些问题，请稍后再试。"
        else:
            response = "AI服务暂未配置，请联系管理员。"
        
        # 发送回复
        if response:
            self.sender.send_text(external_userid, open_kfid, response)
            logger.info(f"Sent AI response to {external_userid}")
    
    async def run_loop(self, open_kfid: str = None):
        """
        运行消息拉取循环
        
        Args:
            open_kfid: 客服账号ID（可选）
        """
        logger.info("=" * 50)
        logger.info("企业微信客服服务启动")
        logger.info(f"轮询间隔: {SYNC_INTERVAL}秒")
        logger.info(f"CRM API: {CRM_API_URL}")
        logger.info(f"LLM API: {LLM_API_URL or '未配置'}")
        logger.info("=" * 50)
        
        self.running = True
        
        while self.running:
            try:
                # 拉取消息
                messages = await self.sync_messages(open_kfid)
                
                # 处理每条消息
                for msg in messages:
                    await self.process_message(msg)
                
                # 等待下次拉取
                await asyncio.sleep(SYNC_INTERVAL)
                
            except asyncio.CancelledError:
                logger.info("Service cancelled")
                break
            except Exception as e:
                logger.error(f"Error in run loop: {e}", exc_info=True)
                await asyncio.sleep(5)  # 出错后等待5秒再重试
    
    def stop(self):
        """停止服务"""
        logger.info("Stopping service...")
        self.running = False
    
    async def run_health_server(self):
        """运行健康检查HTTP服务"""
        try:
            from fastapi import FastAPI
            import uvicorn
            
            app = FastAPI()
            
            @app.get("/health")
            async def health():
                return {
                    "status": "ok",
                    "service": "wecom_kf_service",
                    "version": "1.0.0",
                    "running": self.running,
                    "cursor": self.cursor is not None
                }
            
            @app.get("/stats")
            async def stats():
                return {
                    "processed_messages": len(self._processed_msgids),
                    "token_cached": self.token_manager._token is not None
                }
            
            config = uvicorn.Config(app, host="0.0.0.0", port=SERVICE_PORT, log_level="warning")
            server = uvicorn.Server(config)
            await server.serve()
        except ImportError:
            logger.warning("FastAPI/uvicorn not available, health server disabled")


# ============== 主程序 ==============

def main():
    """主程序入口"""
    # 创建服务实例
    service = WeComKFService(
        corp_id=WECOM_CORP_ID,
        corp_secret=WECOM_SECRET,
        agent_id=WECOM_AGENT_ID,
        crm_api_url=CRM_API_URL,
        crm_api_key=CRM_API_KEY,
        llm_api_url=LLM_API_URL,
        llm_api_key=LLM_API_KEY
    )
    
    # 注册信号处理
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping...")
        service.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 创建主循环任务
    async def main_async():
        # 同时运行消息拉取循环和健康检查服务
        await asyncio.gather(
            service.run_loop(),
            service.run_health_server(),
            return_exceptions=True
        )
    
    # 运行服务
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
    finally:
        logger.info("Service stopped")


if __name__ == '__main__':
    main()
