#!/bin/bash
# Goofish Tracker 管理脚本
# 用法: ./run.sh {start|stop|restart|status|logs}

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/tracker.pid"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/tracker.log"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_config() {
    if [ ! -f "$SCRIPT_DIR/config.yaml" ]; then
        log_error "配置文件不存在: config.yaml"
        if [ -f "$SCRIPT_DIR/config.example.yaml" ]; then
            log_info "请执行: cp config.example.yaml config.yaml"
        fi
        exit 1
    fi
}

check_deps() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装"
        exit 1
    fi

    if ! python3 -c "import yaml" &> /dev/null; then
        log_error "缺少依赖: pyyaml"
        log_info "请执行: pip install pyyaml"
        exit 1
    fi

    if ! python3 -c "from playwright.sync_api import sync_playwright" &> /dev/null; then
        log_error "缺少依赖: playwright"
        log_info "请执行: pip install playwright && playwright install chromium"
        exit 1
    fi
}

start() {
    check_config
    check_deps

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            log_warn "已在运行中 (PID: $PID)"
            return 1
        fi
        rm -f "$PID_FILE"
    fi

    mkdir -p "$LOG_DIR"

    log_info "启动 Goofish Tracker..."
    cd "$SCRIPT_DIR"
    nohup python3 tracker.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    sleep 1
    if [ -f "$PID_FILE" ] && ps -p "$(cat $PID_FILE)" > /dev/null 2>&1; then
        log_info "启动成功 (PID: $(cat $PID_FILE))"
        log_info "日志文件: $LOG_FILE"
    else
        log_error "启动失败，请查看日志"
        exit 1
    fi
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            log_info "停止进程 (PID: $PID)..."
            kill "$PID"
            sleep 2
            if ps -p "$PID" > /dev/null 2>&1; then
                log_warn "强制停止..."
                kill -9 "$PID"
            fi
            rm -f "$PID_FILE"
            log_info "已停止"
        else
            log_warn "进程不存在"
            rm -f "$PID_FILE"
        fi
    else
        log_warn "未运行"
    fi
}

status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            UPTIME=$(ps -o etime= -p "$PID" | tr -d ' ')
            log_info "运行中 (PID: $PID, 运行时间: $UPTIME)"
        else
            log_warn "PID 文件存在但进程不存在"
            rm -f "$PID_FILE"
        fi
    else
        log_info "未运行"
    fi
}

logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        log_error "日志文件不存在: $LOG_FILE"
        exit 1
    fi
}

case "${1:-}" in
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
        echo "Goofish Tracker 管理脚本"
        echo ""
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "命令:"
        echo "  start   - 启动（后台运行）"
        echo "  stop    - 停止"
        echo "  restart - 重启"
        echo "  status  - 查看运行状态"
        echo "  logs    - 实时查看日志"
        exit 1
        ;;
esac
