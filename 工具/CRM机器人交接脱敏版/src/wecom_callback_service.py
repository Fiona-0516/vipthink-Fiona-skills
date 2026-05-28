# -*- coding: utf-8 -*-
"""
企业微信自建应用回调服务
FastAPI 服务，监听企微回调消息
"""

import os
import re
import json
import asyncio
import logging
import httpx
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn

# 导入本地模块
from wecom_crypto import WeComCrypto, verify_signature, decrypt_message, encrypt_message, extract_xml_field
from wecom_token import init_token_manager, get_access_token
from wecom_sender import init_sender, send_text, send_markdown
from wecom_ai import init_ai_client, process_user_message

# ============== 配置 ==============

# 企业微信配置
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")
WECOM_SECRET = os.getenv("WECOM_SECRET", "")

# 回调配置（从SECRET.md读取）
CALLBACK_TOKEN = os.getenv("WECOM_CALLBACK_TOKEN", "")
ENCODING_AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")

# CRM配置
CRM_API_URL = "http://localhost:8090"
CRM_API_KEY = os.getenv("CRM_API_KEY", "")

# LLM配置（从环境变量）
LLM_API_URL = os.getenv("OPENAI_API_URL", "").strip() or None
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "").strip() or None

# 日志配置
LOG_FILE = "wecom_service.log"

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


# ============== 全局实例 ==============

crypto = WeComCrypto(CALLBACK_TOKEN, ENCODING_AES_KEY, WECOM_CORP_ID)


# ============== FastAPI 应用 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("企业微信回调服务启动")
    logger.info("=" * 50)
    
    # 初始化Token管理器
    init_token_manager(WECOM_CORP_ID, WECOM_SECRET)
    logger.info("Token管理器初始化完成")
    
    # 初始化消息发送器
    init_sender(WECOM_AGENT_ID)
    logger.info("消息发送器初始化完成")
    
    # 初始化AI客户端
    if LLM_API_URL:
        init_ai_client(LLM_API_URL, LLM_API_KEY, CRM_API_URL, CRM_API_KEY)
        logger.info(f"AI客户端初始化完成 (LLM: {LLM_API_URL})")
    else:
        logger.warning("LLM API URL 未配置，AI对话功能将不可用")
        init_ai_client(None, None, CRM_API_URL, CRM_API_KEY)
    
    yield
    
    logger.info("企业微信回调服务关闭")


app = FastAPI(
    title="WeCom Callback Service",
    description="企业微信自建应用回调服务",
    version="1.0.0",
    lifespan=lifespan
)


# ============== 健康检查 ==============

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "wecom_callback_service",
        "version": "1.0.0"
    }


# ============== 企业微信回调接口 ==============

@app.get("/wecom/callback")
async def wecom_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...)
):
    """
    企业微信回调验证接口（GET）
    
    用于验证回调URL的有效性
    """
    logger.info(f"收到回调验证请求: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}")
    
    try:
        # 验证签名
        if not verify_signature(CALLBACK_TOKEN, timestamp, nonce, echostr):
            logger.warning("签名验证失败")
            raise HTTPException(status_code=403, detail="Signature verification failed")
        
        # 解密echostr
        decrypted = crypto.decrypt_msg(echostr)
        logger.info(f"回调验证成功，解密echostr成功")
        
        return PlainTextResponse(content=decrypted)
        
    except Exception as e:
        logger.error(f"回调验证失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/wecom/callback")
async def wecom_message(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    request: Request = None
):
    """
    企业微信消息接收接口（POST）
    
    接收并处理用户发送的消息
    """
    logger.info(f"收到消息回调: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}")
    
    try:
        # 读取请求体
        body = await request.body()
        body_str = body.decode('utf-8')
        logger.debug(f"原始请求体: {body_str[:500]}")
        
        # 解析XML获取加密消息
        msg_encrypt = extract_xml_field(body_str, 'Encrypt')
        if not msg_encrypt:
            logger.warning("未找到加密消息字段")
            return PlainTextResponse(content="success")
        
        # 验证签名
        if not verify_signature(CALLBACK_TOKEN, timestamp, nonce, msg_encrypt):
            logger.warning("消息签名验证失败")
            return PlainTextResponse(content="success")
        
        # 解密消息
        decrypted_xml = crypto.decrypt_msg(msg_encrypt)
        logger.info(f"解密消息: {decrypted_xml[:200]}...")
        
        # 提取消息内容
        from_username = extract_xml_field(decrypted_xml, 'FromUserName')
        msg_type = extract_xml_field(decrypted_xml, 'MsgType')
        content = extract_xml_field(decrypted_xml, 'Content')
        msg_id = extract_xml_field(decrypted_xml, 'MsgId')
        
        logger.info(f"消息详情: FromUserName={from_username}, MsgType={msg_type}, Content={content[:50] if content else 'N/A'}...")
        
        # 立即返回"success"（5秒内必须响应）
        asyncio.create_task(process_message_async(from_username, msg_type, content, msg_id))
        
        return PlainTextResponse(content="success")
        
    except Exception as e:
        logger.error(f"处理消息回调失败: {e}", exc_info=True)
        return PlainTextResponse(content="success")


async def process_message_async(user_id: str, msg_type: str, content: str, msg_id: str):
    """
    异步处理消息（AI处理必须在后台进行）
    """
    try:
        if msg_type != 'text':
            logger.info(f"忽略非文本消息类型: {msg_type}")
            return
        
        if not content or not content.strip():
            logger.info("空消息，跳过")
            return
        
        logger.info(f"开始处理用户 {user_id} 的消息: {content[:100]}...")
        
        # 调用AI处理
        ai_response = await process_user_message(user_id, content)
        logger.info(f"AI回复: {ai_response[:100]}...")
        
        # 发送回复
        result = send_text(user_id, ai_response)
        if result.get('errcode') == 0:
            logger.info(f"消息发送成功 to {user_id}")
        else:
            logger.warning(f"消息发送失败: {result}")
            
    except Exception as e:
        logger.error(f"异步处理消息失败: {e}", exc_info=True)


# ============== 测试接口 ==============

@app.post("/test/send")
async def test_send_message(
    user_id: str = Query(...),
    content: str = Query(...)
):
    """测试发送消息"""
    result = send_text(user_id, content)
    return result


@app.post("/test/ai")
async def test_ai_message(
    user_id: str = Query(...),
    message: str = Query(...)
):
    """测试AI处理"""
    response = await process_user_message(user_id, message)
    return {"response": response}


# ============== 主程序 ==============

def main():
    """启动服务"""
    port = int(os.getenv("WECOM_PORT", "8091"))
    
    logger.info(f"启动企业微信回调服务，端口: {port}")
    
    uvicorn.run(
        "wecom_callback_service:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
