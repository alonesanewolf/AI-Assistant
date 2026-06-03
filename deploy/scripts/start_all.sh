#!/bin/bash
# ============================================
# AI_Assistant 云服务器一键启动脚本
# 启动所有服务：Nginx + AI助手 + NetSec + MySQL + (可选) Tomcat
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="${INSTALL_DIR:-/opt/ai_assistant}"

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  AI_Assistant 云服务器启动${NC}"
echo -e "${GREEN}============================================${NC}"

# 启动 MySQL
echo -n "启动 MySQL ... "
if systemctl list-unit-files | grep -q mysql; then
    # Ubuntu 用 mysql，CentOS 也兼容（alias）
    systemctl start mysql 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
elif systemctl list-unit-files | grep -q mysqld; then
    # CentOS mysqld 兜底
    systemctl start mysqld 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
else
    echo -e "${YELLOW}⚠ MySQL 服务未安装${NC}"
fi

# 启动 AI 助手
echo -n "启动 AI 智能助手 ... "
systemctl start ai_assistant 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"

# 启动网络安全助手
if systemctl list-unit-files | grep -q netsec_assistant; then
    echo -n "启动网络安全助手 ... "
    systemctl start netsec_assistant 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
fi

# 启动 Nginx
echo -n "启动 Nginx ... "
systemctl start nginx 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"

# 可选：启动 Tomcat
if systemctl list-unit-files | grep -q tomcat; then
    echo -n "启动 Tomcat ... "
    systemctl start tomcat 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  所有服务已启动${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  ${BLUE}访问地址:${NC}"
echo -e "    统一门户:      http://\$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP')/"
echo -e "    AI 智能助手:   http://\$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP')/ai/"
echo -e "    网络安全助手:  http://\$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP')/netsec/"
echo ""
