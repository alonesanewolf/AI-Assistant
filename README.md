# AI 智能助手系统

一个功能丰富的 AI 智能助手，支持通过 QQ/微信/Telegram/Web/命令行，用自然语言远程操控你的电脑。同时集成 **网络安全助手平台**（DVWA 漏洞练习 + 安全扫描工具）。

## 核心功能

### 统一平台入口
- **电脑开机**: AI 助手本地运行，操控电脑 + 云端联动
- **电脑关机**: 通过云服务器继续使用网络安全助手等功能
- **一个网址**: `http://你的服务器IP/` 访问所有服务

### AI 对话与操控
- **多模型支持**: 本地 Ollama (qwen2:7b) + 云端 DeepSeek
- **智能路由**: 简单任务→本地模型，复杂任务→云端模型
- **4 种模式**: 本地优先 / 云端优先 / 仅本地 / 仅云端
- **Web UI**: 漂亮的暗色主题聊天界面
- **17 种电脑操控**: 截图、打开网页/程序、文件管理、系统信息、音量、锁屏等

### 网络安全助手 (NetSec)
- **14 道漏洞练习**: 暴力破解、SQL注入、XSS、CSRF、命令注入、文件包含等
- **安全扫描工具**: 端口扫描、WAF检测、子域名枚举、服务指纹识别、目录扫描
- **通关追踪**: 进度统计、分类完成率、报告管理

### 多渠道接入
- QQ Bot / Telegram Bot / 微信 Bot / Web 控制台

### 云端大脑
- 部署在云服务器上，作为消息中枢
- 连接所有渠道和本地 Agent

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填写你的 API Key
```

### 3. 启动

**统一启动菜单（推荐）**:
```bash
start.bat
```

**或单独启动**:
- Web 界面: `run_local_assistant.bat`
- 命令行: `run.bat`
- Agent 客户端: `start_agent.bat`
- 云端大脑: `start_brain.bat`

### 4. 可选：安装 Ollama（本地模型）
```bash
# 安装 Ollama 后拉取模型
ollama pull qwen2:7b
```

## 项目结构

```
AI_Assistant/
├── local_assistant.py    # ★ AI 助手 Web UI
├── actions.py            # 电脑操控动作集
├── model_router.py       # AI 模型智能路由
├── memory.py             # 记忆与对话管理
├── agent_client.py       # Agent 客户端
├── brain.py              # 云端大脑
├── start_all.bat         # ★ 电脑端一键启动
├── setup_autostart.bat   # ★ 开机自启配置
├── startup_silent.bat    # ★ 静默自启脚本
├── deploy/               # 云服务器部署配置
│   ├── .env.template     # 环境变量模板
│   ├── nginx/
│   │   ├── conf/ai_assistant.conf  # ★ 统一 Nginx 配置
│   │   └── html/index.html        # ★ 统一门户首页
│   ├── netsec/           # ★ 网络安全助手
│   │   ├── run.py        # Flask 主程序 (端口5100)
│   │   ├── templates/    # 43 个 HTML 模板
│   │   └── sql/          # MySQL 初始化脚本
│   └── scripts/
│       ├── deploy.sh     # ★ 一键部署
│       ├── manage.sh     # ★ 服务管理
│       └── start_all.sh  # ★ 云服务器启动
└── server/tomcat/        # Apache Tomcat 8.5.2 (可选)
```

## 云服务器部署

项目包含完整的 CentOS 7.6+ 云服务器部署方案，一键安装 Nginx + MySQL + Python + 所有服务。

### 统一网址架构

```
http://你的服务器IP/
  ├── /              统一门户首页（所有服务入口）
  ├── /ai/           AI 智能助手
  ├── /netsec/       网络安全助手平台
  ├── /brain/        云端大脑 API
  └── /health        健康检查
```

### 一键部署到云服务器

```bash
# 1. 上传项目到服务器
scp -r AI_Assistant/ root@你的服务器IP:/opt/

# 2. SSH 登录后运行
cd /opt/AI_Assistant/deploy/scripts
chmod +x deploy.sh && ./deploy.sh

# 3. 编辑 API Key
vim /opt/ai_assistant/.env

# 4. 启动所有服务
./start_all.sh
```

### 电脑端开机自启

```bash
# Windows: 双击运行 setup_autostart.bat 即可配置开机自启
# 或手动运行: start_all.bat 启动所有服务
```

### 服务管理

```bash
cd /opt/AI_Assistant/deploy/scripts
./manage.sh start      # 启动全部服务
./manage.sh stop       # 停止全部服务
./manage.sh status     # 查看状态
./manage.sh test       # 健康检查
```

### 网络安全助手

- 默认管理员: `admin` / `your_password`（可通过环境变量 DEFAULT_ADMIN_PASSWORD 设置）
- 访问: `http://你的服务器IP/netsec/`
- 首次启动自动初始化数据库

## 技术栈

- Python 3.10+
- Flask (Web 服务)
- Socket.IO (实时通信)
- Ollama (本地模型)
- OpenAI API (云端模型)
- SQLite (数据存储)

## 安全提示

- `.env` 文件包含 API Key，已加入 `.gitignore`
- 执行系统命令使用白名单机制
- 建议在受信任的网络环境中使用
