#!/bin/bash
# ============================================
# AI_Assistant 云服务器一键部署脚本
# 适用系统: Ubuntu 20.04+ / CentOS 7.6+ / Rocky Linux / AlmaLinux
# ============================================
# 功能:
#   1. 安装 Nginx + Python3 + JDK8 (可选)
#   2. 配置 Nginx 反向代理
#   3. 部署 AI_Assistant 应用
#   4. 创建 systemd 服务实现开机自启
#   5. 防火墙配置
# ============================================

set -e

# ==================== 检测系统类型 ====================
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="$ID"
else
    OS_ID="unknown"
fi

IS_UBUNTU=false
IS_CENTOS=false
if [ "$OS_ID" = "ubuntu" ] || [ "$OS_ID" = "debian" ]; then
    IS_UBUNTU=true
elif [ "$OS_ID" = "centos" ] || [ "$OS_ID" = "rocky" ] || [ "$OS_ID" = "almalinux" ] || [ "$OS_ID" = "rhel" ]; then
    IS_CENTOS=true
fi

# ==================== 包管理器封装 ====================
pkg_update() {
    if $IS_UBUNTU; then
        apt-get update -qq > /dev/null 2>&1 || true
    else
        yum update -y > /dev/null 2>&1 || true
    fi
}

pkg_install() {
    if $IS_UBUNTU; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" > /dev/null 2>&1
    else
        yum install -y "$@" > /dev/null 2>&1
    fi
}

# ==================== 颜色 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ==================== 配置变量 ====================
# 安装目录（可修改）
INSTALL_DIR="/opt/ai_assistant"
# 服务器外网 IP（自动检测，也可手动填写）
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")
# 是否安装 Java/Tomcat（默认否，按需开启）
INSTALL_JAVA=${INSTALL_JAVA:-false}
# 是否安装 MySQL + 网络安全助手（默认是）
INSTALL_NETSEC=${INSTALL_NETSEC:-true}
# DeepSeek API Key（请在 .env 文件中填写，或运行时设置环境变量）
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  AI_Assistant 云服务器一键部署${NC}"
echo -e "${GREEN}============================================${NC}"
echo -e "  服务器 IP: ${CYAN}${SERVER_IP}${NC}"
echo -e "  安装目录:  ${CYAN}${INSTALL_DIR}${NC}"
echo -e "  安装 Java: ${CYAN}${INSTALL_JAVA}${NC}"
echo ""

# ==================== 1. 系统基础配置 ====================
echo -e "${YELLOW}[1/6] 系统基础配置...${NC}"
echo "  检测到系统: ${CYAN}${OS_ID} (${VERSION_ID:-})${NC}"

# 更新系统
if $IS_UBUNTU; then
    echo "  更新 apt 包..."
else
    echo "  更新 yum 包..."
fi
pkg_update

# 安装基础依赖
echo "  安装基础工具..."
if $IS_UBUNTU; then
    pkg_install git curl wget vim net-tools lsof ufw
else
    pkg_install epel-release
    pkg_install git curl wget vim net-tools lsof firewalld
fi

# 关闭 SELinux（仅 CentOS/RHEL）
if $IS_CENTOS; then
    if [ "$(getenforce 2>/dev/null)" != "Disabled" ]; then
        echo "  关闭 SELinux..."
        setenforce 0 2>/dev/null || true
        sed -i 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config
    fi
fi

echo -e "  ${GREEN}✓${NC} 系统基础配置完成"

# ==================== 2. 安装 Python3 ====================
echo -e "${YELLOW}[2/6] 安装 Python3 环境...${NC}"

if command -v python3 &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Python3 已安装: $(python3 --version)"
else
    echo "  安装 Python3..."
    if $IS_UBUNTU; then
        pkg_install python3 python3-pip python3-venv python3-dev
    else
        pkg_install python3 python3-pip python3-devel
    fi
    echo -e "  ${GREEN}✓${NC} Python3 安装完成: $(python3 --version)"
fi

# 升级 pip
python3 -m pip install --upgrade pip > /dev/null 2>&1 || true

# ==================== 3. 安装 Nginx ====================
echo -e "${YELLOW}[3/6] 安装 Nginx...${NC}"

if command -v nginx &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Nginx 已安装: $(nginx -v 2>&1)"
else
    if $IS_UBUNTU; then
        pkg_install nginx
    else
        # 添加 Nginx 官方源
        cat > /etc/yum.repos.d/nginx.repo << 'NGINX_REPO'
[nginx-stable]
name=nginx stable repo
baseurl=http://nginx.org/packages/centos/$releasever/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
NGINX_REPO

        pkg_install nginx
    fi
    systemctl enable nginx
    echo -e "  ${GREEN}✓${NC} Nginx 安装完成: $(nginx -v 2>&1)"
fi

# ==================== 4. 部署 AI_Assistant ====================
echo -e "${YELLOW}[4/6] 部署 AI_Assistant 应用...${NC}"

# 创建目录结构
mkdir -p ${INSTALL_DIR}/logs
mkdir -p /var/log/ai_assistant

# 如果当前目录有项目文件则复制，否则从 git 克隆
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

if [ -f "${PROJECT_ROOT}/local_assistant.py" ]; then
    echo "  从本地复制项目文件..."
    # 复制核心 Python 文件
    for f in assistant.py local_assistant.py brain.py agent_client.py \
             actions.py model_router.py memory.py scheduler.py config.py \
             search.py qq_bot.py wechat_assistant.py \
             requirements.txt; do
        if [ -f "${PROJECT_ROOT}/$f" ]; then
            cp "${PROJECT_ROOT}/$f" "${INSTALL_DIR}/"
        fi
    done
    # 复制 .env 示例
    if [ -f "${PROJECT_ROOT}/.env.example" ]; then
        cp "${PROJECT_ROOT}/.env.example" "${INSTALL_DIR}/.env.example"
    fi
    echo -e "  ${GREEN}✓${NC} 项目文件已复制"
else
    echo "  从 GitHub 克隆项目..."
    if [ -d "${INSTALL_DIR}/.git" ]; then
        cd ${INSTALL_DIR} && git pull origin main
    else
        git clone https://github.com/alonesanewolf/AI-Assistant.git ${INSTALL_DIR}
    fi
    echo -e "  ${GREEN}✓${NC} 项目已克隆"
fi

# 安装 Python 依赖
echo "  安装 Python 依赖..."
cd ${INSTALL_DIR}
python3 -m pip install -r requirements.txt > /dev/null 2>&1

# 创建 .env 配置（如果不存在）
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    cat > ${INSTALL_DIR}/.env << ENVEOF
# AI_Assistant 环境配置
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
ROUTER_MODE=cloud_only
ENABLE_BRAIN_AGENT=false
BRAIN_URL=http://localhost:5000
HOST=0.0.0.0
PORT=8080
APP_PREFIX=/ai
AGENT_NAME=CloudServer

# MySQL 配置（网络安全助手用）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DB=netsec_platform

# NetSec 配置
NETSEC_PORT=5100
NETSEC_DEBUG=false
NETSEC_APP_ROOT=/netsec
NETSEC_HOST=0.0.0.0
DEFAULT_ADMIN_PASSWORD=your_admin_password
ENVEOF
    echo -e "  ${YELLOW}⚠${NC} 请编辑 ${INSTALL_DIR}/.env 填写 DEEPSEEK_API_KEY"
else
    echo -e "  ${GREEN}✓${NC} .env 文件已存在"
fi

# ==================== 5. 配置 Nginx ====================
echo -e "${YELLOW}[5/6] 配置 Nginx 反向代理...${NC}"

# 备份原有默认配置
if [ -f /etc/nginx/conf.d/default.conf ]; then
    mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak
    echo "  已备份原有 default.conf"
fi

# 部署 AI_Assistant Nginx 配置
NGINX_CONF_SRC="${SCRIPT_DIR}/nginx/conf/ai_assistant.conf"
if [ -f "${NGINX_CONF_SRC}" ]; then
    cp "${NGINX_CONF_SRC}" /etc/nginx/conf.d/ai_assistant.conf
else
    # 如果脚本单独运行，从 deploy 目录找
    if [ -f "${PROJECT_ROOT}/deploy/nginx/conf/ai_assistant.conf" ]; then
        cp "${PROJECT_ROOT}/deploy/nginx/conf/ai_assistant.conf" /etc/nginx/conf.d/ai_assistant.conf
    else
        echo -e "  ${YELLOW}⚠${NC} 未找到 ai_assistant.conf，使用内置配置"
        # 写入一个基础配置
        cat > /etc/nginx/conf.d/ai_assistant.conf << 'NGXCONF'
upstream ai_web {
    server 127.0.0.1:8080 weight=1 max_fails=3 fail_timeout=30s;
    keepalive 32;
}
server {
    listen 80;
    server_name _;
    charset utf-8;
    client_max_body_size 50m;
    access_log /var/log/nginx/ai_access.log main;
    error_log  /var/log/nginx/ai_error.log  warn;

    location /socket.io/ {
        proxy_pass http://ai_web;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
    location / {
        proxy_pass http://ai_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
    }
    location /health {
        access_log off;
        return 200 '{"status":"ok"}';
        add_header Content-Type application/json;
    }
}
server {
    listen 8088;
    server_name _;
    location /nginx_status {
        stub_status on;
        access_log off;
        allow 127.0.0.1;
        deny all;
    }
}
NGXCONF
    fi
fi

# 测试 Nginx 配置
echo "  测试 Nginx 配置..."
if nginx -t 2>&1; then
    systemctl restart nginx
    echo -e "  ${GREEN}✓${NC} Nginx 配置生效"
else
    echo -e "  ${RED}✗${NC} Nginx 配置有误，请检查"
fi

# ==================== 6. 防火墙配置 ====================
echo -e "${YELLOW}[6/6] 配置防火墙...${NC}"

if $IS_UBUNTU; then
    # Ubuntu 使用 ufw
    ufw --force enable 2>/dev/null || true
    ufw allow 80/tcp > /dev/null 2>&1 || true
    ufw allow 8080/tcp > /dev/null 2>&1 || true
    ufw allow 5000/tcp > /dev/null 2>&1 || true
    ufw allow 8088/tcp > /dev/null 2>&1 || true
else
    systemctl start firewalld 2>/dev/null || true
    systemctl enable firewalld 2>/dev/null || true
    firewall-cmd --zone=public --add-port=80/tcp --permanent 2>/dev/null || true
    firewall-cmd --zone=public --add-port=8080/tcp --permanent 2>/dev/null || true
    firewall-cmd --zone=public --add-port=5000/tcp --permanent 2>/dev/null || true
    firewall-cmd --zone=public --add-port=8088/tcp --permanent 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
fi

echo -e "  ${GREEN}✓${NC} 防火墙已配置"

# ==================== 可选: 安装 MySQL + 网络安全助手 ====================
if [ "${INSTALL_NETSEC}" = "true" ]; then
    echo -e "${YELLOW}[可选] 安装 MySQL 和网络安全助手...${NC}"

    # 安装 MySQL 8
    if ! command -v mysql &>/dev/null; then
        echo "  安装 MySQL..."
        if $IS_UBUNTU; then
            # Ubuntu: 预设 root 密码避免交互提示
            export DEBIAN_FRONTEND=noninteractive
            pkg_install mysql-server
            # 启动 MySQL 并设置密码
            systemctl start mysql
            systemctl enable mysql
            # 设置 root 密码（Ubuntu MySQL 默认用 auth_socket，改为密码认证）
            mysql -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${MYSQL_PASSWORD:-your_mysql_password}'; FLUSH PRIVILEGES;" 2>/dev/null || true
        else
            yum install -y https://dev.mysql.com/get/mysql80-community-release-el7-3.noarch.rpm > /dev/null 2>&1 || true
            pkg_install mysql-community-server
            systemctl enable mysqld
            systemctl start mysqld
        fi

        echo -e "  ${GREEN}✓${NC} MySQL 安装完成"
    else
        echo -e "  ${GREEN}✓${NC} MySQL 已安装"
        if $IS_UBUNTU; then
            systemctl start mysql 2>/dev/null || true
        else
            systemctl start mysqld 2>/dev/null || true
        fi
    fi

    # 部署网络安全助手
    NETSEC_DIR="${INSTALL_DIR}/netsec"
    if [ -d "${PROJECT_ROOT}/deploy/netsec" ]; then
        mkdir -p ${NETSEC_DIR}
        cp -r "${PROJECT_ROOT}/deploy/netsec/"* "${NETSEC_DIR}/"
        echo -e "  ${GREEN}✓${NC} 网络安全助手已部署到 ${NETSEC_DIR}"

        # 安装 NetSec Python 依赖
        cd ${NETSEC_DIR}
        python3 -m pip install -r requirements.txt > /dev/null 2>&1
        echo -e "  ${GREEN}✓${NC} NetSec Python 依赖已安装"
    else
        echo -e "  ${YELLOW}⚠${NC} 未找到 deploy/netsec 目录，跳过"
    fi

    # 配置防火墙
    if $IS_UBUNTU; then
        ufw allow 5100/tcp > /dev/null 2>&1 || true
        ufw allow 3306/tcp > /dev/null 2>&1 || true
    else
        firewall-cmd --zone=public --add-port=5100/tcp --permanent 2>/dev/null || true
        firewall-cmd --zone=public --add-port=3306/tcp --permanent 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
    fi
fi

# ==================== 可选: 安装 Java + Tomcat ====================
if [ "${INSTALL_JAVA}" = "true" ]; then
    echo -e "${YELLOW}[可选] 安装 Java 和 Tomcat...${NC}"

    # 安装 JDK 8
    if ! command -v java &>/dev/null; then
        yum install -y java-1.8.0-openjdk java-1.8.0-openjdk-devel > /dev/null 2>&1
        echo -e "  ${GREEN}✓${NC} JDK 8 安装完成"
    else
        echo -e "  ${GREEN}✓${NC} Java 已安装: $(java -version 2>&1 | head -1)"
    fi

    # 部署 Tomcat
    TOMCAT_DIR="/opt/tomcat"
    if [ -d "${PROJECT_ROOT}/server/tomcat/apache-tomcat-8.5.2" ]; then
        cp -r "${PROJECT_ROOT}/server/tomcat/apache-tomcat-8.5.2" "${TOMCAT_DIR}"
        chmod +x ${TOMCAT_DIR}/bin/*.sh
        # 修改 Tomcat 端口为 8089（避免与 AI_Assistant 8080 冲突）
        sed -i 's/port="8080"/port="8089"/g' ${TOMCAT_DIR}/conf/server.xml
        echo -e "  ${GREEN}✓${NC} Tomcat 已部署到 ${TOMCAT_DIR} (端口: 8089)"

        # 配置防火墙
        if $IS_UBUNTU; then
            ufw allow 8089/tcp > /dev/null 2>&1 || true
        else
            firewall-cmd --zone=public --add-port=8089/tcp --permanent 2>/dev/null || true
            firewall-cmd --reload 2>/dev/null || true
        fi
    fi
fi

# ==================== 创建 systemd 服务 ====================
echo ""
echo -e "${YELLOW}创建 systemd 服务...${NC}"

# AI_Assistant Web UI 服务
cat > /etc/systemd/system/ai_assistant.service << SERVICEEOF
[Unit]
Description=AI Assistant Web UI Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/local_assistant.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/ai_assistant/web.log
StandardError=append:/var/log/ai_assistant/web_error.log

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Brain 服务（可选，如果作为云端大脑运行）
cat > /etc/systemd/system/ai_brain.service << SERVICEEOF
[Unit]
Description=AI Assistant Cloud Brain Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/brain.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/ai_assistant/brain.log
StandardError=append:/var/log/ai_assistant/brain_error.log

[Install]
WantedBy=multi-user.target
SERVICEEOF

# 网络安全助手服务
if [ "${INSTALL_NETSEC}" = "true" ]; then
    # 确定 MySQL 服务名（Ubuntu=mysql, CentOS=mysqld）
    MYSQL_SVC="mysql"
    if $IS_CENTOS; then
        MYSQL_SVC="mysqld"
    fi

    cat > /etc/systemd/system/netsec_assistant.service << SERVICEEOF
[Unit]
Description=NetSec Assistant - Web Security Platform
After=network.target ${MYSQL_SVC}.service
Requires=${MYSQL_SVC}.service

[Service]
Type=simple
User=root
WorkingDirectory=${NETSEC_DIR}
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="FLASK_SECRET_KEY=$(openssl rand -hex 24 2>/dev/null || echo 'change-me-in-production')"
Environment="MYSQL_HOST=localhost"
Environment="MYSQL_PORT=3306"
Environment="MYSQL_USER=root"
Environment="MYSQL_PASSWORD=${MYSQL_PASSWORD:-your_mysql_password}"
Environment="MYSQL_DB=netsec_platform"
Environment="NETSEC_PORT=5100"
Environment="NETSEC_DEBUG=false"
Environment="NETSEC_APP_ROOT=/netsec"
ExecStart=/usr/bin/python3 ${NETSEC_DIR}/run.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/ai_assistant/netsec.log
StandardError=append:/var/log/ai_assistant/netsec_error.log

[Install]
WantedBy=multi-user.target
SERVICEEOF
    systemctl enable netsec_assistant.service 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} NetSec systemd 服务已创建"
fi

# Tomcat 服务（可选）
if [ "${INSTALL_JAVA}" = "true" ]; then
    cat > /etc/systemd/system/tomcat.service << SERVICEEOF
[Unit]
Description=Apache Tomcat 8.5 Service
After=network.target

[Service]
Type=forking
User=root
Environment="JAVA_HOME=/usr/lib/jvm/jre-1.8.0"
Environment="CATALINA_HOME=${TOMCAT_DIR}"
ExecStart=${TOMCAT_DIR}/bin/startup.sh
ExecStop=${TOMCAT_DIR}/bin/shutdown.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICEEOF
fi

systemctl daemon-reload
systemctl enable ai_assistant.service
echo -e "  ${GREEN}✓${NC} systemd 服务已创建"

# ==================== 完成 ====================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  部署完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  ${BLUE}服务地址:${NC}"
echo -e "    统一门户:      http://${SERVER_IP}/"
echo -e "    AI 智能助手:   http://${SERVER_IP}/ai/"
if [ "${INSTALL_NETSEC}" = "true" ]; then
    echo -e "    网络安全助手:  http://${SERVER_IP}/netsec/"
fi
echo -e "    API 接口:      http://${SERVER_IP}/api/status"
echo -e "    健康检查:      http://${SERVER_IP}/health"
echo -e "    Nginx 状态:    http://${SERVER_IP}:8088/nginx_status"
if [ "${INSTALL_JAVA}" = "true" ]; then
    echo -e "    Tomcat:        http://${SERVER_IP}:8089/"
fi
echo ""
echo -e "  ${BLUE}管理命令:${NC}"
echo -e "    启动全部:      cd ${INSTALL_DIR}/deploy/scripts && ./manage.sh start"
echo -e "    停止全部:      cd ${INSTALL_DIR}/deploy/scripts && ./manage.sh stop"
echo -e "    查看状态:      cd ${INSTALL_DIR}/deploy/scripts && ./manage.sh status"
echo -e "    查看日志:      tail -f /var/log/ai_assistant/web.log"
echo -e "    重载 Nginx:    nginx -s reload"
echo ""
echo -e "  ${BLUE}下一步:${NC}"
echo -e "    1. 编辑 ${INSTALL_DIR}/.env 填写 DEEPSEEK_API_KEY"
echo -e "    2. 启动所有服务: cd ${INSTALL_DIR}/deploy/scripts && ./manage.sh start"
echo -e "    3. 访问统一门户: http://${SERVER_IP}/"
if [ "${INSTALL_NETSEC}" = "true" ]; then
    echo -e "    4. NetSec 初始化数据库后访问: http://${SERVER_IP}/netsec/"
    echo -e "       默认管理员: admin / Admin@123456"
fi
echo ""
echo -e "  ${YELLOW}⚠ 安全提醒:${NC}"
echo -e "    - 生产环境请开启 SELinux 和防火墙"
echo -e "    - 建议配置 HTTPS (Let's Encrypt)"
echo -e "    - 定期更新系统和依赖包"
echo ""
