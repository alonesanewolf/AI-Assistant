#!/bin/bash
# ============================================
# AI_Assistant 部署后验证脚本
# 用法: ./validate.sh
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0
WARNINGS=()

pass()  { PASS=$((PASS+1)); echo -e "  ${GREEN}[✓]${NC} $1"; }
fail()  { FAIL=$((FAIL+1)); echo -e "  ${RED}[✗]${NC} $1"; WARNINGS+=("${RED}FAIL:${NC} $1"); }
warn()  { WARN=$((WARN+1)); echo -e "  ${YELLOW}[!]${NC} $1"; WARNINGS+=("${YELLOW}WARN:${NC} $1"); }

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  AI_Assistant 部署验证${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ==================== 1. 系统检查 ====================
echo -e "${BLUE}[1/8] 系统环境检查${NC}"

# Python3
if command -v python3 &>/dev/null; then
    py_ver=$(python3 --version 2>&1)
    pass "Python3: $py_ver"
else
    fail "Python3 未安装"
fi

# pip3
if command -v pip3 &>/dev/null; then
    pass "pip3: $(pip3 --version 2>&1 | head -1)"
else
    fail "pip3 未安装"
fi

# Nginx
if command -v nginx &>/dev/null; then
    pass "Nginx: $(nginx -v 2>&1)"
else
    fail "Nginx 未安装"
fi

# curl
if command -v curl &>/dev/null; then
    pass "curl: 已安装"
else
    warn "curl 未安装（建议安装用于健康检查）"
fi

echo ""

# ==================== 2. 项目文件检查 ====================
echo -e "${BLUE}[2/8] 项目文件完整性${NC}"

INSTALL_DIR="${INSTALL_DIR:-/opt/ai_assistant}"
REQUIRED_FILES=(
    "local_assistant.py"
    "assistant.py"
    "brain.py"
    "agent_client.py"
    "actions.py"
    "config.py"
    "requirements.txt"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "${INSTALL_DIR}/${f}" ]; then
        pass "${f}"
    else
        fail "${f} 缺失"
    fi
done

# 检查 .env
if [ -f "${INSTALL_DIR}/.env" ]; then
    pass ".env 配置文件存在"
    # 检查关键配置
    if grep -q "DEEPSEEK_API_KEY=" "${INSTALL_DIR}/.env" && ! grep -q "DEEPSEEK_API_KEY=$" "${INSTALL_DIR}/.env"; then
        pass "DEEPSEEK_API_KEY 已配置"
    else
        warn "DEEPSEEK_API_KEY 未配置或为空"
    fi
else
    warn ".env 文件不存在，使用默认配置"
fi

echo ""

# ==================== 3. Python 依赖检查 ====================
echo -e "${BLUE}[3/8] Python 依赖检查${NC}"

REQUIRED_PKGS=("flask" "flask-socketio" "python-socketio" "requests" "pymysql")
for pkg in "${REQUIRED_PKGS[@]}"; do
    if python3 -c "import ${pkg//-/_}" 2>/dev/null; then
        pass "$pkg"
    else
        warn "$pkg 未安装"
    fi
done

echo ""

# ==================== 4. 端口监听检查 ====================
echo -e "${BLUE}[4/8] 端口监听检查${NC}"

check_port() {
    local port=$1
    local name=$2
    if ss -tlnp 2>/dev/null | grep -q ":$port " || netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        pass "端口 $port ($name) - 监听中"
    else
        warn "端口 $port ($name) - 未监听"
    fi
}

check_port 80    "Nginx HTTP"
check_port 5100  "NetSec"
check_port 8080  "AI Assistant"
check_port 8088  "Nginx Status"

echo ""

# ==================== 5. HTTP 端点检查 ====================
echo -e "${BLUE}[5/8] HTTP 端点检查${NC}"

check_http_endpoint() {
    local url=$1
    local name=$2
    local expect=${3:-200}
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 "$url" 2>/dev/null || echo "000")
    if [ "$code" = "$expect" ]; then
        pass "$name ($url) -> HTTP $code"
    else
        warn "$name ($url) -> HTTP $code (期望 $expect)"
    fi
}

check_http_endpoint "http://127.0.0.1/health"        "健康检查"
check_http_endpoint "http://127.0.0.1/"               "统一门户"
check_http_endpoint "http://127.0.0.1/netsec/"        "NetSec 平台"
check_http_endpoint "http://127.0.0.1/netsec/login"   "NetSec 登录"

echo ""

# ==================== 6. Nginx 配置检查 ====================
echo -e "${BLUE}[6/8] Nginx 配置验证${NC}"

if nginx -t 2>&1 | grep -q "syntax is ok"; then
    pass "Nginx 配置语法正确"
else
    fail "Nginx 配置有误"
fi

if [ -f /etc/nginx/conf.d/ai_assistant.conf ]; then
    pass "ai_assistant.conf 已部署"
    
    # 检查关键配置项
    if grep -q "upstream ai_web" /etc/nginx/conf.d/ai_assistant.conf; then
        pass "upstream ai_web 已配置"
    fi
    if grep -q "upstream netsec_platform" /etc/nginx/conf.d/ai_assistant.conf; then
        pass "upstream netsec_platform 已配置"
    fi
    if grep -q "location /netsec/" /etc/nginx/conf.d/ai_assistant.conf; then
        pass "NetSec 反向代理已配置"
    fi
else
    fail "ai_assistant.conf 未找到"
fi

echo ""

# ==================== 7. systemd 服务检查 ====================
echo -e "${BLUE}[7/8] Systemd 服务检查${NC}"

check_service() {
    local svc=$1
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            pass "$svc - 运行中 (开机自启)"
        else
            pass "$svc - 运行中 (未设自启)"
        fi
    elif systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        warn "$svc - 已启用但未运行"
    else
        warn "$svc - 未安装或未配置"
    fi
}

check_service "nginx"
check_service "ai_assistant"
check_service "netsec_assistant"
check_service "ai_brain"

echo ""

# ==================== 8. 磁盘和内存 ====================
echo -e "${BLUE}[8/8] 系统资源${NC}"

# 磁盘
disk_usage=$(df -h / | awk 'NR==2{print $5}' | sed 's/%//')
if [ "$disk_usage" -lt 80 ]; then
    pass "磁盘使用率: ${disk_usage}% (正常)"
elif [ "$disk_usage" -lt 95 ]; then
    warn "磁盘使用率: ${disk_usage}% (偏高)"
else
    fail "磁盘使用率: ${disk_usage}% (严重不足)"
fi

# 内存
mem_info=$(free -m | awk 'NR==2{printf "%.0f", $3/$2*100}')
if [ "$mem_info" -lt 80 ]; then
    pass "内存使用率: ${mem_info}% (正常)"
else
    warn "内存使用率: ${mem_info}% (偏高)"
fi

# 日志目录大小
if [ -d /var/log/ai_assistant ]; then
    log_size=$(du -sh /var/log/ai_assistant 2>/dev/null | cut -f1)
    pass "日志目录大小: $log_size"
fi

echo ""

# ==================== 总结 ====================
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  验证结果${NC}"
echo -e "${CYAN}============================================${NC}"
echo -e "  通过: ${GREEN}${PASS}${NC}"
echo -e "  失败: ${RED}${FAIL}${NC}"
echo -e "  警告: ${YELLOW}${WARN}${NC}"
echo ""

if [ ${#WARNINGS[@]} -gt 0 ]; then
    echo -e "${YELLOW}详细信息:${NC}"
    for w in "${WARNINGS[@]}"; do
        echo "  $w"
    done
    echo ""
fi

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}部署存在问题，请修复后重新验证。${NC}"
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo -e "${YELLOW}部署基本正常，存在一些警告项建议优化。${NC}"
    exit 0
else
    echo -e "${GREEN}✓ 部署验证全部通过！${NC}"
    exit 0
fi
