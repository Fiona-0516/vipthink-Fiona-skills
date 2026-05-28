#!/bin/bash
# 教务小助手机器人 - 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_SCRIPT="$SCRIPT_DIR/bot.py"
PID_FILE="$SCRIPT_DIR/bot.pid"
LOG_FILE="$SCRIPT_DIR/bot.log"

start() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "❌ 机器人已在运行中 (PID: $PID)"
            return 1
        fi
    fi
    echo "🚀 启动教务小助手机器人..."
    nohup python3 "$BOT_SCRIPT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
    if ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
        echo "✅ 启动成功 (PID: $(cat $PID_FILE))"
        echo "📋 日志文件: $LOG_FILE"
    else
        echo "❌ 启动失败，请查看日志: $LOG_FILE"
    fi
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "🛑 停止机器人 (PID: $PID)..."
            kill $PID
            rm -f "$PID_FILE"
            echo "✅ 已停止"
        else
            echo "⚠️ 进程不存在，清理 PID 文件"
            rm -f "$PID_FILE"
        fi
    else
        echo "❌ 机器人未运行"
    fi
}

status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "✅ 机器人运行中 (PID: $PID)"
        else
            echo "❌ 进程不存在 (PID 文件存在但进程已退出)"
        fi
    else
        echo "❌ 机器人未运行"
    fi
}

logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "❌ 日志文件不存在"
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 1
        start
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "  start   - 启动机器人"
        echo "  stop    - 停止机器人"
        echo "  restart - 重启机器人"
        echo "  status  - 查看运行状态"
        echo "  logs    - 查看实时日志"
        exit 1
        ;;
esac
