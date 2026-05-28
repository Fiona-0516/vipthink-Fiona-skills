#!/usr/bin/env python3
"""
钉钉消息通知工具
用于在CRM操作完成后通知用户，支持发送截图
"""

import requests
import json
import time
import os

# 钉钉应用凭证
CLIENT_ID = os.getenv("DINGTALK_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DINGTALK_CLIENT_SECRET", "")

# 缓存 access_token
_access_token = None
_token_expire_time = 0


def get_access_token():
    """获取钉钉 access_token"""
    global _access_token, _token_expire_time
    
    # 如果 token 还有5分钟有效期，直接返回
    if _access_token and time.time() < _token_expire_time - 300:
        return _access_token
    
    url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    headers = {"Content-Type": "application/json"}
    data = {
        "appKey": CLIENT_ID,
        "appSecret": CLIENT_SECRET
    }
    
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    
    if result.get("expireIn"):
        _access_token = result.get("accessToken")
        _token_expire_time = time.time() + result.get("expireIn", 7200)
        return _access_token
    else:
        raise Exception(f"获取 access_token 失败: {result}")


def upload_image(image_path: str) -> str:
    """上传图片到钉钉，返回 media_id"""
    access_token = get_access_token()
    
    url = f"https://oapi.dingtalk.com/media/upload?access_token={access_token}&type=image"
    
    with open(image_path, 'rb') as f:
        files = {'media': f}
        response = requests.post(url, files=files)
    
    result = response.json()
    if result.get("media_id"):
        return result["media_id"]
    else:
        raise Exception(f"上传图片失败: {result}")


def send_message_with_image(staff_id: str, message: str, image_path: str = None):
    """发送消息给指定用户，可附带图片
    
    Args:
        staff_id: 用户的 staff_id
        message: 消息内容
        image_path: 图片文件路径（可选）
    """
    access_token = get_access_token()
    
    # 如果有图片，先上传
    media_id = None
    if image_path and os.path.exists(image_path):
        try:
            media_id = upload_image(image_path)
        except Exception as e:
            print(f"上传图片失败: {e}")
    
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    headers = {
        "Content-Type": "application/json",
        "x-acs-dingtalk-access-token": access_token
    }
    
    if media_id:
        # 发送图片消息
        data = {
            "robotCode": CLIENT_ID,
            "userIds": [staff_id],
            "msgKey": "sampleImageMsg",
            "msgParam": json.dumps({
                "photoURL": media_id  # 使用 media_id
            }, ensure_ascii=False)
        }
        response = requests.post(url, headers=headers, json=data)
        result = response.json()
        
        # 再发送文本消息
        data = {
            "robotCode": CLIENT_ID,
            "userIds": [staff_id],
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": message}, ensure_ascii=False)
        }
        response = requests.post(url, headers=headers, json=data)
    else:
        # 只发送文本消息
        data = {
            "robotCode": CLIENT_ID,
            "userIds": [staff_id],
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": message}, ensure_ascii=False)
        }
        response = requests.post(url, headers=headers, json=data)
    
    return response.json()


if __name__ == "__main__":
    # 测试
    result = send_message_with_image(
        "15505729691213213", 
        "✅ 班级81216操作完成",
        "/app/data/所有对话/主对话/dingtalk_stream_bot/class_81216_after_click.png"
    )
    print(result)
