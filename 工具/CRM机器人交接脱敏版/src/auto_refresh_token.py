#!/usr/bin/env python3
"""
自动刷新 CRM Token
通过浏览器自动化登录获取新 Token
"""

import json
import os
import requests

# 配置
CRM_URL = "https://crm.vipthink.cn"
CRM_ACCOUNT = "18827663792"
CRM_PASSWORD = "rKB.978Y@5"
TOKEN_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/crm_token.json"
WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=<DINGTALK_WEBHOOK_ACCESS_TOKEN>"


def notify_dingtalk(message: str):
    """发送钉钉消息"""
    try:
        requests.post(WEBHOOK_URL, json={
            "msgtype": "text",
            "text": {"content": message}
        })
    except Exception as e:
        print(f"发送钉钉消息失败: {e}")


def update_token_in_bot(token: str):
    """更新机器人代码中的 Token"""
    bot_file = "/app/data/所有对话/主对话/dingtalk_stream_bot/bot.py"
    try:
        with open(bot_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 替换 CRM_TOKEN
        import re
        new_content = re.sub(
            r'CRM_TOKEN = "[^"]*"',
            f'CRM_TOKEN = "{token}"',
            content
        )
        
        with open(bot_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # 保存到 token 文件
        token_data = {
            "token": token,
            "updated_at": __import__('datetime').datetime.now().isoformat(),
            "updated_by": "auto_refresh"
        }
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(token_data, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        print(f"更新 Token 失败: {e}")
        return False


def restart_bot():
    """重启机器人"""
    import subprocess
    try:
        subprocess.run(["pkill", "-f", "python.*bot.py"], check=False)
        subprocess.Popen(
            ["python", "/app/data/所有对话/主对话/dingtalk_stream_bot/bot.py"],
            stdout=open("/app/data/所有对话/主对话/dingtalk_stream_bot/bot.log", 'w'),
            stderr=subprocess.STDOUT
        )
        return True
    except Exception as e:
        print(f"重启机器人失败: {e}")
        return False


if __name__ == "__main__":
    print("=== CRM Token 自动刷新 ===")
    print("请使用浏览器自动化脚本获取新 Token")
    print("或者在钉钉群发送: 更新Token xxx")
