#!/bin/bash
# ============================================
# AI_Assistant 服务管理脚本
# 用法: ./manage.sh {start|stop|restart|status|logs|test}
# ============================================

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SERVICES=("ai_assistant" "netsec_assistant" "ai_brain" "nginx" "mysql" "tomcat")
ACTIVE_SERVICES=("ai_assistant" "netsec_assistant" "mysql" "nginx")

show_banner() {
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  AI_Assistant 服务管理${NC}"
    echo -e "${GREEN}============================================${NC}"
}

show_help() {
    echo "用法: $0 {start|stop|restart|status|logs|test|quick-deploy}"
    echo ""
    echo "  start        启动所有服务"
    echo "  stop         停止所有服务"
    echo "  restart      重启所有服务"
    echo "  status       查看服务状态"
    echo "  logs         查看 Web 服务日志"
    echo "  test         运行健康检查"
    echo "  quick-deploy 快速部署（安装 Nginx + Python 依赖并启动）"
}

start_services() {
    echo -e "${YELLOW}启动服务...${NC}"
    for svc in "${ACTIVE_SERVICES[@]}"; do
        echo -n "  $svc ... "
        if systemctl start $svc 2>/dev/null; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${RED}✗${NC}"
        fi
    done
    echo -e "${GREEN}服务已启动${NC}"
}

stop_services() {
    echo -e "${YELLOW}停止服务...${NC}"
    for svc in "${ACTIVE_SERVICES[@]}"; do
        echo -n "  $svc ... "
        if systemctl stop $svc 2>/dev/null; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${RED}✗${NC}"
        fi
    done
    echo -e "${GREEN}服务已停止${NC}"
}

show_status() {
    echo -e "${YELLOW}服务状态:${NC}"
    echo ""
    for svc in "${ACTIVE_SERVICES[@]}"; do
        printf "  %-20s " "$svc"
        state=$(systemctl is-active $svc 2>/dev/null || echo "未安装")
        if [ "$state" = "active" ]; then
            echo -e "${GREEN}$state${NC}"
        else
            echo -e "${RED}$state${NC}"
        fi
    done
    echo ""

    # 检查端口
    echo -e "${YELLOW}端口监听:${NC}"
    for port in 80 3306 5000 5100 8080 8088 8089; do
        if ss -tlnp 2>/dev/null | grep -q ":$port "; then
            echo -e "  :$port  ${GREEN}监听中${NC}"
        else
            echo -e "  :$port  ${RED}未监听${NC}"
        fi
    done
}

show_logs() {
    LOG_FILE="/var/log/ai_assistant/web.log"
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "日志文件不存在: $LOG_FILE"
        echo "尝试查看 systemd 日志..."
        journalctl -u ai_assistant -f
    fi
}

run_test() {
    echo -e "${YELLOW}运行健康检查...${NC}"
    echo ""

    SERVER_IP="127.0.0.1"

    # 测试 Nginx
    echo -n "  统一门户 :80 ... "
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://${SERVER_IP}/ 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✓ HTTP $HTTP_CODE${NC}"
    else
        echo -e "${RED}✗ HTTP $HTTP_CODE${NC}"
    fi

    # 测试 AI 助手
    echo -n "  AI 助手 /ai/ ... "
    AI_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://${SERVER_IP}/ai/ 2>/dev/null || echo "000")
    if [ "$AI_CODE" = "200" ]; then
        echo -e "${GREEN}✓ HTTP $AI_CODE${NC}"
    else
        echo -e "${YELLOW}⚠ HTTP $AI_CODE${NC}"
    fi

    # 测试 NetSec
    echo -n "  NetSec /netsec/ ... "
    NETSEC_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://${SERVER_IP}/netsec/ 2>/dev/null || echo "000")
    if [ "$NETSEC_CODE" = "200" ]; then
        echo -e "${GREEN}✓ HTTP $NETSEC_CODE${NC}"
    else
        echo -e "${YELLOW}⚠ HTTP $NETSEC_CODE${NC}"
    fi

    # 测试健康检查
    echo -n "  健康检查 ... "
    HEALTH=$(curl -s http://${SERVER_IP}/health 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q "ok"; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    # 测试 API
    echo -n "  API 状态 ... "
    API=$(curl -s http://${SERVER_IP}/api/status 2>/dev/null || echo "")
    if [ -n "$API" ]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    # Nginx 状态
    echo -n "  Nginx 状态 ... "
    NGX_STATUS=$(curl -s http://127.0.0.1:8088/nginx_status 2>/dev/null || echo "")
    if echo "$NGX_STATUS" | grep -q "Active"; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${YELLOW}⚠ 未开启 stub_status${NC}"
    fi

    echo ""
    echo -e "${GREEN}健康检查完成${NC}"
}

quick_deploy() {
    echo -e "${YELLOW}快速部署模式...${NC}"
    
    # 检测系统
    if [ -f /etc/os-release ]; then
        . /etc/os-release
    fi
    
    # 检查 Python
    if ! command -v python3 &>/dev/null; then
        echo "安装 Python3..."
        if [ "$ID" = "ubuntu" ] || [ "$ID" = "debian" ]; then
            apt-get update -qq > /dev/null 2>&1
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip > /dev/null 2>&1
        else
            yum install -y python3 python3-pip > /dev/null 2>&1
        fi
    fi

    # 安装依赖
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    cd "$PROJECT_DIR"
    pip3 install -r requirements.txt > /dev/null 2>&1

    # 检查 .env
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}⚠ 未找到 .env 文件，创建默认配置...${NC}"
        cp .env.example .env 2>/dev/null || true
        echo "请编辑 .env 填写 DEEPSEEK_API_KEY"
    fi

    # 检查 Nginx
    if ! command -v nginx &>/dev/null; then
        echo "安装 Nginx..."
        if [ "$ID" = "ubuntu" ] || [ "$ID" = "debian" ]; then
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx > /dev/null 2>&1
        else
            yum install -y nginx > /dev/null 2>&1
        fi
    fi

    # 配置 Nginx
    if [ -f "deploy/nginx/conf/ai_assistant.conf" ]; then
        cp deploy/nginx/conf/ai_assistant.conf /etc/nginx/conf.d/
        nginx -t && nginx -s reload 2>/dev/null || systemctl restart nginx
    fi

    # 启动服务
    echo "启动 AI_Assistant..."
    nohup python3 local_assistant.py > /var/log/ai_assistant/web.log 2>&1 &
    
    echo ""
    echo -e "${GREEN}✓ 快速部署完成${NC}"
    echo "访问: http://$(curl -s ifconfig.me)/"
}

# ==================== 主逻辑 ====================
show_banner

case "${1:-status}" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        sleep 2
        start_services
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    test)
        run_test
        ;;
    quick-deploy)
        quick_deploy
        ;;
    *)
        show_help
        ;;
esac
