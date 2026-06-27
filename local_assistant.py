"""
本地 AI 智能助手 (Local Assistant)
===================================
- 本地 Web 界面，无需云端服务器
- 集成 AI 对话 + 电脑操作 + 记忆功能
- 同时作为 Agent 连接云端 Brain，保持手机遥控功能
- 支持 DeepSeek（云端） + Ollama（本地） 双模型自动切换

启动方式:
    python local_assistant.py
    # 或双击 run_local_assistant.bat
"""

import io
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ==================== Windows 编码修复 ====================
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (ValueError, AttributeError):
        pass

from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit

# 导入现有模块
from model_router import ModelRouter
from actions import ComputerActions
from memory import MemoryStore
from search import WebSearch
from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    MAX_MEMORY_TURNS,
    API_TIMEOUT,
)

# ==================== 配置 ====================
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8080"))
AGENT_NAME = os.environ.get("AGENT_NAME", os.environ.get("COMPUTERNAME", "我的电脑"))

# URL 前缀（通过 Nginx 反向代理时使用，如 /ai）
APP_PREFIX = os.environ.get("APP_PREFIX", "")

# 云端 Brain 地址（保持串联）
BRAIN_URL = os.environ.get("BRAIN_URL", "http://localhost:5000")
ENABLE_BRAIN_AGENT = os.environ.get("ENABLE_BRAIN_AGENT", "true").lower() == "true"

# ==================== Flask + SocketIO ====================
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(24).hex())
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ==================== 初始化模块 ====================
ROUTER_MODE = os.environ.get("ROUTER_MODE", "local_first")  # local_first / cloud_first / local_only / cloud_only
model_router = ModelRouter(mode=ROUTER_MODE)
actions = ComputerActions()
memory = MemoryStore()
# 搜索模块（带 AI 摘要能力，与 assistant.py 保持一致）
search = WebSearch(ai_summarizer=lambda q, items: _ai_summarize_search(q, items, model_router))


def _ai_summarize_search(query: str, items: list, router) -> str:
    """用 AI 对搜索结果做智能摘要（供 WebSearch 回调使用）"""
    if not items or not router:
        return ""
    context_parts = []
    for i, item in enumerate(items[:3], 1):
        context_parts.append(
            f"{i}. 标题: {item['title']}\n"
            f"   摘要: {item['snippet']}\n"
            f"   链接: {item['link']}"
        )
    context = "\n\n".join(context_parts)
    prompt = (
        f"用户搜索了: \"{query}\"\n\n"
        f"以下是搜索结果:\n{context}\n\n"
        f"请用 2-3 句话简洁地总结这些搜索结果的核心内容。用中文回复。"
    )
    try:
        messages = [{"role": "user", "content": prompt}]
        summary = router.chat(messages, temperature=0.3)
        return f"📊 搜索结果摘要:\n{summary}"
    except Exception:
        return ""


# 对话历史
conversations: dict = {}  # session_id -> [messages]
conversations_lock = threading.Lock()

# 云端 Agent 连接状态
brain_connected = False
brain_sid = None


# ==================== AI 系统提示词 ====================

SYSTEM_PROMPT = """你是本地智能助手，运行在用户的电脑上，可以直接操作电脑。

## 你的能力:
1. **电脑操作** - 直接执行系统操作
2. **网页搜索** - 搜索互联网信息
3. **文件管理** - 创建/读取/列出文件
4. **记忆功能** - 记住用户告诉你的信息
5. **定时任务** - 设置提醒和定时操作

## 支持的指令（输出时使用以下格式）:
### 电脑操作
- 打开网页: [CMD:open_url]https://example.com[/CMD]
- 打开程序: [CMD:open_program]程序名[/CMD]
- 创建文件: [CMD:create_file]文件路径|文件内容[/CMD]
- 读取文件: [CMD:read_file]文件路径[/CMD]
- 列出文件: [CMD:list_files]目录路径[/CMD]
- 截图: [CMD:screenshot]保存路径(可选)[/CMD]
- 执行命令: [CMD:run_command]命令[/CMD]
- 系统信息: [CMD:sysinfo][/CMD]
- 发送通知: [CMD:notify]标题|消息内容[/CMD]
- 读取剪贴板: [CMD:clipboard][/CMD]
- 写入剪贴板: [CMD:clipboard]要写入的内容[/CMD]
- 音量控制: [CMD:volume]up/down/mute[/CMD]
- 锁屏: [CMD:lock_screen][/CMD]
- 进程列表: [CMD:get_processes]筛选关键词(可选)[/CMD]
- 终止进程: [CMD:kill_process]进程名[/CMD]
- 模拟按键: [CMD:press_keys]组合键如ctrl+c[/CMD]
- 输入文字: [CMD:type_text]要输入的文字[/CMD]
- 获取时间: [CMD:get_time][/CMD]

### 记忆管理
- 记住: [CMD:remember]键名|值[/CMD]
- 回忆: [CMD:recall]键名[/CMD]
- 忘记: [CMD:forget]键名[/CMD]

### 搜索
- 搜索: [CMD:search]关键词[/CMD]

## 规则:
- 当用户请求操作时，使用 CMD 格式
- 回复简洁友好，不要长篇大论
- 每个回复最多一个 CMD 指令
- 闲聊正常回复即可

当前时间: {current_time}
用户电脑: {agent_name}"""


# ==================== AI 对话 ====================

def call_ai(session_id: str, user_message: str) -> tuple:
    """调用 AI 模型，返回 (reply_text, model_used, source)"""
    with conversations_lock:
        if session_id not in conversations:
            conversations[session_id] = []
        history = conversations[session_id]

        if len(history) > MAX_MEMORY_TURNS * 2:
            history = history[-(MAX_MEMORY_TURNS * 2):]

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                agent_name=AGENT_NAME,
            ),
        }
    ] + history + [{"role": "user", "content": user_message}]

    result = model_router.chat(messages=messages)
    reply = result["content"]
    model_used = result.get("model", "unknown")
    source = result.get("source", "unknown")

    with conversations_lock:
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": reply})
        conversations[session_id] = history

    # 同时保存到记忆数据库
    memory.add_message("user", user_message)
    memory.add_message("assistant", reply)

    if source == "本地":
        print(f"[AI] 本地 Ollama → {model_used}")
    elif source == "云端":
        print(f"[AI] 云端 DeepSeek → {model_used}")

    return reply, model_used, source


def parse_commands(text: str) -> list:
    """解析 CMD 指令"""
    pattern = r"\[CMD:(\w+)\](.*?)\[/CMD\]"
    return re.findall(pattern, text, re.DOTALL)


def clean_reply(text: str) -> str:
    """移除 CMD 标签"""
    return re.sub(r"\[CMD:\w+\].*?\[/CMD\]", "", text, flags=re.DOTALL).strip()


def execute_command(cmd_type: str, params: str) -> str:
    """执行本地操作指令"""
    params = params.strip()

    if cmd_type == "open_url":
        return actions.open_url(params)

    elif cmd_type == "open_program":
        return actions.open_program(params)

    elif cmd_type == "create_file":
        parts = params.split("|", 1)
        path = parts[0].strip()
        content = parts[1] if len(parts) > 1 else ""
        return actions.create_file(path, content)

    elif cmd_type == "read_file":
        return actions.read_file(params)

    elif cmd_type == "list_files":
        return actions.list_files(params if params else ".")

    elif cmd_type == "screenshot":
        # 本地截图：保存文件并返回 base64
        save_path = params if params else None
        try:
            import base64
            import pyautogui
            from io import BytesIO

            if save_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = f"screenshot_{timestamp}.png"

            screenshot = pyautogui.screenshot()

            # 转为 base64 JPEG
            buffer = BytesIO()
            screenshot.save(buffer, format="JPEG", quality=85)
            b64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")

            # 同时保存文件
            screenshot.save(save_path)

            return f"BASE64_JPEG:{b64_data}|截图已保存: {save_path}"
        except ImportError:
            return "截图功能需要安装: pip install pyautogui"
        except Exception as e:
            return f"截图失败: {e}"

    elif cmd_type == "run_command":
        return actions.run_command(params)

    elif cmd_type == "notify":
        parts = params.split("|", 1)
        title = parts[0].strip()
        msg = parts[1].strip() if len(parts) > 1 else ""
        return actions.send_notification(title, msg)

    elif cmd_type == "sysinfo":
        return actions.get_system_info()

    elif cmd_type == "remember":
        parts = params.split("|", 1)
        if len(parts) < 2:
            return "参数不足: remember 需要 键名|值"
        key, value = parts[0].strip(), parts[1].strip()
        memory.set_memory(key, value)
        return f"已记住: {key}"

    elif cmd_type == "recall":
        key = params.strip()
        value = memory.get_memory(key)
        return f"{key}: {value}" if value else f"未找到记忆: {key}"

    elif cmd_type == "forget":
        key = params.strip()
        if memory.delete_memory(key):
            return f"已忘记: {key}"
        return f"未找到记忆: {key}"

    elif cmd_type == "search":
        try:
            return search.search_and_summarize(params)
        except ImportError:
            return f"搜索 '{params}' - 搜索模块未加载"

    elif cmd_type == "clipboard":
        return actions.clipboard_read() if not params else actions.clipboard_write(params)

    elif cmd_type == "volume":
        return actions.volume_control(params if params else "status")

    elif cmd_type == "lock_screen":
        return actions.lock_screen()

    elif cmd_type == "get_processes":
        return actions.get_processes(params)

    elif cmd_type == "kill_process":
        return actions.kill_process(params)

    elif cmd_type == "press_keys":
        return actions.press_keys(params)

    elif cmd_type == "type_text":
        return actions.type_text(params)

    elif cmd_type == "get_time":
        return actions.get_time()

    else:
        return f"未知指令: {cmd_type}"


# ==================== Web UI ====================

LOCAL_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>本地 AI 助手</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <script>
        // Socket.IO 路径前缀（适配 Nginx 反向代理）
        const SOCKET_PATH = '{{ app_prefix }}' ? '{{ app_prefix }}/socket.io' : undefined;
    </script>
    <style>
        :root {
            --bg: #0d1117;
            --card: #161b22;
            --card2: #21262d;
            --border: #30363d;
            --accent: #58a6ff;
            --accent2: #7c3aed;
            --green: #3fb950;
            --red: #f85149;
            --yellow: #d2991d;
            --text: #e6edf3;
            --text2: #8b949e;
            --radius: 12px;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        /* 头部 */
        .header {
            background: var(--card);
            border-bottom: 1px solid var(--border);
            padding: 12px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
        }
        .header-left { display:flex; align-items:center; gap:12px; }
        .logo {
            width: 36px; height: 36px;
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            border-radius: 10px;
            display: flex; align-items:center; justify-content:center;
            font-size: 18px;
        }
        .title { font-size: 18px; font-weight: 700; }
        .header-right { display:flex; gap:10px; align-items:center; }
        .status-dot {
            width: 8px; height: 8px; border-radius: 50%;
        }
        .status-dot.online { background: var(--green); box-shadow: 0 0 6px var(--green); }
        .status-dot.offline { background: var(--red); }
        .status-tag {
            font-size: 12px; color: var(--text2);
            padding: 3px 10px; background: var(--card2); border-radius: 10px;
        }
        /* 主体 */
        .main {
            flex: 1;
            display: flex;
            overflow: hidden;
        }
        /* 侧边栏 */
        .sidebar {
            width: 260px;
            background: var(--card);
            border-right: 1px solid var(--border);
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 14px;
            flex-shrink: 0;
        }
        .sidebar h3 {
            font-size: 11px; text-transform: uppercase;
            letter-spacing: 1px; color: var(--text2);
            margin-bottom: -6px;
        }
        .stat-card {
            background: var(--card2); border-radius: var(--radius);
            padding: 12px;
        }
        .stat-row {
            display: flex; justify-content: space-between;
            padding: 5px 0; font-size: 13px;
        }
        .stat-row .label { color: var(--text2); }
        .stat-row .value { font-weight: 600; }
        .stat-row .value.good { color: var(--green); }
        .stat-row .value.warn { color: var(--yellow); }
        .quick-btn {
            width: 100%;
            background: var(--card2);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text);
            font-size: 13px;
            cursor: pointer;
            text-align: left;
            transition: all .15s;
            font-family: inherit;
            display: flex; align-items:center; gap:8px;
        }
        .quick-btn:hover { border-color: var(--accent); background: rgba(88,166,255,0.1); }
        .quick-btn:active { transform: scale(0.98); }
        /* 对话区 */
        .chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
        }
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .msg {
            max-width: 75%;
            padding: 12px 16px;
            border-radius: 14px;
            line-height: 1.55;
            font-size: 14px;
            animation: fadeIn 0.3s ease;
            word-break: break-word;
        }
        @keyframes fadeIn { from { opacity:0; transform: translateY(8px); } to { opacity:1; transform: translateY(0); } }
        .msg.user {
            align-self: flex-end;
            background: linear-gradient(135deg, #1f6feb, #58a6ff);
            color: #fff;
            border-bottom-right-radius: 4px;
        }
        .msg.assistant {
            align-self: flex-start;
            background: var(--card2);
            border-bottom-left-radius: 4px;
        }
        .msg.system {
            align-self: center;
            background: rgba(255,255,255,0.03);
            color: var(--text2);
            font-size: 12px;
            padding: 6px 14px;
            border-radius: 8px;
        }
        .msg .cmd-tag {
            display: inline-block;
            background: rgba(63,185,80,0.15);
            color: var(--green);
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            margin-top: 6px;
        }
        .msg .screenshot-preview {
            margin-top: 8px;
            max-width: 300px;
            border-radius: 8px;
            border: 1px solid var(--border);
            cursor: pointer;
        }
        /* 输入区 */
        .input-area {
            padding: 14px 20px;
            background: var(--card);
            border-top: 1px solid var(--border);
            display: flex;
            gap: 10px;
            flex-shrink: 0;
        }
        .input-area input {
            flex: 1;
            padding: 12px 16px;
            background: var(--card2);
            border: 1px solid var(--border);
            border-radius: 10px;
            color: var(--text);
            font-size: 14px;
            outline: none;
            font-family: inherit;
            transition: border-color 0.2s;
        }
        .input-area input:focus { border-color: var(--accent); }
        .input-area input::placeholder { color: var(--text2); }
        .input-area button {
            padding: 12px 22px;
            background: linear-gradient(135deg, #1f6feb, #58a6ff);
            border: none;
            border-radius: 10px;
            color: #fff;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
            font-family: inherit;
            white-space: nowrap;
        }
        .input-area button:hover { opacity: 0.9; }
        .input-area button:disabled { opacity: 0.5; cursor: not-allowed; }
        /* 滚动条 */
        .messages::-webkit-scrollbar { width: 5px; }
        .messages::-webkit-scrollbar-track { background: transparent; }
        .messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        /* Toast */
        .toast {
            position: fixed; bottom: 80px; left: 50%;
            transform: translateX(-50%);
            background: var(--card2); color: var(--text);
            padding: 10px 20px; border-radius: 20px;
            font-size: 13px; z-index: 999;
            opacity: 0; transition: opacity .2s;
            pointer-events: none;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        }
        .toast.show { opacity: 1; }
        .toast.success { background: rgba(63,185,80,0.2); color: var(--green); }
        .toast.error { background: rgba(248,81,73,0.2); color: var(--red); }
        /* 截图全屏模态 */
        .modal-overlay {
            display: none; position: fixed;
            top:0; left:0; right:0; bottom:0;
            background: rgba(0,0,0,0.92);
            z-index: 2000;
            justify-content: center; align-items: center;
            flex-direction: column;
        }
        .modal-overlay.show { display: flex; }
        .modal-overlay img {
            max-width: 95%; max-height: 85vh;
            object-fit: contain; border-radius: 8px;
        }
        .modal-close {
            position: absolute; top: 15px; right: 20px;
            background: rgba(255,255,255,0.15);
            border: none; color: #fff;
            width: 36px; height: 36px; border-radius: 50%;
            font-size: 20px; cursor: pointer;
            display: flex; align-items:center; justify-content:center;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <div class="logo">&#x1F916;</div>
            <div>
                <div class="title">本地 AI 助手</div>
                <div style="font-size:11px;color:var(--text2)">运行在 <span id="hostname">-</span></div>
            </div>
        </div>
        <div class="header-right">
            <span class="status-tag" id="sourceTag" style="font-size:11px;">--</span>
            <span class="status-tag" id="modelTag" style="font-size:11px;">--</span>
            <span class="status-tag" id="brainTag" style="display:none;font-size:11px;">云端已连</span>
            <div class="status-dot online" id="statusDot"></div>
        </div>
    </div>

    <div class="main">
        <!-- 侧边栏 -->
        <div class="sidebar">
            <h3>&#x2699; 快捷操作</h3>
            <button class="quick-btn" onclick="doQuickAction('screenshot')">&#x1F4F8; 截取屏幕</button>
            <button class="quick-btn" onclick="doQuickAction('sysinfo')">&#x1F4CA; 系统信息</button>
            <button class="quick-btn" onclick="doQuickAction('list_files')">&#x1F4C1; 浏览文件</button>
            <button class="quick-btn" onclick="doQuickAction('open_url','https://www.baidu.com')">&#x1F310; 打开百度</button>
            <button class="quick-btn" onclick="doQuickAction('open_program','notepad')">&#x1F4DD; 打开记事本</button>
            <button class="quick-btn" onclick="doQuickAction('open_program','calc')">&#x1F5A9; 打开计算器</button>
            <button class="quick-btn" onclick="doQuickAction('get_time')">&#x1F552; 当前时间</button>
            <button class="quick-btn" onclick="doQuickAction('clipboard')">&#x1F4CB; 读取剪贴板</button>
            <button class="quick-btn" onclick="doQuickAction('get_processes')">&#x1F4CA; 进程列表</button>
            <button class="quick-btn" onclick="doQuickAction('lock_screen')">&#x1F512; 锁定屏幕</button>
            <div style="display:flex;gap:4px;">
                <button class="quick-btn" style="flex:1;text-align:center;justify-content:center;" onclick="doQuickAction('volume','down')">&#x1F509;</button>
                <button class="quick-btn" style="flex:1;text-align:center;justify-content:center;" onclick="doQuickAction('volume','mute')">&#x1F507;</button>
                <button class="quick-btn" style="flex:1;text-align:center;justify-content:center;" onclick="doQuickAction('volume','up')">&#x1F50A;</button>
            </div>

            <h3>&#x1F4CA; 系统状态</h3>
            <div class="stat-card">
                <div class="stat-row">
                    <span class="label">当前模型</span>
                    <span class="value good" id="statModel">-</span>
                </div>
                <div class="stat-row">
                    <span class="label">来源</span>
                    <span class="value" id="statSource">-</span>
                </div>
                <div class="stat-row">
                    <span class="label">路由模式</span>
                    <span class="value" id="statMode">-</span>
                </div>
                <div class="stat-row">
                    <span class="label">DeepSeek</span>
                    <span class="value" id="statDeepseek">-</span>
                </div>
                <div class="stat-row">
                    <span class="label">Ollama</span>
                    <span class="value" id="statOllama">-</span>
                </div>
                <div class="stat-row">
                    <span class="label">对话轮数</span>
                    <span class="value" id="statTurns">0</span>
                </div>
                <div class="stat-row">
                    <span class="label">记忆条目</span>
                    <span class="value" id="statMemory">0</span>
                </div>
                <div class="stat-row">
                    <span class="label">云端大脑</span>
                    <span class="value" id="statBrain">-</span>
                </div>
            </div>

            <h3>&#x1F527; 模型控制</h3>
            <div style="display:flex;flex-direction:column;gap:6px;">
                <select id="modeSelect" onchange="switchMode()"
                    style="width:100%;padding:8px 10px;background:var(--card2);border:1px solid var(--border);
                           border-radius:8px;color:var(--text);font-size:13px;cursor:pointer;font-family:inherit;">
                    <option value="local_first">本地优先（推荐）</option>
                    <option value="cloud_first">云端优先</option>
                    <option value="local_only">仅本地模型</option>
                    <option value="cloud_only">仅云端模型</option>
                </select>
                <select id="modelSelect" onchange="switchModel()"
                    style="width:100%;padding:8px 10px;background:var(--card2);border:1px solid var(--border);
                           border-radius:8px;color:var(--text);font-size:13px;cursor:pointer;font-family:inherit;">
                </select>
                <button class="quick-btn" onclick="exportConversation()"
                    style="text-align:center;justify-content:center;">&#x1F4E5; 导出对话记录</button>
            </div>

            <h3>&#x1F4AC; 示例对话</h3>
            <div style="font-size:12px;color:var(--text2);line-height:1.6;">
                <div style="margin-bottom:4px;">"帮我搜索 Python 教程"</div>
                <div style="margin-bottom:4px;">"打开记事本并写一段代码"</div>
                <div style="margin-bottom:4px;">"记住我的生日是 5 月 1 日"</div>
                <div style="margin-bottom:4px;">"截个图看看"</div>
                <div style="margin-bottom:4px;">"音量调大一点"</div>
                <div style="margin-bottom:4px;">"查看剪贴板内容"</div>
                <div>"锁屏"</div>
            </div>
        </div>

        <!-- 对话区 -->
        <div class="chat-area">
            <div class="messages" id="messages">
                <div class="msg system">&#x1F44B; 你好！我是你的本地 AI 助手。我可以帮你操作电脑、搜索信息、管理文件等。试试输入指令吧！</div>
            </div>
            <div class="input-area">
                <input type="text" id="input" placeholder="输入消息或指令... (Enter 发送)"
                       onkeydown="if(event.key==='Enter') sendMessage()" autofocus>
                <button id="sendBtn" onclick="sendMessage()">&#x27A4; 发送</button>
            </div>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <!-- 全屏截图 -->
    <div class="modal-overlay" id="fullscreenModal" onclick="closeFullscreen()">
        <button class="modal-close">&times;</button>
        <img id="fullscreenImg" alt="截图" />
        <div style="color:#666;margin-top:8px;font-size:12px;">点击关闭</div>
    </div>

    <script>
        const socket = io({ path: SOCKET_PATH ? SOCKET_PATH : '/socket.io' });
        const sessionId = 'local_' + Date.now();
        let currentModel = '-';
        let currentSource = '-';
        let localModels = [];

        socket.on('connect', () => {
            socket.emit('register', { session_id: sessionId });
            refreshStatus();
        });

        socket.on('brain_status', (data) => {
            const tag = document.getElementById('brainTag');
            document.getElementById('statBrain').textContent = data.connected ? '已连接' : '离线';
            document.getElementById('statBrain').className = 'value ' + (data.connected ? 'good' : 'warn');
            tag.style.display = data.connected ? 'inline' : 'none';
        });

        function sendMessage() {
            const input = document.getElementById('input');
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            document.getElementById('sendBtn').disabled = true;

            addMessage('user', text);

            socket.emit('chat_message', {
                session_id: sessionId,
                message: text,
            });
        }

        socket.on('chat_reply', (data) => {
            addMessage('assistant', data.reply, data.command, data.screenshot);
            document.getElementById('sendBtn').disabled = false;
            document.getElementById('input').focus();

            if (data.model) {
                currentModel = data.model;
                document.getElementById('modelTag').textContent = data.model;
            }
            if (data.source) {
                currentSource = data.source;
                const sourceTag = document.getElementById('sourceTag');
                sourceTag.textContent = data.source;
                sourceTag.style.background = data.source === '本地' ? 'rgba(63,185,80,0.15)' : 'rgba(88,166,255,0.15)';
                sourceTag.style.color = data.source === '本地' ? 'var(--green)' : 'var(--accent)';
            }

            refreshStatus();
        });

        socket.on('chat_error', (data) => {
            addMessage('system', '❌ ' + data.error);
            document.getElementById('sendBtn').disabled = false;
        });

        function addMessage(role, text, cmd, screenshot) {
            const container = document.getElementById('messages');
            const div = document.createElement('div');
            div.className = 'msg ' + role;

            // 检查是否有截图数据
            if (text && text.startsWith('BASE64_JPEG:')) {
                const parts = text.split('|');
                const b64 = parts[0].substring(12);
                const info = parts[1] || '截图';

                div.textContent = info;
                const img = document.createElement('img');
                img.className = 'screenshot-preview';
                img.src = 'data:image/jpeg;base64,' + b64;
                img.onclick = () => openFullscreen(b64);
                div.appendChild(img);
            } else {
                div.textContent = text;
            }

            if (cmd) {
                const tag = document.createElement('span');
                tag.className = 'cmd-tag';
                tag.textContent = '已执行: ' + cmd.type;
                div.appendChild(document.createElement('br'));
                div.appendChild(tag);
            }

            if (screenshot) {
                const img = document.createElement('img');
                img.className = 'screenshot-preview';
                img.src = 'data:image/jpeg;base64,' + screenshot;
                img.onclick = () => openFullscreen(screenshot);
                div.appendChild(img);
            }

            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }

        async function doQuickAction(command, params) {
            params = params || '';
            addMessage('system', '执行: ' + command + (params ? ' ' + params : ''));

            try {
                const resp = await fetch('/api/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command, params, session_id: sessionId })
                });
                const data = await resp.json();
                addMessage('system', data.result || '完成');

                // 如果是截图，显示预览
                if (command === 'screenshot' && data.screenshot) {
                    const container = document.getElementById('messages');
                    const div = document.createElement('div');
                    div.className = 'msg system';
                    const img = document.createElement('img');
                    img.className = 'screenshot-preview';
                    img.src = 'data:image/jpeg;base64,' + data.screenshot;
                    img.onclick = () => openFullscreen(data.screenshot);
                    div.appendChild(img);
                    container.appendChild(div);
                    container.scrollTop = container.scrollHeight;
                }
            } catch(e) {
                addMessage('system', '❌ 错误: ' + e.message);
            }
        }

        function openFullscreen(b64) {
            const modal = document.getElementById('fullscreenModal');
            document.getElementById('fullscreenImg').src = 'data:image/jpeg;base64,' + b64;
            modal.classList.add('show');
        }

        function closeFullscreen() {
            document.getElementById('fullscreenModal').classList.remove('show');
        }

        async function refreshStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                document.getElementById('hostname').textContent = data.hostname;
                document.getElementById('statModel').textContent = currentModel || data.model || '-';
                document.getElementById('statSource').textContent = currentSource || '-';
                document.getElementById('statMode').textContent = modeLabel(data.router_mode);
                document.getElementById('statDeepseek').textContent = data.deepseek ? '可用' : '离线';
                document.getElementById('statDeepseek').className = 'value ' + (data.deepseek ? 'good' : 'warn');
                document.getElementById('statOllama').textContent = data.ollama ? '可用' : '未运行';
                document.getElementById('statOllama').className = 'value ' + (data.ollama ? 'good' : 'warn');
                document.getElementById('statTurns').textContent = data.turns || 0;
                document.getElementById('statMemory').textContent = data.memories || 0;
                document.getElementById('statBrain').textContent = data.brain_connected ? '已连接' : '离线';
                document.getElementById('statBrain').className = 'value ' + (data.brain_connected ? 'good' : 'warn');

                // 更新模式选择器
                const modeSelect = document.getElementById('modeSelect');
                if (data.router_mode) {
                    modeSelect.value = data.router_mode;
                }

                // 更新本地模型列表
                if (data.local_models && data.local_models.length > 0) {
                    localModels = data.local_models;
                    const modelSelect = document.getElementById('modelSelect');
                    modelSelect.innerHTML = '';
                    for (const m of data.local_models) {
                        const opt = document.createElement('option');
                        opt.value = m;
                        opt.textContent = m;
                        if (m === data.model) opt.selected = true;
                        modelSelect.appendChild(opt);
                    }
                }
            } catch(e) {}
        }

        function modeLabel(mode) {
            const map = {
                'local_first': '本地优先',
                'cloud_first': '云端优先',
                'local_only': '仅本地',
                'cloud_only': '仅云端'
            };
            return map[mode] || mode;
        }

        async function switchMode() {
            const mode = document.getElementById('modeSelect').value;
            try {
                const resp = await fetch('/api/router/mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode })
                });
                const data = await resp.json();
                if (data.success) {
                    addMessage('system', '路由模式已切换: ' + modeLabel(mode));
                    refreshStatus();
                }
            } catch(e) {
                addMessage('system', '切换失败: ' + e.message);
            }
        }

        async function switchModel() {
            const model = document.getElementById('modelSelect').value;
            if (!model) return;
            try {
                const resp = await fetch('/api/router/model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model })
                });
                const data = await resp.json();
                if (data.success) {
                    addMessage('system', 'Ollama 模型已切换: ' + model);
                    refreshStatus();
                } else {
                    addMessage('system', '切换失败: ' + (data.error || '未知错误'));
                }
            } catch(e) {
                addMessage('system', '切换失败: ' + e.message);
            }
        }

        // 导出对话
        async function exportConversation() {
            try {
                const resp = await fetch('/api/conversation/export?session_id=' + sessionId);
                const data = await resp.json();
                if (data.messages && data.messages.length > 0) {
                    // 生成 Markdown 格式
                    let md = '# AI 助手对话记录\n\n';
                    md += '导出时间: ' + new Date().toLocaleString() + '\n\n---\n\n';
                    for (const msg of data.messages) {
                        const role = msg.role === 'user' ? '你' : 'AI';
                        md += '**' + role + '**: ' + msg.content + '\n\n';
                    }
                    // 下载文件
                    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'conversation_' + new Date().toISOString().slice(0,10) + '.md';
                    a.click();
                    URL.revokeObjectURL(url);
                    addMessage('system', '对话记录已导出 (' + data.messages.length + ' 条消息)');
                } else {
                    addMessage('system', '没有对话记录可导出');
                }
            } catch(e) {
                addMessage('system', '导出失败: ' + e.message);
            }
        }

        // 定时刷新状态
        setInterval(refreshStatus, 30000);
        refreshStatus();
    </script>
</body>
</html>"""


# ==================== HTTP 路由 ====================

@app.route("/")
def index():
    """主界面"""
    return render_template_string(LOCAL_UI_HTML, app_prefix=APP_PREFIX)


@app.route("/api/status")
def api_status():
    """系统状态"""
    full_status = model_router.get_full_status()
    model_status = {k: v for k, v in full_status.items() if k in ("deepseek", "ollama")}
    mem_summary = memory.get_memory_summary()
    with conversations_lock:
        turns = len(conversations.get("local_default", [])) // 2
    return jsonify({
        "hostname": AGENT_NAME,
        "model": full_status.get("ollama", {}).get("model", "-"),
        "deepseek": model_status.get("deepseek", {}).get("available", False),
        "ollama": model_status.get("ollama", {}).get("available", False),
        "turns": turns,
        "memories": mem_summary.get("memory_count", 0),
        "brain_connected": brain_connected,
        "router_mode": full_status.get("router_mode", "local_first"),
        "local_models": full_status.get("local_models", []),
    })


@app.route("/api/router/mode", methods=["POST"])
def api_set_router_mode():
    """切换路由模式"""
    data = request.get_json()
    mode = data.get("mode", "")
    if mode not in ModelRouter.MODES:
        return jsonify({"error": f"无效模式，支持: {ModelRouter.MODES}"}), 400
    model_router.set_mode(mode)
    return jsonify({"success": True, "mode": mode})


@app.route("/api/router/model", methods=["POST"])
def api_set_ollama_model():
    """切换 Ollama 模型"""
    data = request.get_json()
    model_name = data.get("model", "")
    if not model_name:
        return jsonify({"error": "缺少 model 参数"}), 400
    # 验证模型是否存在
    local_models = model_router.list_local_models()
    if model_name not in local_models:
        return jsonify({"error": f"模型不存在，可用: {local_models}"}), 400
    model_router.set_ollama_model(model_name)
    return jsonify({"success": True, "model": model_name})


@app.route("/api/action", methods=["POST"])
def api_action():
    """直接执行操作（不经过 AI）"""
    data = request.get_json()
    if not data or "command" not in data:
        return jsonify({"error": "缺少 command 字段"}), 400

    command = data["command"]
    params = data.get("params", "")
    session_id = data.get("session_id", "local_default")

    result = execute_command(command, params)

    # 检查是否有截图数据
    screenshot = None
    display_result = result
    if command == "screenshot" and result.startswith("BASE64_JPEG:"):
        parts = result.split("|", 1)
        screenshot = parts[0][12:]
        display_result = parts[1] if len(parts) > 1 else "截图已完成"

    return jsonify({
        "command": command,
        "result": display_result,
        "screenshot": screenshot,
        "success": True,
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """HTTP API 对话（供外部调用）"""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "缺少 message 字段"}), 400

    session_id = data.get("session_id", "api_local")
    message = data["message"]

    try:
        reply, model_used, source = call_ai(session_id, message)
        commands = parse_commands(reply)
        clean = clean_reply(reply)

        cmd_result = None
        screenshot = None
        if commands:
            cmd_type, cmd_params = commands[0]
            exec_result = execute_command(cmd_type, cmd_params)
            cmd_result = {"type": cmd_type, "result": exec_result}
            if cmd_type == "screenshot" and exec_result.startswith("BASE64_JPEG:"):
                parts = exec_result.split("|", 1)
                screenshot = parts[0][12:]

        return jsonify({
            "reply": clean,
            "command": cmd_result,
            "screenshot": screenshot,
            "success": True,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/conversation/export")
def api_export_conversation():
    """导出对话记录"""
    session_id = request.args.get("session_id", "local_default")
    with conversations_lock:
        history = conversations.get(session_id, [])
    return jsonify({
        "session_id": session_id,
        "messages": history,
        "count": len(history),
    })


@app.route("/api/conversation/clear", methods=["POST"])
def api_clear_conversation():
    """清除对话历史"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "local_default")
    with conversations_lock:
        if session_id in conversations:
            conversations[session_id] = []
    return jsonify({"success": True, "message": "对话已清除"})


# ==================== Socket.IO 事件 ====================

@socketio.on("connect")
def handle_connect():
    print(f"[Socket] 客户端连接: {request.sid}")


@socketio.on("register")
def handle_register(data: dict):
    session_id = data.get("session_id", "default")
    print(f"[注册] Web 客户端: {session_id}")


@socketio.on("chat_message")
def handle_chat_message(data: dict):
    """处理 Web 聊天消息"""
    session_id = data.get("session_id", "local_default")
    message = data.get("message", "")

    if not message:
        emit("chat_error", {"error": "消息为空"})
        return

    try:
        # 调用 AI
        reply, model_used, source = call_ai(session_id, message)
        commands = parse_commands(reply)
        clean = clean_reply(reply)

        cmd_info = None
        screenshot_b64 = None

        # 执行指令
        if commands:
            cmd_type, cmd_params = commands[0]
            exec_result = execute_command(cmd_type, cmd_params)
            cmd_info = {"type": cmd_type, "params": cmd_params.strip()}

            # 截图处理
            if cmd_type == "screenshot" and exec_result.startswith("BASE64_JPEG:"):
                parts = exec_result.split("|", 1)
                screenshot_b64 = parts[0][12:]
                exec_result = parts[1] if len(parts) > 1 else "截图已完成"

            print(f"[执行] {cmd_type}: {exec_result[:60]}")

        emit("chat_reply", {
            "reply": clean,
            "command": cmd_info,
            "screenshot": screenshot_b64,
            "model": model_used,
            "source": source,
        })

    except Exception as e:
        print(f"[错误] chat_message: {e}")
        emit("chat_error", {"error": str(e)})


# ==================== 云端 Brain Agent 串联 ====================

def brain_agent_loop():
    """
    作为 Agent 连接云端 Brain，保持手机遥控功能
    复用 agent_client.py 的逻辑
    """
    global brain_connected, brain_sid

    if not ENABLE_BRAIN_AGENT:
        print("[Brain Agent] 已禁用（ENABLE_BRAIN_AGENT=false）")
        return

    import socket
    import socketio as sio

    agent_id = f"agent_{socket.gethostname().lower().replace('-','_')}"

    agent_sio = sio.Client(
        reconnection=True,
        reconnection_attempts=999,
        reconnection_delay=5,
        reconnection_delay_max=30,
        logger=False,
        engineio_logger=False,
    )

    @agent_sio.on("connect")
    def on_connect():
        global brain_connected
        brain_connected = True
        agent_sio.emit("register", {
            "type": "agent",
            "agent_id": agent_id,
            "name": AGENT_NAME,
            "hostname": socket.gethostname(),
        })
        # 上报能力
        agent_sio.emit("agent_capability", {
            "agent_id": agent_id,
            "commands": [
                "screenshot", "open_website", "open_app", "create_file",
                "read_file", "file_info", "run_command", "get_time",
                "clipboard", "volume_control", "system_info", "lock_screen",
                "kill_process", "press_keys", "type_text", "get_processes",
            ],
        })
        print(f"[Brain Agent] 已连接云端大脑: {BRAIN_URL}")
        socketio.emit("brain_status", {"connected": True})

    @agent_sio.on("disconnect")
    def on_disconnect():
        global brain_connected
        brain_connected = False
        print("[Brain Agent] 与云端大脑断开，将自动重连...")
        socketio.emit("brain_status", {"connected": False})

    @agent_sio.on("agent_command")
    def on_command(data: dict):
        """接收云端大脑发来的指令"""
        task_id = data.get("task_id", "")
        command = data.get("command", "")
        params = data.get("params", "")

        print(f"[Brain Agent] 收到指令: {command} (task: {task_id})")

        try:
            result = execute_agent_command(command, params)
            agent_sio.emit("agent_result", {
                "task_id": task_id,
                "command": command,
                "result": result,
                "success": True,
                "agent_id": agent_id,
            })
        except Exception as e:
            agent_sio.emit("agent_result", {
                "task_id": task_id,
                "command": command,
                "result": f"执行失败: {e}",
                "success": False,
                "agent_id": agent_id,
            })

    @agent_sio.on("heartbeat_ack")
    def on_heartbeat(data):
        pass

    # 心跳
    def heartbeat():
        while agent_sio.connected:
            time.sleep(30)
            try:
                agent_sio.emit("agent_heartbeat", {
                    "agent_id": agent_id,
                    "time": datetime.now().isoformat(),
                })
            except Exception:
                pass

    # 连接循环
    while True:
        try:
            print(f"[Brain Agent] 正在连接云端大脑 {BRAIN_URL} ...")
            agent_sio.connect(BRAIN_URL, wait_timeout=10)
            threading.Thread(target=heartbeat, daemon=True).start()
            agent_sio.wait()
        except Exception as e:
            print(f"[Brain Agent] 连接失败: {e}，5秒后重试...")
            time.sleep(5)


def execute_agent_command(command: str, params: str) -> str:
    """
    执行云端大脑发来的指令（统一复用 agent_client 的 CommandExecutor）
    """
    from agent_client import CommandExecutor
    success, result = CommandExecutor.execute(command, params)
    return result

# ==================== 启动 ====================

def main():
    print("=" * 60)
    print("  本地 AI 智能助手 启动中...")
    print("=" * 60)
    print(f"  电脑名称: {AGENT_NAME}")
    print(f"  Web 界面: http://localhost:{PORT}")
    print(f"  路由模式: {model_router.mode}")
    print(f"  云端大脑: {BRAIN_URL if ENABLE_BRAIN_AGENT else '未启用'}")
    print("=" * 60)

    # 检查模型状态
    full_status = model_router.get_full_status()
    model_status = {k: v for k, v in full_status.items() if k in ("deepseek", "ollama")}
    for name, info in model_status.items():
        icon = "[OK]" if info["available"] else "[--]"
        print(f"  {icon} {name}: {info['model']} ({info['type']})")

    local_models = full_status.get("local_models", [])
    if local_models:
        current = model_router.get_ollama_model()
        print(f"  本地模型: {', '.join(local_models)}")
        print(f"  当前使用: {current}")
    print("=" * 60)

    # 启动云端 Brain Agent 串联
    if ENABLE_BRAIN_AGENT:
        threading.Thread(target=brain_agent_loop, daemon=True, name="BrainAgent").start()
        print("[启动] 云端 Brain Agent 线程已启动")
    else:
        print("[启动] 云端 Brain Agent 未启用")

    # 启动 Web 服务
    print(f"\n[启动] Web 服务运行在 http://localhost:{PORT}")
    print("[提示] 按 Ctrl+C 停止服务\n")

    socketio.run(
        app,
        host=HOST,
        port=PORT,
        debug=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
