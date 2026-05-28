#!/usr/bin/env python3
"""
更新 CRM Token 并重启机器人
支持多种 Token 格式：
1. 纯 JWT Token
2. "Bearer " + Token
3. JSON 字符串格式: {"Authorization":"Bearer xxx"}

重要：只更新 crm_token.json，bot.py 启动时会自动从文件加载
"""

import time
import re
import os
import sys
import subprocess
import json
import base64
import requests
from datetime import datetime

BOT_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/bot.py"
TOKEN_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/crm_token.json"


def parse_token(raw_token: str) -> str:
    """解析各种格式的Token，提取纯净的JWT Token"""
    token = raw_token.strip()
    
    # JSON字符串格式
    if token.startswith('{') and token.endswith('}'):
        try:
            data = json.loads(token)
            auth_value = data.get('Authorization', '')
            if auth_value.startswith('Bearer '):
                token = auth_value[7:]
            else:
                token = auth_value
        except json.JSONDecodeError:
            pass
    
    # Bearer前缀
    elif token.startswith('Bearer '):
        token = token[7:]
    
    return token


def is_cst_token(token: str) -> bool:
    """检查Token是否是CST类型（有效），而非TCT类型（无效）"""
    try:
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.b64decode(payload).decode('utf-8')
        return 'CST' in decoded and 'TCT' not in decoded
    except Exception:
        return False


def get_token_uid(token: str) -> str:
    """获取Token中的UID"""
    try:
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.b64decode(payload).decode('utf-8')
        import re
        uid_match = re.search(r'"uid"\s*:\s*(\d+)', decoded)
        return uid_match.group(1) if uid_match else "未知"
    except Exception:
        return "未知"


def is_crm_token_key_token(token: str) -> bool:
    """检测Token是否来自 CRM_TOKEN_KEY（旧版工单token，API不认）
    
    CRM_TOKEN_KEY 的 token 虽然JWT格式也是CST+uid=3301，但服务端不认。
    典型特征：token长度较短（~394字符），与 TOKEN_KEY 的token长度不同。
    但最可靠的区分方式是API调用验证。
    """
    # 这个函数主要用于日志提示，真正判断靠API验证
    return False  # 无法仅从token内容区分，依赖API验证


def verify_token(token: str) -> tuple:
    """验证Token是否有效（使用只读接口classs/manage测试）
    
    重要：JWT格式正确（CST+uid=3301）不代表Token有效！
    如果取了 CRM_TOKEN_KEY 的 token，JWT解析也是CST类型，但API会返回"非法员工令牌"。
    必须通过API调用验证。
    """
    try:
        clean_token = token.strip()
        if clean_token.startswith('Bearer '):
            clean_token = clean_token[7:]
        
        # 先检查Token类型
        if not is_cst_token(clean_token):
            return False, "Token类型无效（TCT），需要CST类型的Token"
        
        # 检查UID
        uid = get_token_uid(clean_token)
        if uid != "3301":
            return False, f"Token UID={uid}，需要UID=3301"
        
        # 使用只读接口 classs/manage 验证（不修改任何数据）
        test_url = "https://ems.vipthink.cn/gateway/route__jw/api/classs/manage"
        headers = {"Authorization": f"Bearer {clean_token}", "Content-Type": "application/json"}
        data = {"classStuType": 0, "isMax": 1, "pageNo": 1, "pageSize": 1}
        resp = requests.post(test_url, headers=headers, json=data, timeout=10)
        result = resp.json()
        
        if result.get("code") == 200:
            return True, "Token验证成功，API可正常调用"
        elif "非法员工" in result.get("msg", "") or "非法员工" in str(result.get("data", {}).get("info", "")):
            return False, f"Token被服务端拒绝（{result.get('msg')}），可能是取了CRM_TOKEN_KEY的token，必须从TOKEN_KEY提取"
        elif "用户识别失败" in result.get("msg", ""):
            return False, f"Token已失效（{result.get('msg')}），需要重新登录"
        else:
            return False, f"API返回: code={result.get('code')} msg={result.get('msg', '未知')}"
    except Exception as e:
        return False, f"验证异常: {str(e)}"


def update_token(raw_token: str) -> bool:
    """更新 Token 到 crm_token.json（bot.py启动时自动从文件加载，无需改源码）"""
    
    token = parse_token(raw_token)
    print(f"解析后的Token: {token[:30]}...")
    
    # 验证Token类型
    if not is_cst_token(token):
        print("❌ Token类型无效（TCT），必须是CST类型！不更新。")
        return False
    
    # 验证UID
    uid = get_token_uid(token)
    if uid != "3301":
        print(f"❌ Token UID={uid}，必须是3301！不更新。")
        return False
    
    try:
        # 保存到 crm_token.json
        token_data = {
            "token": token,
            "updated_at": datetime.now().isoformat(),
            "updated_by": "auto_refresh"
        }
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(token_data, f, ensure_ascii=False, indent=2)
        print("✅ crm_token.json 已更新")
        
        return True
    except Exception as e:
        print(f"❌ 更新失败: {e}")
        return False


def restart_bot():
    """重启机器人 - 杀掉所有旧进程，确保只有一个新进程"""
    try:
        # 查找并关闭所有bot.py进程
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        killed_pids = []
        for line in result.stdout.split('\n'):
            if 'bot.py' in line and 'grep' not in line and 'update_token' not in line:
                pid = line.split()[1]
                subprocess.run(['kill', '-9', pid])
                killed_pids.append(pid)
                print(f"✅ 已关闭旧进程 {pid}")
        
        if killed_pids:
            time.sleep(3)  # 等待进程完全退出
            
            # 确认所有旧进程已退出
            result2 = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            for line in result2.stdout.split('\n'):
                if 'bot.py' in line and 'grep' not in line and 'update_token' not in line:
                    pid = line.split()[1]
                    print(f"⚠️ 进程 {pid} 还在，强制再杀")
                    subprocess.run(['kill', '-9', pid])
                    time.sleep(1)
        
        # 启动新进程（用shell=True让&生效）
        bot_dir = os.path.dirname(BOT_FILE)
        subprocess.Popen(
            f'cd {bot_dir} && nohup python bot.py > /dev/null 2>&1 &',
            shell=True
        )
        time.sleep(2)
        
        # 验证新进程已启动
        result3 = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        bot_count = 0
        for line in result3.stdout.split('\n'):
            if 'bot.py' in line and 'grep' not in line and 'update_token' not in line:
                bot_count += 1
        
        if bot_count == 1:
            print("✅ 机器人已重启（1个进程）")
            return True
        elif bot_count > 1:
            print(f"⚠️ 发现 {bot_count} 个bot进程，可能有残留")
            return True
        else:
            print("❌ 机器人未启动成功")
            return False
            
    except Exception as e:
        print(f"❌ 重启失败: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) == 2:
        arg = sys.argv[1]
        
        if arg == "--check":
            # 检查模式
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
            token = data.get('token', '')
            if not is_cst_token(token):
                print(f"[Token检查] ❌ Token类型无效（TCT）")
                sys.exit(1)
            is_valid, msg = verify_token(token)
            print(f"[Token检查] {'✅' if is_valid else '❌'} {msg}")
            sys.exit(0 if is_valid else 1)
        
        elif arg == "--verify":
            # 仅验证模式（不更新）
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
            token = data.get('token', '')
            if token.startswith('Bearer '):
                token = token[7:]
            is_valid, msg = verify_token(token)
            print(f"[Token验证] {'✅' if is_valid else '❌'} {msg}")
            sys.exit(0 if is_valid else 1)
        
        else:
            # 更新模式
            if update_token(arg):
                restart_bot()
                # 验证新Token
                time.sleep(3)
                token = parse_token(arg)
                is_valid, msg = verify_token(token)
                if is_valid:
                    print(f"✅ CRM Token 更新成功 - {msg}")
                else:
                    print(f"⚠️ CRM Token 已更新但验证失败 - {msg}")
            else:
                print("❌ Token更新失败，未重启机器人")
                sys.exit(1)
    else:
        print("""
╔══════════════════════════════════════════════╗
║         CRM Token 更新脚本                    ║
╠══════════════════════════════════════════════╣
║ 用法:                                        ║
║   python update_token.py <新Token>           ║
║   python update_token.py --check             ║
║   python update_token.py --verify            ║
║                                              ║
║ 注意: Token必须是CST类型，UID=3301           ║
║ ⚠️ 必须从TOKEN_KEY提取，不要用CRM_TOKEN_KEY  ║
╚══════════════════════════════════════════════╝
        """)
