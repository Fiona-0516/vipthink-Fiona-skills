#!/bin/bash
# 企业微信客服服务启动脚本
# 用于手动启动或调试服务

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 配置
SERVICE_NAME="wecom_kf_service.py"
LOG_FILE="wecom_kf_service.log"
PID_FILE="wecom_kf_service.pid"

# LLM配置（留空则使用环境变量）
export LLM_API_URL="${LLM_API_URL:-}"
export LLM_API_KEY="${LLM_API_KEY:-}"
export LLM_MODEL="${LLM_MODEL:-gpt-3.5-turbo}"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_running() {
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        else
            rm -f "$PID_FILE"
        fi
    fi
    return 1
}

start_service() {
    if check_running; then
        pid=$(cat "$PID_FILE")
        log_warn "服务已在运行 (PID: $pid)"
        return 1
    fi
    
    log_info "启动企业微信客服服务..."
    log_info "日志文件: $LOG_FILE"
    log_info "LLM API: ${LLM_API_URL:-未配置}"
    
    # 后台运行
    nohup python3 "$SERVICE_NAME" > "$LOG_FILE" 2>&1 &
    pid=$!
    echo $pid > "$PID_FILE"
    
    sleep 2
    
    if ps -p $pid > /dev/null 2>&1; then
        log_info "服务启动成功 (PID: $pid)"
        log_info "健康检查: curl http://localhost:8092/health"
        return 0
    else
        log_error "服务启动失败，请检查日志: $LOG_FILE"
        return 1
    fi
}

stop_service() {
    if ! check_running; then
        log_warn "服务未运行"
        return 1
    fi
    
    pid=$(cat "$PID_FILE")
    log_info "停止服务 (PID: $pid)..."
    
    kill -15 $pid 2>/dev/null
    
    # 等待进程结束
    for i in {1..10}; do
        if ! ps -p $pid > /dev/null 2>&1; then
            rm -f "$PID_FILE"
            log_info "服务已停止"
            return 0
        fi
        sleep 1
    done
    
    # 强制杀死
    log_warn "服务未响应，强制终止..."
    kill -9 $pid 2>/dev/null
    rm -f "$PID_FILE"
    log_info "服务已强制停止"
    return 0
}

status_service() {
    if check_running; then
        pid=$(cat "$PID_FILE")
        log_info "服务运行中 (PID: $pid)"
        
        # 显示最新日志
        if [ -f "$LOG_FILE" ]; then
            echo ""
            echo "=== 最近日志 ==="
            tail -10 "$LOG_FILE"
        fi
        return 0
    else
        log_warn "服务未运行"
        return 1
    fi
}

restart_service() {
    log_info "重启服务..."
    stop_service
    sleep 2
    start_service
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -50 "$LOG_FILE"
    else
        log_warn "日志文件不存在: $LOG_FILE"
    fi
}

show_help() {
    echo "企业微信客服服务管理脚本"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  start     启动服务"
    echo "  stop      停止服务"
    echo "  restart   重启服务"
    echo "  status    查看服务状态"
    echo "  logs      查看日志"
    echo "  help      显示帮助"
    echo ""
    echo "环境变量:"
    echo "  LLM_API_URL   LLM API地址"
    echo "  LLM_API_KEY   LLM API密钥"
    echo "  LLM_MODEL     LLM模型名称 (默认: gpt-3.5-turbo)"
}

# 主程序
case "${1:-help}" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        status_service
        ;;
    logs)
        show_logs
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "未知命令: $1"
        show_help
        exit 1
        ;;
esac

exit 0
