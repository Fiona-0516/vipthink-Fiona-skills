# -*- coding: utf-8 -*-
"""
企业微信消息发送模块
"""

import json
import logging
from typing import Optional, Dict, Any
import httpx

from wecom_token import get_access_token

logger = logging.getLogger(__name__)


class WeComMessageSender:
    """企业微信消息发送器"""
    
    SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
    
    def __init__(self, agent_id: str):
        """
        初始化消息发送器
        
        Args:
            agent_id: 应用AgentId
        """
        self.agent_id = agent_id
    
    def send_text(self, user_id: str, content: str, access_token: str = None) -> Dict[str, Any]:
        """
        发送文本消息
        
        Args:
            user_id: 用户ID
            content: 文本内容
            access_token: Access Token（可选，自动获取）
        
        Returns:
            API响应结果
        """
        if not access_token:
            access_token = get_access_token()
            if not access_token:
                return {'errcode': -1, 'errmsg': 'Failed to get access token'}
        
        data = {
            'touser': user_id,
            'agentid': self.agent_id,
            'msgtype': 'text',
            'text': {
                'content': content
            }
        }
        
        return self._send(access_token, data)
    
    def send_markdown(self, user_id: str, content: str, access_token: str = None) -> Dict[str, Any]:
        """
        发送Markdown消息
        
        Args:
            user_id: 用户ID
            content: Markdown内容
            access_token: Access Token（可选，自动获取）
        
        Returns:
            API响应结果
        """
        if not access_token:
            access_token = get_access_token()
            if not access_token:
                return {'errcode': -1, 'errmsg': 'Failed to get access token'}
        
        data = {
            'touser': user_id,
            'agentid': self.agent_id,
            'msgtype': 'markdown',
            'markdown': {
                'content': content
            }
        }
        
        return self._send(access_token, data)
    
    def send_news(self, user_id: str, articles: list, access_token: str = None) -> Dict[str, Any]:
        """
        发送图文消息
        
        Args:
            user_id: 用户ID
            articles: 图文列表，每个包含 title, description, url, picurl
            access_token: Access Token（可选，自动获取）
        
        Returns:
            API响应结果
        """
        if not access_token:
            access_token = get_access_token()
            if not access_token:
                return {'errcode': -1, 'errmsg': 'Failed to get access token'}
        
        data = {
            'touser': user_id,
            'agentid': self.agent_id,
            'msgtype': 'news',
            'news': {
                'articles': articles
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


# 全局实例
_sender: Optional[WeComMessageSender] = None


def init_sender(agent_id: str) -> WeComMessageSender:
    """初始化全局消息发送器"""
    global _sender
    _sender = WeComMessageSender(agent_id)
    return _sender


def get_sender() -> Optional[WeComMessageSender]:
    """获取全局消息发送器"""
    return _sender


def send_text(user_id: str, content: str, access_token: str = None) -> Dict[str, Any]:
    """发送文本消息的便捷函数"""
    if _sender:
        return _sender.send_text(user_id, content, access_token)
    return {'errcode': -1, 'errmsg': 'Sender not initialized'}


def send_markdown(user_id: str, content: str, access_token: str = None) -> Dict[str, Any]:
    """发送Markdown消息的便捷函数"""
    if _sender:
        return _sender.send_markdown(user_id, content, access_token)
    return {'errcode': -1, 'errmsg': 'Sender not initialized'}


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    # 这里需要先初始化token manager
    from wecom_token import init_token_manager, get_access_token
    
    corp_id = "ww1c944b278160ee01"
    corp_secret = "<WECOM_SECRET>"
    
    init_token_manager(corp_id, corp_secret)
    token = get_access_token()
    
    if token:
        print(f"Token OK: {token[:20]}...")
        
        # 测试发送
        sender = WeComMessageSender("1000009")
        result = sender.send_text("test_user", "测试消息")
        print(f"Send result: {result}")
    else:
        print("Token fetch failed")
