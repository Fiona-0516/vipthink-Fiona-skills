#!/bin/bash
# 企业微信回调服务启动脚本

SERVICE_NAME="wecom_callback_service"
PORT=8091
LOG_FILE="wecom_service.log"
PID_FILE="wecom_service.pid"

cd "$(dirname "$0")"

start() {
    echo "Starting WeCom Callback Service..."
    
    # 检查端口是否已被占用
    if lsof -i :$PORT > /dev/null 2>&1; then
        echo "Port $PORT is already in use. Stopping existing process..."
        pkill -f "wecom_callback_service" 2>/dev/null
        sleep 2
    fi
    
    # 启动服务
    python3 -m uvicorn wecom_callback_service:app --host 0.0.0.0 --port $PORT > $LOG_FILE 2>&1 &
    PID=$!
    echo $PID > $PID_FILE
    
    sleep 3
    
    # 检查是否启动成功
    if curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
        echo "Service started successfully (PID: $PID)"
        echo "Health check: http://localhost:$PORT/health"
        echo "API docs: http://localhost:$PORT/docs"
    else
        echo "Service may have failed to start. Check $LOG_FILE"
        tail -20 $LOG_FILE
    fi
}

stop() {
    echo "Stopping WeCom Callback Service..."
    
    if [ -f $PID_FILE ]; then
        PID=$(cat $PID_FILE)
        if kill -0 $PID 2>/dev/null; then
            kill $PID
            rm -f $PID_FILE
            echo "Service stopped (PID: $PID)"
        else
            echo "Process not running"
            rm -f $PID_FILE
        fi
    else
        pkill -f "wecom_callback_service" 2>/dev/null
        echo "Service stopped"
    fi
}

status() {
    echo "WeCom Callback Service Status:"
    
    if [ -f $PID_FILE ]; then
        PID=$(cat $PID_FILE)
        if kill -0 $PID 2>/dev/null; then
            echo "  Running (PID: $PID)"
        else
            echo "  Not running (stale PID file)"
        fi
    else
        echo "  Not running"
    fi
    
    echo ""
    echo "Port $PORT status:"
    lsof -i :$PORT 2>/dev/null || echo "  Port $PORT is free"
    
    echo ""
    echo "Recent logs:"
    tail -10 $LOG_FILE 2>/dev/null || echo "No logs found"
}

restart() {
    stop
    sleep 2
    start
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
