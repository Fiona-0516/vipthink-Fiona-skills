#!/usr/bin/env python3
"""
钉钉企业机器人发送消息工具
通过 Stream 模式的 API 发送消息到群聊
"""

import requests
import json
import time
from typing import Optional

# 钉钉应用凭证
CLIENT_ID = os.getenv("DINGTALK_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DINGTALK_CLIENT_SECRET", "")

# Token 缓存
_access_token = None
_token_expire_time = 0


def get_access_token() -> Optional[str]:
    """获取企业应用 access_token"""
    global _access_token, _token_expire_time
    
    # 检查缓存
    if _access_token and time.time() < _token_expire_time:
        return _access_token
    
    url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    data = {
        "appKey": CLIENT_ID,
        "appSecret": CLIENT_SECRET
    }
    
    try:
        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()
        
        if result.get("expireIn"):
            _access_token = result.get("accessToken")
            _token_expire_time = time.time() + result.get("expireIn", 7200) - 300
            return _access_token
        else:
            print(f"获取token失败: {result}")
            return None
    except Exception as e:
        print(f"请求失败: {e}")
        return None


def send_group_message(conversation_id: str, msg: str, msg_type: str = "text") -> bool:
    """发送消息到群聊
    
    Args:
        conversation_id: 群聊ID
        msg: 消息内容
        msg_type: 消息类型 text/markdown
    
    Returns:
        是否发送成功
    """
    token = get_access_token()
    if not token:
        return False
    
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    
    headers = {
        "x-acs-dingtalk-access-token": token,
        "Content-Type": "application/json"
    }
    
    if msg_type == "markdown":
        content = json.dumps({"title": "教务小助手通知", "text": msg}, ensure_ascii=False)
    else:
        content = json.dumps({"content": msg}, ensure_ascii=False)
    
    data = {
        "robotCode": CLIENT_ID,
        "userIds": [],  # 群消息不需要指定用户
        "msgKey": f"sample{msg_type.capitalize()}",
        "msgParam": content,
        "openConversationId": conversation_id
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        result = resp.json()
        
        if result.get("processQueryKeys"):
            print(f"消息发送成功: {conversation_id}")
            return True
        else:
            print(f"消息发送失败: {result}")
            return False
    except Exception as e:
        print(f"发送请求失败: {e}")
        return False


# 测试
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("用法: python dingtalk_send.py <conversation_id> <message>")
        sys.exit(1)
    
    conv_id = sys.argv[1]
    message = sys.argv[2]
    
    success = send_group_message(conv_id, message)
    print(f"发送结果: {'成功' if success else '失败'}")
