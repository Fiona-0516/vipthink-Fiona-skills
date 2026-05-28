#!/bin/bash
# CRM服务健康监控 - 纯bash，不消耗LLM积分
# 用crontab每5分钟执行一次

cd /app/data/所有对话/主对话/dingtalk_stream_bot

# 1. 检查CRM API服务(8090)
if ! pgrep -f "crm_api_service:app" > /dev/null; then
    echo "[$(date)] CRM API服务挂了，重启中..."
    nohup python3 -m uvicorn crm_api_service:app --host 0.0.0.0 --port 8090 > /tmp/crm_api.log 2>&1 &
    echo "[$(date)] CRM API服务已重启 PID=$!"
fi

# 2. 检查钉钉机器人(bot.py)
if ! pgrep -f "python bot.py" > /dev/null; then
    echo "[$(date)] 钉钉机器人挂了，重启中..."
    nohup python bot.py > /tmp/bot.log 2>&1 &
    echo "[$(date)] 钉钉机器人已重启 PID=$!"
fi

# 3. 检查企微回调服务(8091)
if ! pgrep -f "wecom_callback_service:app" > /dev/null; then
    echo "[$(date)] 企微回调服务挂了，重启中..."
    nohup python3 -m uvicorn wecom_callback_service:app --host 0.0.0.0 --port 8091 > /tmp/wecom_service.log 2>&1 &
    echo "[$(date)] 企微回调服务已重启 PID=$!"
fi

# 4. 检查Token是否即将过期（剩余<4小时）
TOKEN_FILE="crm_token.json"
if [ -f "$TOKEN_FILE" ]; then
    python3 -c "
import json, base64, time
try:
    d = json.load(open('$TOKEN_FILE'))
    p = d['token'].split('.')[1] + '=' * (4 - len(d['token'].split('.')[1]) % 4)
    exp = json.loads(base64.urlsafe_b64decode(p))[0]['exp']
    remaining = (exp - int(time.time())) / 3600
    if remaining < 4:
        print(f'WARNING: Token仅剩{remaining:.1f}小时！')
        exit(1)
except Exception as e:
    print(f'ERROR: Token检查失败: {e}')
    exit(1)
" >> /tmp/health_monitor.log 2>&1
    if [ $? -ne 0 ]; then
        echo "[$(date)] ⚠️ Token即将过期，需要刷新！"
    fi
fi

# 5. Cloudflare tunnel检查
if ! pgrep -f "cloudflared" > /dev/null; then
    echo "[$(date)] Cloudflare tunnel挂了，尝试重启..."
    nohup cloudflared tunnel --url http://localhost:8090 > /tmp/cloudflared.log 2>&1 &
fi
