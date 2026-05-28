# -*- coding: utf-8 -*-
"""
企业微信 AI 对话处理模块
负责意图识别、CRM调用、回复生成
"""

import json
import re
import sqlite3
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict
import httpx

logger = logging.getLogger(__name__)

# 数据库路径
DB_PATH = Path(__file__).parent / "wecom_conversations.db"


@dataclass
class ConversationState:
    """用户对话状态"""
    user_id: str
    stage: str  # initial/confirm_type/confirm_time/querying/recommending/preview/enrolled
    course_type: Optional[str] = None  # 英语/粤语/台湾
    stage_level: Optional[str] = None  # S1-S7
    time_preference: Optional[str] = None
    weekday_preference: Optional[str] = None
    recommended_classes: Optional[List[Dict]] = None
    selected_class: Optional[Dict] = None
    last_updated: str = None
    
    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()


@dataclass
class CRMResult:
    """CRM API调用结果"""
    success: bool
    action: str
    data: Any = None
    error: Optional[str] = None


class ConversationManager:
    """对话历史管理器"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                crm_action TEXT,
                extra_data TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_states (
                user_id TEXT PRIMARY KEY,
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
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_user_created 
            ON conversations(user_id, created_at DESC)
        ''')
        conn.commit()
        conn.close()
    
    def add_message(self, user_id: str, role: str, content: str, 
                   crm_action: str = None, extra_data: dict = None):
        """添加对话消息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO conversations (user_id, role, content, crm_action, extra_data)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, role, content, crm_action, json.dumps(extra_data) if extra_data else None))
        conn.commit()
        conn.close()
    
    def get_conversation_history(self, user_id: str, limit: int = 20) -> List[Dict]:
        """获取对话历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT role, content, created_at, crm_action, extra_data
            FROM conversations
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        # 反转顺序（从旧到新）
        history = []
        for row in reversed(rows):
            history.append({
                'role': row[0],
                'content': row[1],
                'created_at': row[2],
                'crm_action': row[3],
                'extra_data': json.loads(row[4]) if row[4] else None
            })
        return history
    
    def get_user_state(self, user_id: str) -> ConversationState:
        """获取用户状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_states WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return ConversationState(
                user_id=row[0],
                stage=row[1],
                course_type=row[2],
                stage_level=row[3],
                time_preference=row[4],
                weekday_preference=row[5],
                recommended_classes=json.loads(row[6]) if row[6] else None,
                selected_class=json.loads(row[7]) if row[7] else None,
                last_updated=row[8]
            )
        return ConversationState(user_id=user_id, stage='initial')
    
    def update_user_state(self, state: ConversationState):
        """更新用户状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_states 
            (user_id, stage, course_type, stage_level, time_preference, 
             weekday_preference, recommended_classes, selected_class, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            state.user_id,
            state.stage,
            state.course_type,
            state.stage_level,
            state.time_preference,
            state.weekday_preference,
            json.dumps(state.recommended_classes) if state.recommended_classes else None,
            json.dumps(state.selected_class) if state.selected_class else None,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()


class CRMAPIClient:
    """CRM API 客户端"""
    
    def __init__(self, api_url: str, api_key: str):
        """
        初始化CRM API客户端
        
        Args:
            api_url: CRM API基础URL
            api_key: API密钥
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
    
    async def call_command(self, command: str, **params) -> CRMResult:
        """
        调用CRM命令
        
        Args:
            command: 命令类型 (query/preview/enroll/remove/lock/unlock/...)
            **params: 命令参数
        
        Returns:
            CRMResult 结果
        """
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
                    return CRMResult(
                        success=True,
                        action=command,
                        data=data
                    )
                else:
                    return CRMResult(
                        success=False,
                        action=command,
                        error=f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                    
        except Exception as e:
            logger.error(f"CRM API call failed: {e}")
            return CRMResult(
                success=False,
                action=command,
                error=str(e)
            )
    
    async def query_classes(self, course_type: str, stage: str, 
                           time_filter: str = None, weekday_filter: str = None) -> CRMResult:
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
    
    async def preview_enroll(self, class_id: str, user_id: str) -> CRMResult:
        """预览排课"""
        return await self.call_command('preview', class_id=class_id, user_id=user_id)
    
    async def enroll(self, class_id: str, user_id: str) -> CRMResult:
        """执行排课"""
        return await self.call_command('enroll', class_id=class_id, user_id=user_id)
    
    async def remove_student(self, class_id: str, user_id: str) -> CRMResult:
        """移出学员"""
        return await self.call_command('remove', class_id=class_id, user_id=user_id)


class WeComAIClient:
    """企业微信 AI 对话处理核心类"""
    
    # 排课流程阶段
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

```json
{"crm_action": "query", "params": {"course_type": "英语", "stage": "S3", "time_filter": "晚上"}}
```

支持的CRM操作：
- query: 查询可插班班级，需要 course_type 和 stage
- preview: 预览排课信息，需要 class_id 和 user_id
- enroll: 执行排课，需要 class_id 和 user_id
- remove: 移出学员，需要 class_id 和 user_id"""
    
    def __init__(self, llm_api_url: str = None, llm_api_key: str = None,
                 crm_api_url: str = "http://localhost:8090", crm_api_key: str = None):
        """
        初始化AI客户端
        
        Args:
            llm_api_url: LLM API URL
            llm_api_key: LLM API Key
            crm_api_url: CRM API URL
            crm_api_key: CRM API Key
        """
        self.llm_api_url = llm_api_url or self._get_llm_config()
        self.llm_api_key = llm_api_key
        self.crm_client = CRMAPIClient(crm_api_url, crm_api_key) if crm_api_key else None
        self.conv_manager = ConversationManager()
        
        # 加载知识库
        self._load_knowledge_base()
    
    def _get_llm_config(self) -> Optional[str]:
        """从环境变量或配置文件获取LLM配置"""
        import os
        base_url = os.getenv('OPENAI_BASE_URL', '').strip()
        if base_url:
            return base_url.rstrip('/') + '/v1/chat/completions'
        return None
    
    def _load_knowledge_base(self):
        """加载知识库文件"""
        kb_path = Path(__file__).parent.parent / "用户上传" / "企微机器人知识库-精简版.md"
        if kb_path.exists():
            try:
                with open(kb_path, 'r', encoding='utf-8') as f:
                    kb_content = f.read()
                # 将知识库内容追加到系统提示词
                self.SYSTEM_PROMPT += f"\n\n## 知识库内容\n\n{kb_content}"
                logger.info(f"Knowledge base loaded from {kb_path}")
            except Exception as e:
                logger.warning(f"Failed to load knowledge base: {e}")
    
    def _format_history(self, history: List[Dict]) -> str:
        """格式化对话历史"""
        messages = []
        for msg in history:
            role = msg['role']
            content = msg['content']
            messages.append(f"{role}: {content}")
        return "\n".join(messages)
    
    async def process_message(self, user_id: str, message: str) -> str:
        """
        处理用户消息
        
        Args:
            user_id: 用户ID
            message: 用户消息
        
        Returns:
            AI回复文本
        """
        # 添加用户消息到历史
        self.conv_manager.add_message(user_id, 'user', message)
        
        # 获取对话历史和状态
        history = self.conv_manager.get_conversation_history(user_id)
        state = self.conv_manager.get_user_state(user_id)
        
        # 构建LLM消息
        system_msg = {"role": "system", "content": self.SYSTEM_PROMPT}
        history_msgs = []
        for msg in history[-19:]:  # 保留最近19条
            history_msgs.append({"role": msg['role'], "content": msg['content']})
        history_msgs.append({"role": "user", "content": message})
        
        # 调用LLM
        llm_response = await self._call_llm(system_msg, history_msgs)
        
        # 检查是否需要调用CRM
        crm_result = await self._check_and_execute_crm(llm_response, state, user_id)
        
        if crm_result:
            # 如果执行了CRM，重新生成回复
            history_msgs.append({"role": "assistant", "content": llm_response})
            history_msgs.append({"role": "system", "content": f"[CRM结果]: {json.dumps(crm_result, ensure_ascii=False)}"})
            llm_response = await self._call_llm(system_msg, history_msgs)
        
        # 更新状态
        self._update_state_from_message(state, message, llm_response)
        
        # 添加助手回复到历史
        self.conv_manager.add_message(user_id, 'assistant', llm_response)
        
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
            "model": "gpt-3.5-turbo",
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
    
    async def _check_and_execute_crm(self, response: str, state: ConversationState, user_id: str) -> Optional[Dict]:
        """检查回复中是否需要调用CRM"""
        # 查找CRM动作标记
        pattern = r'\{[\s\n]*"crm_action"[\s:]+"(\w+)"[\s,\n]+"params"[\s:]+(\{[^}]+\})\s*\}'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if not matches:
            # 尝试另一种格式
            try:
                # 提取所有JSON对象
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
                # 更新状态
                if result.success and result.data:
                    state.recommended_classes = result.data if isinstance(result.data, list) else [result.data]
                    state.stage = self.STAGE_RECOMMENDING
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
                if result.success:
                    state.stage = self.STAGE_ENROLLED
        
        if result:
            return {
                'action': action,
                'success': result.success,
                'data': result.data if result.success else None,
                'error': result.error
            }
        return None
    
    def _update_state_from_message(self, state: ConversationState, user_msg: str, ai_response: str):
        """从消息中更新状态"""
        user_msg_lower = user_msg.lower()
        
        # 检测课类
        if '英语' in user_msg:
            state.course_type = '英语'
        elif '粤语' in user_msg:
            state.course_type = '粤语'
        elif '台湾' in user_msg:
            state.course_type = '台湾'
        
        # 检测阶段
        stage_match = re.search(r'S([1-7])', user_msg.upper())
        if stage_match:
            state.stage_level = f"S{stage_match.group(1)}"
        
        # 检测时间偏好
        if '晚上' in user_msg:
            state.time_preference = '晚上'
        elif '上午' in user_msg or '早上' in user_msg:
            state.time_preference = '上午'
        elif '下午' in user_msg:
            state.time_preference = '下午'
        
        # 检测周末/工作日
        if '周末' in user_msg or '周六' in user_msg or '周日' in user_msg:
            state.weekday_preference = '周末'
        elif '工作日' in user_msg:
            state.weekday_preference = '工作日'
        
        # 更新状态
        self.conv_manager.update_user_state(state)


# 全局实例
_ai_client: Optional[WeComAIClient] = None


def init_ai_client(llm_api_url: str = None, llm_api_key: str = None,
                   crm_api_url: str = "http://localhost:8090", crm_api_key: str = None) -> WeComAIClient:
    """初始化全局AI客户端"""
    global _ai_client
    _ai_client = WeComAIClient(llm_api_url, llm_api_key, crm_api_url, crm_api_key)
    return _ai_client


def get_ai_client() -> Optional[WeComAIClient]:
    """获取全局AI客户端"""
    return _ai_client


async def process_user_message(user_id: str, message: str) -> str:
    """处理用户消息的便捷函数"""
    if _ai_client:
        return await _ai_client.process_message(user_id, message)
    return "AI服务未初始化"


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    # 初始化AI客户端（不使用真实LLM）
    client = WeComAIClient(
        llm_api_url="https://api.openai.com/v1/chat/completions",
        llm_api_key="test",
        crm_api_url="http://localhost:8090",
        crm_api_key="<CRM_API_KEY>"
    )
    
    # 测试对话管理
    state = client.conv_manager.get_user_state("test_user")
    print(f"Initial state: {asdict(state)}")
    
    # 添加测试消息
    client.conv_manager.add_message("test_user", "user", "你好，我想给孩子排课")
    history = client.conv_manager.get_conversation_history("test_user")
    print(f"History count: {len(history)}")
