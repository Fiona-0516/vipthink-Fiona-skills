"""
LLM意图识别模块 - 为钉钉教务机器人提供自然语言理解能力

混合方案：
1. 先尝试正则规则快速匹配
2. 正则匹配失败时调用LLM
3. LLM返回结构化意图后执行对应操作
"""

import json
import re
import os
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger("意图识别")

# LLM调用的超时时间（秒）
LLM_TIMEOUT = 5

# 置信度阈值
CONFIDENCE_THRESHOLD = 0.7

# ==================== 意图识别Prompt ====================
INTENT_PROMPT = """你是教务小助手的意图识别专家。用户会用自然语言描述操作需求，你需要提取结构化意图。

【支持的意图类型】

1. query (查班)
   - 查询可插班的班级
   - 参数：course_type(英语/粤语/台湾/豌豆明思), stage(S1-S7), 
          time_filter(时间如19:30), weekday_filter(周期如工作日/周一到周四),
          time_range_desc(时间描述如晚上/16:00以后)

2. unlock (解锁班级)
   - 允许某班级插班
   - 参数：class_id(班级ID，5位以上数字)

3. lock (锁班)
   - 禁止某班级插班
   - 参数：class_id(班级ID)

4. allow_makeup (允许补课)
   - 开启班级补课权限
   - 参数：class_id(班级ID)

5. disallow_makeup (禁止补课)
   - 关闭班级补课权限
   - 参数：class_id(班级ID)

6. batch_unlock (按老师解锁)
   - 批量解锁某老师的所有班级
   - 参数：teacher(老师名), course_type(可选：英语/粤语/台湾)

7. batch_lock (按老师锁班)
   - 批量锁定某老师的所有班级
   - 参数：teacher(老师名), course_type(可选)

8. batch_allow_makeup (按老师允许补课)
   - 批量允许某老师班级的补课
   - 参数：teacher(老师名), course_type(可选)

9. query_teacher (查看老师班级)
   - 查看某老师的所有班级
   - 参数：teacher(老师名), course_type(可选)

10. check_token (查看Token状态)
    - 查看CRM Token是否有效

11. update_token (更新Token)
    - 更新CRM Token
    - 参数：token(新Token)

12. help (查看帮助)
    - 显示帮助信息

13. unknown (无法识别)
    - 无法理解用户意图

【输出格式】
只返回JSON，不要其他内容：
{"intent": "意图类型", "params": {"参数名": "参数值"}, "confidence": 0.0-1.0, "reason": "识别理由"}

【示例】
输入："帮我查一下台湾S3的班"
输出：{"intent": "query", "params": {"course_type": "台湾", "stage": "S3"}, "confidence": 0.95, "reason": "识别为查班请求"}

输入："把83029锁了"
输出：{"intent": "lock", "params": {"class_id": "83029"}, "confidence": 0.9, "reason": "识别为锁班操作"}

输入："帮我解锁140902"
输出：{"intent": "unlock", "params": {"class_id": "140902"}, "confidence": 0.9, "reason": "识别为解锁班级"}

输入："解锁Jonery老师的班"
输出：{"intent": "batch_unlock", "params": {"teacher": "Jonery"}, "confidence": 0.85, "reason": "识别为批量解锁老师班级"}

输入："锁掉Eliza老师英语的班"
输出：{"intent": "batch_lock", "params": {"teacher": "Eliza", "course_type": "英语"}, "confidence": 0.9, "reason": "识别为批量锁定老师英语班级"}

输入："Token还有效吗"
输出：{"intent": "check_token", "params": {}, "confidence": 0.9, "reason": "识别为查看Token状态"}

【用户消息】
{message}

请返回JSON："""


# ==================== 正则规则快速匹配 ====================
# 课类列表
COURSE_TYPES = ["英语", "英文", "粤语", "台湾", "豌豆明思"]
COURSE_TYPE_ALIASES = {
    "英文": "英语",
    "台灣": "台湾",
    "英語": "英语",
    "粵語": "粤语",
    "明思": "豌豆明思",
    "豌豆豌豆明思": "豌豆明思"
}

# 周期词汇映射
WEEKDAY_MAP = {
    "周一": "周一", "周二": "周二", "周三": "周三", "周四": "周四",
    "周五": "周五", "周六": "周六", "周日": "周日", "周天": "周日",
    "工作日": "工作日", "周末": "周末"
}


def normalize_text(text: str) -> str:
    """标准化文本：统一大小写和别名"""
    text = text.replace('s1', 'S1').replace('s2', 'S2').replace('s3', 'S3')
    text = text.replace('s4', 'S4').replace('s5', 'S5').replace('s6', 'S6').replace('s7', 'S7')
    
    for alias, standard in COURSE_TYPE_ALIASES.items():
        text = text.replace(alias, standard)
    
    return text


def quick_rule_match(text: str) -> Optional[Dict[str, Any]]:
    """
    快速正则规则匹配，用于常见模式
    返回：{"intent": "...", "params": {...}, "confidence": 0.9} 或 None
    """
    text = normalize_text(text)
    
    # 提取班级ID
    class_id_match = re.search(r'(\d{5,})', text)
    class_id = class_id_match.group(1) if class_id_match else None
    
    # 帮助/测试
    if text in ["帮助", "help", "?", "？", "帮帮我", "怎么用"]:
        return {"intent": "help", "params": {}, "confidence": 0.95, "reason": "识别为帮助请求"}
    
    if text in ["测试", "test", "在吗", "你好"]:
        return {"intent": "test", "params": {}, "confidence": 0.95, "reason": "识别为测试请求"}
    
    # 查看Token状态
    if any(kw in text for kw in ["Token还有效", "token还有效", "Token状态", "token状态", "token还有效吗", "Token有效吗"]):
        return {"intent": "check_token", "params": {}, "confidence": 0.9, "reason": "识别为查看Token状态"}
    
    # 解锁班级
    if class_id and (re.search(r'(?:帮.*)?解(?:除)?锁', text) or re.search(r'(?:帮.*)?开锁', text)):
        return {"intent": "unlock", "params": {"class_id": class_id}, "confidence": 0.9, "reason": f"识别为解锁班级{class_id}"}
    
    # 锁班
    if class_id and (re.search(r'(?:把|帮.*)?(?:上)?锁', text) or re.search(r'(?:把|帮.*)?锁(?:定)?了?', text)):
        return {"intent": "lock", "params": {"class_id": class_id}, "confidence": 0.9, "reason": f"识别为锁班{class_id}"}
    
    # 允许补课
    if class_id and re.search(r'(?:允许|开启|打开).*补课', text):
        return {"intent": "allow_makeup", "params": {"class_id": class_id}, "confidence": 0.9, "reason": f"识别为允许补课{class_id}"}
    
    # 禁止补课
    if class_id and re.search(r'(?:禁止|关闭|取消).*补课', text):
        return {"intent": "disallow_makeup", "params": {"class_id": class_id}, "confidence": 0.9, "reason": f"识别为禁止补课{class_id}"}
    
    # 按老师解锁 - 匹配 "解锁[老师名]的班" 或 "解锁[老师名]老师的班"
    unlock_teacher_match = re.search(r'解(?:除)?锁\s*(.+?)(?:老师)?\s*(?:的?班|老師的?班)', text)
    if unlock_teacher_match:
        teacher = unlock_teacher_match.group(1).strip()
        course_type = None
        if "英语" in text:
            course_type = "英语"
        elif "粤语" in text:
            course_type = "粤语"
        elif "台湾" in text:
            course_type = "台湾"
        if teacher:
            return {"intent": "batch_unlock", "params": {"teacher": teacher, "course_type": course_type}, "confidence": 0.85, "reason": f"识别为批量解锁{teacher}的班级"}
    
    # 按老师锁班 - 匹配 "锁[老师名]的班" 或 "锁掉[老师名]的班" 或 "锁定[老师名]的班"
    # 老师名在课类前面
    lock_teacher_match = re.search(r'(?:(?:上)?锁(?:定|掉)?)\s*(.+?)(?:老师|老師)?\s*(?:的?班|老師的?班)', text)
    if lock_teacher_match:
        teacher = lock_teacher_match.group(1).strip()
        # 如果老师名包含课类，需要分离
        for course in COURSE_TYPES:
            if teacher.endswith(course):
                teacher = teacher[:-len(course)].strip()
                break
        course_type = None
        if "英语" in text:
            course_type = "英语"
        elif "粤语" in text:
            course_type = "粤语"
        elif "台湾" in text:
            course_type = "台湾"
        if teacher:
            return {"intent": "batch_lock", "params": {"teacher": teacher, "course_type": course_type}, "confidence": 0.85, "reason": f"识别为批量锁定{teacher}的班级"}
    
    # 查班：课类S阶段格式
    for course in COURSE_TYPES:
        match = re.search(rf'{course}S(\d+)', text)
        if match:
            stage = f"S{match.group(1)}"
            params = {"course_type": course, "stage": stage}
            
            # 检查是否有时间/周期筛选
            time_match = re.search(r'(\d{1,2}:\d{2})', text)
            if time_match:
                params["time_filter"] = time_match.group(1)
            
            # 检查周期
            weekday_patterns = [
                r'(周[一二三四五六日天]\s*(?:到|至|-|~)\s*周[一二三四五六日天])',
                r'(工作日|周末)',
                r'(周[一二三四五六日天]+(?:\s*周[一二三四五六日天]+)*)',
            ]
            for pattern in weekday_patterns:
                weekday_match = re.search(pattern, text)
                if weekday_match:
                    params["weekday_filter"] = weekday_match.group(1)
                    break
            
            return {"intent": "query", "params": params, "confidence": 0.9, "reason": f"识别为查班{course}{stage}"}
    
    # 查看老师班级 - 匹配 "看看[老师名]有哪些班" 或 "[老师名]的班"
    # 格式：看看张老师有哪些班
    teacher_query_match = re.search(r'看看\s*(.+?)(?:老师|老師)?\s*(?:有哪些班|的班|的班级)', text)
    if teacher_query_match:
        teacher = teacher_query_match.group(1).strip()
        if teacher and len(teacher) >= 2:
            course_type = None
            if "英语" in text:
                course_type = "英语"
            elif "粤语" in text:
                course_type = "粤语"
            elif "台湾" in text:
                course_type = "台湾"
            return {"intent": "query_teacher", "params": {"teacher": teacher, "course_type": course_type}, "confidence": 0.8, "reason": f"识别为查询{teacher}老师班级"}
    
    return None


# ==================== LLM调用 ====================

async def call_llm_async(prompt: str) -> Optional[str]:
    """异步调用LLM，返回原始响应文本"""
    import requests
    
    api_token = os.environ.get('COZE_API_TOKEN')
    cozeloop_token = os.environ.get('COZELOOP_API_TOKEN')
    openai_key = os.environ.get('OPENAI_API_KEY')
    openai_base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
    
    try:
        # 尝试方式1：使用 cozeloop SDK
        if cozeloop_token:
            try:
                import cozeloop
                from cozeloop.entities.prompt import Message
                
                client = cozeloop.new_client()
                msg = Message(role='user', content=prompt)
                result = await asyncio.wait_for(
                    client.aexecute_prompt(
                        prompt_key='intent_parser',
                        messages=[msg]
                    ),
                    timeout=LLM_TIMEOUT
                )
                if result and result.content:
                    return result.content
            except Exception as e:
                logger.warning(f"cozeloop调用失败: {e}")
        
        # 尝试方式2：使用 OpenAI 兼容 API
        if openai_key and openai_key.strip():
            try:
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 500
                }
                
                response = requests.post(
                    f"{openai_base.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=LLM_TIMEOUT
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception as e:
                logger.warning(f"OpenAI API调用失败: {e}")
        
        # 尝试方式3：直接调用 Coze API (非流式)
        if api_token:
            try:
                # 使用Coze的chat API
                import httpx
                
                headers = {
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json"
                }
                
                # 构建对话消息
                messages = [{"role": "user", "content": prompt, "content_type": "text"}]
                
                # 获取workspace_id和bot_id
                workspace_id = os.environ.get('COZELOOP_WORKSPACE_ID', '7491274638526496809')
                bot_id = os.environ.get('COZE_BOT_ID', workspace_id)  # 使用workspace_id作为bot_id
                
                async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
                    response = await client.post(
                        "https://api.coze.com/v1/chat",
                        headers=headers,
                        json={
                            "bot_id": bot_id,
                            "user_id": "intent_parser",
                            "stream": False,
                            "additional_messages": messages
                        }
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        if result.get("code") == 0:
                            # 轮询获取结果
                            chat_id = result.get("data", {}).get("id")
                            conversation_id = result.get("data", {}).get("conversation_id")
                            
                            # 等待结果
                            for _ in range(30):  # 最多等待30秒
                                await asyncio.sleep(1)
                                msg_response = await client.get(
                                    f"https://api.coze.com/v1/chat/retrieve?chat_id={chat_id}&conversation_id={conversation_id}",
                                    headers=headers
                                )
                                if msg_response.status_code == 200:
                                    msg_data = msg_response.json()
                                    if msg_data.get("data", {}).get("status") == "completed":
                                        # 获取消息内容
                                        msgs_response = await client.get(
                                            f"https://api.coze.com/v1/messages?chat_id={chat_id}&conversation_id={conversation_id}",
                                            headers=headers
                                        )
                                        if msgs_response.status_code == 200:
                                            msgs = msgs_response.json()
                                            for msg in msgs.get("data", []):
                                                if msg.get("role") == "assistant":
                                                    return msg.get("content", "")
                                        break
            except Exception as e:
                logger.warning(f"Coze API调用失败: {e}")
                
    except Exception as e:
        logger.error(f"LLM调用异常: {e}")
    
    return None


def call_llm_sync(prompt: str) -> Optional[str]:
    """同步调用LLM"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在异步环境中，创建新loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, call_llm_async(prompt))
                return future.result(timeout=LLM_TIMEOUT + 2)
        else:
            return loop.run_until_complete(call_llm_async(prompt))
    except Exception as e:
        logger.error(f"同步LLM调用失败: {e}")
    return None


def parse_llm_response(response: str) -> Optional[Dict[str, Any]]:
    """解析LLM返回的JSON"""
    if not response:
        return None
    
    try:
        # 尝试提取JSON
        # 去掉可能的markdown代码块
        response = re.sub(r'```json\s*', '', response)
        response = re.sub(r'```\s*', '', response)
        response = response.strip()
        
        # 找到JSON开始和结束
        start = response.find('{')
        end = response.rfind('}') + 1
        
        if start >= 0 and end > start:
            json_str = response[start:end]
            result = json.loads(json_str)
            
            # 验证必要字段
            if "intent" in result:
                return {
                    "intent": result.get("intent", "unknown"),
                    "params": result.get("params", {}),
                    "confidence": float(result.get("confidence", 0)),
                    "reason": result.get("reason", "")
                }
    except json.JSONDecodeError as e:
        logger.warning(f"JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"响应解析异常: {e}")
    
    return None


async def parse_intent_llm_async(message: str) -> Optional[Dict[str, Any]]:
    """
    使用LLM解析用户消息意图
    返回: {"intent": "query", "params": {...}, "confidence": 0.9, "reason": "..."}
    """
    prompt = INTENT_PROMPT.format(message=message)
    
    response = await call_llm_async(prompt)
    if response:
        return parse_llm_response(response)
    
    return None


def parse_intent_llm(message: str) -> Optional[Dict[str, Any]]:
    """同步版本"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, parse_intent_llm_async(message))
                return future.result(timeout=LLM_TIMEOUT + 3)
        else:
            return loop.run_until_complete(parse_intent_llm_async(message))
    except Exception as e:
        logger.error(f"LLM意图识别失败: {e}")
    return None


# ==================== 主入口 ====================

def parse_intent(message: str, use_llm: bool = True) -> Optional[Dict[str, Any]]:
    """
    解析用户消息意图
    混合策略：
    1. 先用正则规则快速匹配
    2. 规则匹配失败且use_llm=True时，调用LLM
    
    返回: {"intent": "...", "params": {...}, "confidence": 0.0-1.0, "reason": "..."}
    """
    if not message or not message.strip():
        return None
    
    message = message.strip()
    
    # 步骤1：正则规则快速匹配
    rule_result = quick_rule_match(message)
    if rule_result and rule_result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
        logger.info(f"正则匹配成功: {rule_result['intent']} - {rule_result.get('reason', '')}")
        return rule_result
    
    # 步骤2：调用LLM
    if use_llm:
        logger.info(f"正则未匹配，调用LLM: {message[:50]}...")
        llm_result = parse_intent_llm(message)
        if llm_result and llm_result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            logger.info(f"LLM匹配成功: {llm_result['intent']} - {llm_result.get('reason', '')}")
            return llm_result
        else:
            logger.info(f"LLM匹配失败或置信度不足")
    
    return None


async def parse_intent_async(message: str, use_llm: bool = True) -> Optional[Dict[str, Any]]:
    """
    异步版本的意图解析
    """
    if not message or not message.strip():
        return None
    
    message = message.strip()
    
    # 步骤1：正则规则快速匹配
    rule_result = quick_rule_match(message)
    if rule_result and rule_result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
        logger.info(f"正则匹配成功: {rule_result['intent']} - {rule_result.get('reason', '')}")
        return rule_result
    
    # 步骤2：异步调用LLM
    if use_llm:
        logger.info(f"正则未匹配，调用LLM: {message[:50]}...")
        llm_result = await parse_intent_llm_async(message)
        if llm_result and llm_result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            logger.info(f"LLM匹配成功: {llm_result['intent']} - {llm_result.get('reason', '')}")
            return llm_result
        else:
            logger.info(f"LLM匹配失败或置信度不足")
    
    return None


# ==================== 测试 ====================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    test_messages = [
        "帮我查一下台湾S3的班",
        "有没有台湾S3可以插的班",
        "140902解锁",
        "把83029锁了",
        "帮我看看英语S5晚上还有什么班",
        "解锁Jonery老师的班",
        "锁掉Eliza老师英语的班",
        "Token还有效吗",
        "帮助",
        "你好",
        "允许83029补课",
        "禁止补课 140902",
        "看看张老师有哪些班",
        "查班 粤语S2 19:20",
    ]
    
    print("=" * 60)
    print("意图识别测试")
    print("=" * 60)
    
    for msg in test_messages:
        print(f"\n输入: {msg}")
        result = parse_intent(msg, use_llm=False)  # 先只用规则测试
        if result:
            print(f"结果: intent={result['intent']}, params={result.get('params', {})}, conf={result.get('confidence', 0)}")
            print(f"理由: {result.get('reason', 'N/A')}")
        else:
            print("结果: 未匹配")
    
    print("\n" + "=" * 60)
