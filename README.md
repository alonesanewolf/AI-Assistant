# AI 智能助手系统

一个功能丰富的 AI 智能助手，支持通过 QQ/微信/Telegram/Web/命令行，用自然语言远程操控你的电脑。

## 功能特点

### AI 对话
- **多模型支持**: 本地 Ollama (qwen2:7b) + 云端 DeepSeek
- **智能路由**: 简单任务→本地模型，复杂任务→云端模型
- **4 种模式**: 本地优先 / 云端优先 / 仅本地 / 仅云端
- **Web UI**: 漂亮的暗色主题聊天界面

### 电脑远程操控（17 种操作）
| 操作 | 说明 |
|------|------|
| 截图 | 全屏截图，Web 端实时预览 |
| 打开网页/程序/文件 | 控制电脑打开任意内容 |
| 文件管理 | 创建、读取、列出文件 |
| 系统信息 | CPU、内存、磁盘状态 |
| 音量控制 | 调大/调小/静音 |
| 锁屏/进程管理 | 锁屏、查看/终止进程 |
| 按键模拟 | 组合键、文字输入 |
| 剪贴板 | 读写剪贴板 |
| 执行命令 | 安全白名单机制 |
| 桌面通知 | 发送系统通知 |

### 多渠道接入
- **QQ Bot** — OneBot 协议，私聊/群聊操控
- **Telegram Bot** — 远程发送指令
- **微信 Bot** — 企业微信/个人微信接入
- **Web 控制台** — 浏览器直接操作

### 云端大脑
- 部署在云服务器上，作为消息中枢
- 连接所有渠道和本地 Agent
- 消息队列 + 任务分发 + 截图实时推流

### 记忆与持久化
- SQLite 数据库存储对话历史和键值记忆
- AI 可记住偏好和事实
- 支持对话搜索、导出、统计

### 定时任务
- 间隔任务和每日定时任务
- 支持一次性任务
- 任务持久化存储

### 网页搜索
- DuckDuckGo 搜索，无需 API Key

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
├── assistant.py          # 命令行 AI 助手
├── local_assistant.py    # Web UI 本地助手
├── wechat_assistant.py   # 企业微信 AI 助手
├── actions.py            # 电脑操控动作集
├── model_router.py       # AI 模型智能路由
├── memory.py             # 记忆与对话管理
├── scheduler.py          # 定时任务调度
├── config.py             # 配置管理
├── search.py             # 网页搜索
├── agent_client.py       # Agent 客户端
├── brain.py              # 云端大脑
├── qq_bot.py             # QQ Bot
├── telegram_bot.py       # Telegram Bot
├── wechat_bot.py         # 微信 SDK
└── requirements.txt      # 依赖列表
```

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
