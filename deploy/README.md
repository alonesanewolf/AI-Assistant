# AI_Assistant 云服务器部署指南

## 统一平台架构

```
http://你的服务器IP/
  ├── /              统一门户首页（所有服务入口）
  ├── /ai/           AI 智能助手 (端口8080)
  ├── /netsec/       网络安全助手平台 (端口5100)
  ├── /brain/        云端大脑 API (端口5000)
  └── /health        健康检查
```

## 目录结构

```
deploy/
├── README.md                     # 本文档
├── .env.template                 # 环境变量模板
├── nginx.md                      # Nginx 安装配置详细教程
├── nginx/
│   ├── nginx.conf                # Nginx 主配置（参考）
│   ├── html/
│   │   └── index.html            # ★ 统一门户首页
│   └── conf/
│       ├── ai_assistant.conf     # ★ 统一 Nginx 配置（核心）
│       ├── proxy.conf            # 反向代理配置模板
│       ├── loadbalance.conf      # 负载均衡配置模板
│       └── full-example.conf     # 综合案例配置模板
├── netsec/                       # ★ 网络安全助手平台
│   ├── run.py                    # Flask 主程序
│   ├── NetSecAssistant.py        # 扫描核心类
│   ├── network_scan.py           # 网络扫描工具
│   ├── templates/                # 43 个 HTML 模板
│   ├── static/                   # 静态资源
│   └── sql/mysql8_init.sql       # 数据库初始化脚本
└── scripts/
    ├── deploy.sh                 # ★ 一键部署脚本
    ├── manage.sh                 # ★ 服务管理脚本
    ├── start_all.sh              # ★ 云服务器启动脚本
    ├── start_backends.sh         # 模拟后端启动（参考）
    └── test.sh                   # 自动化测试（参考）
```

## 架构图

```
                     用户浏览器
                          │
                          ▼
                  ┌───────────────┐
                  │  Nginx :80    │  ← 统一入口
                  └───────┬───────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                  ▼
 ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
 │ AI 助手      │  │ NetSec 平台  │  │ 云端 Brain   │
 │ :8080        │  │ :5100        │  │ :5000        │
 │ (Flask+      │  │ (Flask+      │  │ (Flask+      │
 │  SocketIO)   │  │  MySQL)      │  │  SocketIO)   │
 └──────────────┘  └──────┬───────┘  └──────────────┘
                          │
                          ▼
                   ┌──────────┐
                   │ MySQL 8  │
                   │ :3306    │
                   └──────────┘
```

## 快速开始

### 前提条件

- CentOS 7.6+ / Rocky Linux / AlmaLinux 云服务器
- 已开放 80 端口（安全组/防火墙）
- 有 root 权限
- 2GB+ 内存（MySQL 需要）

### 一键部署（推荐）

```bash
# 1. 上传项目到服务器
scp -r AI_Assistant/ root@你的服务器IP:/opt/

# 2. SSH 登录服务器
ssh root@你的服务器IP

# 3. 运行部署脚本（含 MySQL + NetSec）
cd /opt/AI_Assistant/deploy/scripts
chmod +x deploy.sh
./deploy.sh

# 4. 配置 API Key
vim /opt/ai_assistant/.env

# 5. 启动所有服务
./start_all.sh
```

部署完成后访问 `http://你的服务器IP/` 即可看到统一门户。

### 电脑端使用

```bash
# 一键启动（Windows）
双击 start_all.bat

# 配置开机自启
双击 setup_autostart.bat
```

## 服务管理

### 使用管理脚本

```bash
cd /opt/AI_Assistant/deploy/scripts

./manage.sh start      # 启动全部服务
./manage.sh stop       # 停止全部服务
./manage.sh restart    # 重启全部服务
./manage.sh status     # 查看服务状态
./manage.sh test       # 运行健康检查
```

### 使用 systemd

```bash
systemctl start ai_assistant       # AI 助手
systemctl start netsec_assistant   # 网络安全助手
systemctl start mysqld             # MySQL
systemctl start nginx              # Nginx

# 查看日志
journalctl -u ai_assistant -f
journalctl -u netsec_assistant -f
```

### 查看日志

```bash
tail -f /var/log/ai_assistant/web.log       # AI 助手日志
tail -f /var/log/ai_assistant/netsec.log    # NetSec 日志
tail -f /var/log/nginx/ai_assistant_access.log  # Nginx 访问日志
```

## 端口说明

| 端口 | 服务 | 说明 |
|------|------|------|
| 80 | Nginx | 统一入口（公网访问） |
| 3306 | MySQL | 数据库（仅本地） |
| 5000 | Brain | 云端大脑 API |
| 5100 | NetSec | 网络安全助手 |
| 8080 | AI Web | AI 助手 Web 界面 |
| 8088 | Nginx Status | Nginx 状态监控 |
| 8089 | Tomcat | Java 容器（可选） |

## 网络安全助手

- 默认管理员: `admin` / `your_password`（可通过环境变量 DEFAULT_ADMIN_PASSWORD 设置）
- 访问: `http://你的服务器IP/netsec/`
- 首次访问自动初始化 MySQL 数据库
- 包含 14 道 DVWA 风格漏洞练习题
- 支持端口扫描、WAF 检测、子域名枚举等工具

## 安全建议

1. **修改默认密码**: 部署后立即修改 NetSec 管理员密码和 MySQL 密码
2. **配置 HTTPS**: 使用 Let's Encrypt 免费证书
   ```bash
   yum install -y certbot python3-certbot-nginx
   certbot --nginx -d your-domain.com
   ```
3. **防火墙最小化**: 仅开放 80/443 端口
4. **API Key 安全**: `.env` 文件权限设为 600
5. **NetSec 安全**: 漏洞练习平台包含真实漏洞，仅限学习使用

## 故障排查

```bash
# 检查 Nginx 配置
nginx -t

# 检查端口监听
ss -tlnp | grep -E '80|3306|5000|5100|8080'

# 检查进程
ps aux | grep python3

# 测试各服务
curl http://127.0.0.1/health           # 健康检查
curl http://127.0.0.1:8080/api/status  # AI 助手
curl http://127.0.0.1:5100/            # NetSec
```
