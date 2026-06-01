"""
云端大脑 (Brain) - Flask + SocketIO 服务
==========================================
功能:
  1. Web 界面 - 与 AI 对话（DeepSeek + 本地 Ollama 双模型）
  2. WebSocket - 与本地 Agent 双向通信（电脑串联）
  3. Redis 消息队列 - 异步任务调度（可选，回退内存队列）
  4. QQ Bot 接入 - 正向 WebSocket / HTTP 回调双模式
  5. 微信接入 - 企业微信机器人 / 个人微信 / HTTP 回调
  6. 指令路由 - 20+ 种电脑操作指令

架构:
  QQ/微信/浏览器 --> Brain(Flask+SocketIO) --> Redis Queue --> Agent Client --> 电脑执行
                                          ^                                    |
                                          +------ WebSocket 直连 --------------+
"""

import io
import json
import os
import re
import sys
import time
import uuid
import threading
from datetime import datetime
from typing import Optional

# ==================== 编码修复（必须在最前面） ====================
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (ValueError, AttributeError):
        pass

from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room

# 导入模型路由器（支持 DeepSeek + 本地 Ollama）
from model_router import ModelRouter

# ==================== 配置 ====================

# DeepSeek 配置（在 model_router.py 中已定义，此处保留兼容）
DEEPSEEK_API_KEY = "REDACTED"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# QQ Bot 配置
QQ_BOT_ENABLED = os.environ.get("QQ_BOT_ENABLED", "").lower() == "true"
QQ_WS_URL = os.environ.get("QQ_WS_URL", "ws://localhost:3001")

# 微信配置
WECHAT_ENABLED = os.environ.get("WECHAT_ENABLED", "").lower() == "true"
WECOM_BOT_KEY = os.environ.get("WECOM_BOT_KEY", "")

# Telegram 配置（手机遥控）
TELEGRAM_ENABLED = os.environ.get("TELEGRAM_BOT_TOKEN", "") != ""
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Redis 配置
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))

# 服务配置
HOST = "0.0.0.0"
PORT = 5000

# ==================== Redis 消息队列 ====================

class RedisQueue:
    """Redis 消息队列（带内存回退，健壮的异常处理）"""

    def __init__(self):
        self._redis = None
        self._fallback_queue: list = []
        self._fallback_results: dict = {}
        self._use_redis = False
        self._lock = threading.Lock()
        self._connect()

    def _connect(self) -> None:
        """尝试连接 Redis"""
        try:
            import redis
            self._redis = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                socket_connect_timeout=2,
                socket_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
                decode_responses=True,
            )
            self._redis.ping()
            self._use_redis = True
            print("[Redis] 连接成功")
        except Exception as e:
            print(f"[Redis] 连接失败({type(e).__name__})，使用内存队列回退")
            self._use_redis = False

    def _reconnect_redis(self):
        """尝试重连 Redis"""
        self._use_redis = False
        self._redis = None
        self._connect()

    def push_task(self, task: dict) -> str:
        """推送任务到队列，返回任务ID"""
        task_id = task.get("task_id", str(uuid.uuid4())[:8])
        task["task_id"] = task_id
        task["status"] = "pending"
        task["created_at"] = datetime.now().isoformat()

        with self._lock:
            if self._use_redis:
                try:
                    self._redis.lpush("brain:tasks", json.dumps(task))
                    return task_id
                except Exception:
                    self._reconnect_redis()
            self._fallback_queue.append(task)
        return task_id

    def pop_task(self, timeout: int = 3) -> Optional[dict]:
        """从队列取出任务（线程安全）"""
        with self._lock:
            if self._use_redis:
                try:
                    result = self._redis.brpop("brain:tasks", timeout=timeout)
                    if result:
                        return json.loads(result[1])
                except Exception:
                    self._reconnect_redis()
            if self._fallback_queue:
                return self._fallback_queue.pop(0)
        return None

    def blocking_pop_task(self, timeout: int = 5) -> Optional[dict]:
        """阻塞式取任务，专门给 worker 线程用，内置重连逻辑"""
        if not self._use_redis:
            # 内存模式：轮询等待
            deadline = time.time() + timeout
            while time.time() < deadline:
                with self._lock:
                    if self._fallback_queue:
                        return self._fallback_queue.pop(0)
                time.sleep(0.5)
            return None

        # Redis 模式：brpop 阻塞等待，出错自动重连
        while True:
            try:
                result = self._redis.brpop("brain:tasks", timeout=timeout)
                if result:
                    return json.loads(result[1])
                return None
            except Exception as e:
                print(f"[Redis] brpop 错误({type(e).__name__})，5秒后重连...")
                self._reconnect_redis()
                if not self._use_redis:
                    # 已回退到内存模式
                    return self.blocking_pop_task(timeout)
                time.sleep(5)

    def set_result(self, task_id: str, result: dict) -> None:
        """保存任务执行结果"""
        result["completed_at"] = datetime.now().isoformat()
        with self._lock:
            if self._use_redis:
                try:
                    self._redis.setex(
                        f"brain:result:{task_id}",
                        3600,
                        json.dumps(result),
                    )
                    return
                except Exception:
                    self._reconnect_redis()
            self._fallback_results[task_id] = result

    def get_result(self, task_id: str) -> Optional[dict]:
        """获取任务结果"""
        if self._use_redis:
            try:
                data = self._redis.get(f"brain:result:{task_id}")
                if data:
                    return json.loads(data)
            except Exception:
                self._reconnect_redis()
        return self._fallback_results.get(task_id)

    def get_queue_length(self) -> int:
        """获取队列长度"""
        if self._use_redis:
            try:
                return self._redis.llen("brain:tasks")
            except Exception:
                self._reconnect_redis()
        return len(self._fallback_queue)

    @property
    def is_connected(self) -> bool:
        return self._use_redis


# ==================== Flask + SocketIO 初始化 ====================

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                     max_http_buffer_size=10_000_000,  # 10MB，支持大截图传输
                     ping_timeout=60, ping_interval=25)

# 初始化组件
queue = RedisQueue()
model_router = ModelRouter()  # 智能模型路由器（DeepSeek + Ollama）

# QQ Bot（如果启用）
qq_bot = None
if QQ_BOT_ENABLED:
    from qq_bot import QQBot
    qq_bot = QQBot(ws_url=QQ_WS_URL)

# 微信 Bot（如果启用）
wechat_bot = None
if WECHAT_ENABLED:
    from wechat_bot import WeChatBot
    wechat_bot = WeChatBot(mode="wecom", webhook_key=WECOM_BOT_KEY)

# Telegram Bot（如果启用）
telegram_bot = None
if TELEGRAM_ENABLED:
    from telegram_bot import TelegramBot
    telegram_bot = TelegramBot(token=TELEGRAM_BOT_TOKEN)

# 存储已连接的 Agent
connected_agents: dict = {}  # agent_id -> {sid, name, status, ...}
agents_lock = threading.Lock()

# 对话历史（按会话存储）
conversations: dict = {}  # session_id -> [messages]

# 待发送的消息队列（QQ 等外部通道的回复）
pending_replies: list = []
replies_lock = threading.Lock()

# 截图缓存（最新截图的 base64 数据）
latest_screenshot: str = ""
screenshot_lock = threading.Lock()


# ==================== AI 系统提示词 ====================

SYSTEM_PROMPT = """你是一个云端智能大脑，负责理解用户意图并将指令发送给本地 Agent 在用户的电脑上执行。

## 你的能力:
1. 理解自然语言，识别用户想要执行的操作
2. 将用户意图转换为标准指令格式
3. 回复用户时简洁友好

## 支持的指令（输出时使用以下格式）:
### 基础操作
- 打开网页: [CMD:open_website]https://example.com[/CMD]
- 打开程序: [CMD:open_app]程序名[/CMD]
- 创建文件: [CMD:create_file]文件路径|文件内容[/CMD]
- 截图: [CMD:screenshot]保存路径(可选)[/CMD]
- 执行命令: [CMD:run_command]系统命令[/CMD]
- 获取时间: [CMD:get_time][/CMD]

### 电脑串联操作
- 查看文件信息: [CMD:file_info]文件或目录路径[/CMD]
- 读取文件内容: [CMD:read_file]文件路径[/CMD]
- 剪贴板读取: [CMD:clipboard][/CMD]
- 剪贴板写入: [CMD:clipboard]要写入的内容[/CMD]
- 音量增大: [CMD:volume_control]up[/CMD]
- 音量减小: [CMD:volume_control]down[/CMD]
- 静音切换: [CMD:volume_control]mute[/CMD]
- 系统信息: [CMD:system_info][/CMD]
- 锁定屏幕: [CMD:lock_screen][/CMD]
- 终止进程: [CMD:kill_process]进程名[/CMD]
- 查看进程: [CMD:get_processes]筛选关键词(可选)[/CMD]
- 模拟按键: [CMD:press_keys]组合键如 ctrl+c[/CMD]
- 输入文字: [CMD:type_text]要输入的文字[/CMD]

## 规则:
- 当用户请求上述操作时，必须输出对应 CMD 格式
- 每个回复只能包含最多一个 CMD 指令
- 如果用户只是闲聊，正常回复即可
- 回复要简洁，不要长篇大论
- 用户说"我的电脑""这台电脑"就是在说他们的电脑

当前时间: {current_time}"""


# ==================== 意图识别 & AI 对话 ====================

def call_ai(session_id: str, user_message: str, model: str = None) -> str:
    """调用 AI 模型进行对话（支持 DeepSeek + 本地 Ollama）"""
    if session_id not in conversations:
        conversations[session_id] = []

    history = conversations[session_id]

    # 保留最近 20 轮
    if len(history) > 40:
        history = history[-40:]

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
        }
    ] + history + [{"role": "user", "content": user_message}]

    result = model_router.chat(messages=messages, model=model)
    reply = result["content"]

    # 保存历史
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply})
    conversations[session_id] = history

    if result["model"] != DEEPSEEK_MODEL:
        print(f"[AI] 使用模型: {result['model']}")

    return reply


# 保留旧函数名兼容
def call_deepseek(session_id: str, user_message: str) -> str:
    return call_ai(session_id, user_message)


def parse_commands(text: str) -> list:
    """从 AI 回复中提取 CMD 指令"""
    pattern = r"\[CMD:(\w+)\](.*?)\[/CMD\]"
    return re.findall(pattern, text, re.DOTALL)


def clean_reply(text: str) -> str:
    """移除回复中的 CMD 标签"""
    return re.sub(r"\[CMD:\w+\].*?\[/CMD\]", "", text, flags=re.DOTALL).strip()


def process_user_message(session_id: str, message: str, source: str = "unknown") -> dict:
    """
    处理用户消息的统一入口：调用 AI → 解析指令 → 分派任务
    返回 {"reply": str, "command": dict|None, "task_id": str|None}
    """
    try:
        reply = call_deepseek(session_id, message)
        commands = parse_commands(reply)
        clean = clean_reply(reply)

        cmd_info = None
        task_id = None
        if commands:
            cmd_type, cmd_params = commands[0]
            cmd_info = {"type": cmd_type, "params": cmd_params.strip()}

            # 推送到 Redis 队列
            task_id = queue.push_task({
                "command": cmd_type,
                "params": cmd_params.strip(),
                "session_id": session_id,
                "source": source,
            })

            # 通过 WebSocket 广播给所有 Agent
            socketio.emit("agent_command", {
                "task_id": task_id,
                "command": cmd_type,
                "params": cmd_params.strip(),
            }, room="agents")

        return {
            "reply": clean,
            "command": cmd_info,
            "task_id": task_id,
            "success": True,
        }
    except Exception as e:
        return {
            "reply": f"[AI服务暂时不可用] {e}",
            "command": None,
            "task_id": None,
            "success": False,
        }


# ==================== 消息队列 Worker 线程 ====================

def message_worker():
    """后台 Worker：从队列取任务 → 通过 WebSocket 发给 Agent（容错版）"""
    print("[Worker] 消息队列 Worker 已启动")
    while True:
        try:
            task = queue.blocking_pop_task(timeout=5)
            if task:
                print(f"[Worker] 分发任务 {task.get('task_id')}: {task.get('command')}")
                socketio.emit("agent_command", {
                    "task_id": task.get("task_id"),
                    "command": task.get("command"),
                    "params": task.get("params"),
                }, room="agents")
        except Exception as e:
            print(f"[Worker] 异常({type(e).__name__}): {e}，继续运行...")
            time.sleep(3)


# ==================== 待回复消息发送线程 ====================

def reply_sender():
    """定期检查待回复队列，通过 WebSocket 广播"""
    print("[Reply] 回复发送器已启动")
    while True:
        try:
            with replies_lock:
                if pending_replies:
                    reply_data = pending_replies.pop(0)
                    print(f"[Reply] 回复用户: {reply_data.get('reply', '')[:50]}...")
                    # 广播给所有 Web 客户端
                    socketio.emit("brain_reply", {
                        "reply": reply_data.get("reply", ""),
                        "command": reply_data.get("command"),
                        "task_id": reply_data.get("task_id"),
                    })
        except Exception as e:
            print(f"[Reply] 异常({type(e).__name__}): {e}")
        time.sleep(1)


# ==================== HTTP 路由 ====================

# --- Web 界面 ---

MOBILE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>电脑遥控器</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        :root {
            --bg: #0f0f0f;
            --card: #1a1a1a;
            --card2: #222;
            --accent: #4a9eff;
            --accent2: #6c5ce7;
            --green: #00d68f;
            --red: #ff6b6b;
            --yellow: #ffd43b;
            --text: #e8e8e8;
            --text2: #999;
            --radius: 16px;
            --safe-bottom: env(safe-area-inset-bottom, 16px);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        html { height: 100%; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100%;
            -webkit-tap-highlight-color: transparent;
            -webkit-font-smoothing: antialiased;
            user-select: none;
            -webkit-user-select: none;
        }
        .app {
            max-width: 480px;
            margin: 0 auto;
            padding: 16px;
            padding-bottom: calc(80px + var(--safe-bottom));
        }

        /* 头部 */
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 0 16px;
        }
        .header-left { display:flex; align-items:center; gap:10px; }
        .logo {
            width: 38px; height: 38px;
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            border-radius: 11px;
            display: flex; align-items: center; justify-content: center;
            font-size: 20px;
        }
        .title { font-size: 18px; font-weight: 700; }
        .status-dot {
            width: 10px; height: 10px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 8px rgba(0,214,143,0.5);
            transition: background .3s;
        }
        .status-dot.offline { background: var(--red); box-shadow: 0 0 8px rgba(255,107,107,0.5); }

        /* 状态栏 */
        .status-bar {
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
        }
        .stat-item {
            flex: 1;
            background: var(--card);
            border-radius: var(--radius);
            padding: 12px;
            text-align: center;
        }
        .stat-value { font-size: 22px; font-weight: 700; }
        .stat-label { font-size: 11px; color: var(--text2); margin-top: 2px; }
        .stat-value.online { color: var(--green); }
        .stat-value.warn { color: var(--yellow); }

        /* 截图区 */
        .screenshot-section {
            background: var(--card);
            border-radius: var(--radius);
            padding: 6px;
            margin-bottom: 12px;
            position: relative;
            overflow: hidden;
            aspect-ratio: 16/10;
        }
        .screenshot-img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            border-radius: 10px;
            display: none;
            background: #000;
        }
        .screenshot-placeholder {
            color: var(--text2);
            font-size: 14px;
            text-align: center;
            position: absolute;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            width: 100%;
        }
        .screenshot-placeholder .icon { font-size: 40px; display:block; margin-bottom:8px; }
        .screenshot-actions {
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
        }
        /* 自动刷新开关 */
        .auto-refresh-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: var(--card);
            border-radius: var(--radius);
            padding: 10px 14px;
            margin-bottom: 12px;
        }
        .auto-refresh-row label {
            font-size: 13px;
            color: var(--text);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .switch {
            position: relative;
            width: 44px; height: 24px;
        }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0; left: 0; right: 0; bottom: 0;
            background: var(--card2);
            border-radius: 24px;
            transition: .3s;
        }
        .slider:before {
            content: "";
            position: absolute;
            height: 18px; width: 18px;
            left: 3px; bottom: 3px;
            background: #666;
            border-radius: 50%;
            transition: .3s;
        }
        input:checked + .slider { background: var(--accent); }
        input:checked + .slider:before {
            transform: translateX(20px);
            background: #fff;
        }

        /* 按钮通用 */
        .btn {
            border: none;
            border-radius: 12px;
            padding: 12px 16px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all .15s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            font-family: inherit;
            white-space: nowrap;
        }
        .btn:active { transform: scale(0.96); opacity: 0.85; }
        .btn-primary {
            flex: 1;
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            color: #fff;
            font-size: 15px;
            padding: 14px;
        }
        .btn-secondary {
            background: var(--card2);
            color: var(--text);
        }
        .btn-danger { background: rgba(255,107,107,0.2); color: var(--red); }
        .btn-small {
            padding: 8px 12px;
            font-size: 12px;
            border-radius: 8px;
        }

        /* 快捷操作网格 */
        .section-title {
            font-size: 13px;
            color: var(--text2);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 12px 0 8px;
            padding-left: 4px;
        }
        .quick-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }
        .quick-btn {
            background: var(--card);
            border: none;
            border-radius: var(--radius);
            padding: 14px 8px;
            color: var(--text);
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
            transition: all .15s;
            font-family: inherit;
        }
        .quick-btn:active { background: var(--card2); transform: scale(0.95); }
        .quick-btn .icon { font-size: 22px; }

        /* 音量控制 */
        .volume-row {
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
        }
        .volume-row .btn { flex:1; }

        /* AI 对话 */
        .chat-section {
            background: var(--card);
            border-radius: var(--radius);
            padding: 12px;
            margin-bottom: 12px;
        }
        .chat-messages {
            max-height: 180px;
            overflow-y: auto;
            margin-bottom: 10px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .chat-msg {
            padding: 8px 12px;
            border-radius: 10px;
            font-size: 13px;
            line-height: 1.4;
            max-width: 85%;
        }
        .chat-msg.user {
            align-self: flex-end;
            background: var(--accent);
            color: #fff;
        }
        .chat-msg.bot {
            align-self: flex-start;
            background: var(--card2);
        }
        .chat-input-row {
            display: flex;
            gap: 8px;
        }
        .chat-input-row input {
            flex: 1;
            background: var(--card2);
            border: none;
            border-radius: 10px;
            padding: 10px 14px;
            color: var(--text);
            font-size: 14px;
            outline: none;
            font-family: inherit;
        }
        .chat-input-row button {
            background: var(--accent);
            border: none;
            border-radius: 10px;
            padding: 10px 16px;
            color: #fff;
            font-weight: 600;
            cursor: pointer;
            font-family: inherit;
        }

        /* Toast */
        .toast {
            position: fixed;
            bottom: 100px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--card2);
            color: var(--text);
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
            z-index: 999;
            opacity: 0;
            transition: opacity .2s;
            pointer-events: none;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
        }
        .toast.show { opacity: 1; }
        .toast.success { background: rgba(0,214,143,0.2); color: var(--green); }
        .toast.error { background: rgba(255,107,107,0.2); color: var(--red); }

        /* Loading spinner */
        .spinner {
            width: 20px; height: 20px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: #fff;
            border-radius: 50%;
            animation: spin .6s linear infinite;
            display: inline-block;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* 全屏截图模态框 */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.95);
            z-index: 2000;
            justify-content: center;
            align-items: center;
            flex-direction: column;
        }
        .modal-overlay.show { display: flex; }
        .modal-overlay img {
            max-width: 100%;
            max-height: calc(100vh - 80px);
            object-fit: contain;
        }
        .modal-close {
            position: absolute;
            top: 15px; right: 15px;
            background: rgba(255,255,255,0.15);
            border: none;
            color: #fff;
            width: 36px; height: 36px;
            border-radius: 50%;
            font-size: 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        /* 刷新指示器 */
        .refresh-indicator {
            position: absolute;
            top: 8px; right: 8px;
            background: rgba(0,0,0,0.6);
            color: #fff;
            padding: 3px 8px;
            border-radius: 10px;
            font-size: 11px;
            display: none;
            align-items: center;
            gap: 4px;
        }
        .refresh-indicator.show { display: flex; }

        /* 截图时间戳 */
        .screenshot-time {
            position: absolute;
            bottom: 8px; left: 8px;
            background: rgba(0,0,0,0.6);
            color: rgba(255,255,255,0.7);
            padding: 2px 8px;
            border-radius: 8px;
            font-size: 10px;
            display: none;
        }
        .screenshot-time.show { display: block; }
    </style>
</head>
<body>
    <div class="app">
        <!-- 头部 -->
        <div class="header">
            <div class="header-left">
                <div class="logo">&#x1F4BB;</div>
                <div>
                    <div class="title">电脑遥控器</div>
                    <div style="font-size:11px;color:var(--text2)" id="agentName">等待连接...</div>
                </div>
            </div>
            <div class="status-dot" id="statusDot"></div>
        </div>

        <!-- 状态条 -->
        <div class="status-bar">
            <div class="stat-item">
                <div class="stat-value" id="cpuVal">--</div>
                <div class="stat-label">CPU</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="memVal">--</div>
                <div class="stat-label">内存</div>
            </div>
            <div class="stat-item">
                <div class="stat-value online" id="agentCount">0</div>
                <div class="stat-label">在线设备</div>
            </div>
        </div>

        <!-- 截图预览（实时） -->
        <div class="screenshot-section" id="screenshotBox" onclick="openFullscreen()">
            <img class="screenshot-img" id="screenshotImg" alt="电脑屏幕" />
            <div class="screenshot-placeholder" id="screenshotPlaceholder">
                <span class="icon">&#x1F4F7;</span>
                点击下方按钮截取屏幕<br><small>开启自动刷新可实时显示</small>
            </div>
            <div class="refresh-indicator" id="refreshIndicator">
                <span class="spinner" style="width:12px;height:12px;border-width:1.5px;"></span>
                <span id="refreshText">刷新中</span>
            </div>
            <div class="screenshot-time" id="screenshotTime"></div>
        </div>

        <div class="screenshot-actions">
            <button class="btn btn-primary" onclick="takeScreenshot(event)" id="screenshotBtn">
                &#x1F4F8; 截取屏幕
            </button>
            <button class="btn btn-secondary btn-small" onclick="takeScreenshot(event)" id="refreshBtn">&#x1F504;</button>
        </div>

        <!-- 自动刷新开关 -->
        <div class="auto-refresh-row">
            <label>&#x1F504; 实时刷新
                <span style="font-size:11px;color:var(--text2)" id="intervalLabel">(每3秒)</span>
            </label>
            <label class="switch">
                <input type="checkbox" id="autoRefreshToggle" onchange="toggleAutoRefresh()">
                <span class="slider"></span>
            </label>
        </div>

        <!-- 快捷操作 -->
        <div class="section-title">快捷操作</div>
        <div class="quick-grid">
            <button class="quick-btn" onclick="doAction('lock_screen')">
                <span class="icon">&#x1F512;</span>锁屏
            </button>
            <button class="quick-btn" onclick="doAction('get_processes')">
                <span class="icon">&#x1F4CB;</span>进程
            </button>
            <button class="quick-btn" onclick="doAction('system_info')">
                <span class="icon">&#x1F4CA;</span>系统信息
            </button>
            <button class="quick-btn" onclick="doAction('run_command', 'notepad')">
                <span class="icon">&#x1F4DD;</span>记事本
            </button>
            <button class="quick-btn" onclick="doAction('run_command', 'calc')">
                <span class="icon">&#x1F5A9;</span>计算器
            </button>
            <button class="quick-btn" onclick="doAction('run_command', 'cmd')">
                <span class="icon">&#x2328;</span>命令行
            </button>
        </div>

        <!-- 音量控制 -->
        <div class="section-title">音量</div>
        <div class="volume-row">
            <button class="btn btn-secondary" onclick="doAction('volume_control','down')">&#x1F509; 减小</button>
            <button class="btn btn-secondary" onclick="doAction('volume_control','mute')">&#x1F507; 静音</button>
            <button class="btn btn-secondary" onclick="doAction('volume_control','up')">&#x1F50A; 增大</button>
        </div>

        <!-- AI 对话 -->
        <div class="section-title">AI 对话</div>
        <div class="chat-section">
            <div class="chat-messages" id="chatMessages">
                <div class="chat-msg bot">你好！我是你的电脑助手。你可以直接说"打开百度"或"截屏"来指挥电脑。</div>
            </div>
            <div class="chat-input-row">
                <input type="text" id="chatInput" placeholder="输入指令或问题..."
                       onkeydown="if(event.key==='Enter') sendChat()">
                <button onclick="sendChat()">发送</button>
            </div>
        </div>

        <!-- Toast -->
        <div class="toast" id="toast"></div>
    </div>

    <!-- 全屏模态框 -->
    <div class="modal-overlay" id="fullscreenModal" onclick="closeFullscreen()">
        <button class="modal-close">&times;</button>
        <img id="fullscreenImg" alt="全屏截图" />
        <div style="color:#888;margin-top:10px;font-size:12px;">点击空白处关闭</div>
    </div>

    <script>
        const socket = io();
        const sessionId = 'mobile_' + Date.now();
        let currentScreenshot = null;
        let agentOnline = false;
        let autoRefreshTimer = null;
        let isRefreshing = false;

        // Socket 事件
        socket.on('connect', () => {
            socket.emit('register', { type: 'web', session_id: sessionId });
            refreshStatus();
        });

        socket.on('agent_update', (data) => {
            const agents = data.agents || [];
            document.getElementById('agentCount').textContent = agents.length;
            const dot = document.getElementById('statusDot');
            agentOnline = agents.length > 0;
            if (agentOnline) {
                dot.classList.remove('offline');
                document.getElementById('agentName').textContent = agents[0]?.name || '在线';
            } else {
                dot.classList.add('offline');
                document.getElementById('agentName').textContent = '无设备在线';
            }
        });

        // 接收实时截图推送（Socket.IO）
        socket.on('screenshot_update', (data) => {
            showScreenshot(data.image);
        });

        // 截图结果中也可能包含 base64
        socket.on('command_result', (data) => {
            if (data.command === 'screenshot' && data.result && data.result.startsWith('BASE64_JPEG:')) {
                const b64 = data.result.substring(12);
                showScreenshot(b64);
            } else if (!data.command || data.command !== 'screenshot') {
                showToast((data.success ? 'OK' : 'X') + ' ' + (data.result || '').substring(0, 60), data.success);
            }
        });

        // 显示截图
        function showScreenshot(base64Data) {
            if (!base64Data) return;
            currentScreenshot = base64Data;
            const img = document.getElementById('screenshotImg');
            const ph = document.getElementById('screenshotPlaceholder');
            img.src = 'data:image/jpeg;base64,' + base64Data;
            img.style.display = 'block';
            ph.style.display = 'none';

            // 更新时间戳
            const now = new Date();
            document.getElementById('screenshotTime').textContent =
                now.getHours().toString().padStart(2,'0') + ':' +
                now.getMinutes().toString().padStart(2,'0') + ':' +
                now.getSeconds().toString().padStart(2,'0');
            document.getElementById('screenshotTime').classList.add('show');

            hideRefreshIndicator();
        }

        // 截图功能
        async function takeScreenshot(e) {
            if (e) e.stopPropagation();
            if (!agentOnline) {
                showToast('设备不在线', false);
                return;
            }
            if (isRefreshing) return;
            isRefreshing = true;
            showRefreshIndicator();

            try {
                // 触发 Agent 截图
                await fetch('/api/screenshot/trigger', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: sessionId })
                });
                showToast('已发送截图指令', true);
            } catch(err) {
                showToast('网络错误: ' + err.message, false);
                hideRefreshIndicator();
            }

            // 等待结果（通过 Socket 推送会自动更新，这里做超时兜底）
            setTimeout(() => {
                isRefreshing = false;
                hideRefreshIndicator();
            }, 8000);
        }

        function showRefreshIndicator() {
            document.getElementById('refreshIndicator').classList.add('show');
        }

        function hideRefreshIndicator() {
            document.getElementById('refreshIndicator').classList.remove('show');
        }

        // 自动刷新切换
        function toggleAutoRefresh() {
            const enabled = document.getElementById('autoRefreshToggle').checked;
            if (enabled) {
                startAutoRefresh();
                showToast('已开启实时刷新', true);
            } else {
                stopAutoRefresh();
                showToast('已关闭实时刷新');
            }
        }

        function startAutoRefresh() {
            stopAutoRefresh(); // 先清理旧的
            if (!agentOnline) {
                document.getElementById('autoRefreshToggle').checked = false;
                showToast('设备不在线，无法自动刷新', false);
                return;
            }
            // 每 3 秒触发一次截图
            autoRefreshTimer = setInterval(() => {
                if (!isRefreshing && agentOnline) {
                    isRefreshing = true;
                    showRefreshIndicator();
                    fetch('/api/screenshot/trigger', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: sessionId })
                    }).catch(() => {});
                    setTimeout(() => {
                        isRefreshing = false;
                        hideRefreshIndicator();
                    }, 2500);
                }
            }, 3000);
        }

        function stopAutoRefresh() {
            if (autoRefreshTimer) {
                clearInterval(autoRefreshTimer);
                autoRefreshTimer = null;
            }
        }

        // 全屏查看
        function openFullscreen() {
            if (!currentScreenshot) return;
            const modal = document.getElementById('fullscreenModal');
            document.getElementById('fullscreenImg').src = 'data:image/jpeg;base64,' + currentScreenshot;
            modal.classList.add('show');
        }

        function closeFullscreen() {
            document.getElementById('fullscreenModal').classList.remove('show');
        }

        // 快捷操作
        async function doAction(command, params) {
            params = params || '';
            if (!agentOnline) { showToast('设备不在线', false); return; }
            showToast('发送指令: ' + command);
            try {
                const resp = await fetch('/api/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command, params, session_id: sessionId })
                });
                const data = await resp.json();

                let result = null;
                for (let i = 0; i < 15; i++) {
                    await sleep(1000);
                    const r = await fetch('/api/task/' + data.task_id);
                    const d = await r.json();
                    if (d.status === 'completed') { result = d; break; }
                }

                if (result) {
                    const msg = result.result ? result.result.substring(0, 200) : '完成';
                    showToast((result.success ? 'OK ' : 'X ') + msg, result.success);
                    if (['system_info', 'get_processes'].includes(command)) {
                        addChatMessage('bot', msg);
                    }
                }
            } catch(e) {
                showToast('错误: ' + e.message, false);
            }
        }

        // AI 对话
        async function sendChat() {
            const input = document.getElementById('chatInput');
            const text = input.value.trim();
            if (!text) return;

            addChatMessage('user', text);
            input.value = '';

            try {
                const resp = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, session_id: sessionId })
                });
                const data = await resp.json();
                addChatMessage('bot', data.reply || '(无回复)');
                if (data.task_id) { pollAndShowResult(data.task_id); }
            } catch(e) {
                addChatMessage('bot', '错误: ' + e.message);
            }
        }

        async function pollAndShowResult(taskId) {
            for (let i = 0; i < 30; i++) {
                await sleep(1000);
                const r = await fetch('/api/task/' + taskId);
                const d = await r.json();
                if (d.status === 'completed') {
                    const icon = d.success ? 'OK' : 'X';
                    // 检查是否有截图数据
                    if (d.screenshot) {
                        showScreenshot(d.screenshot);
                        addChatMessage('bot', '[OK] 截图已完成');
                    } else {
                        addChatMessage('bot', '[' + icon + '] ' + (d.result || '').substring(0, 300));
                    }
                    return;
                }
            }
            addChatMessage('bot', '(执行超时)');
        }

        function addChatMessage(role, text) {
            const container = document.getElementById('chatMessages');
            const div = document.createElement('div');
            div.className = 'chat-msg ' + role;
            div.textContent = text;
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }

        // 刷新状态
        async function refreshStatus() {
            try {
                const resp = await fetch('/api/health');
                const data = await resp.json();
                document.getElementById('agentCount').textContent = data.agents;
                const dot = document.getElementById('statusDot');
                agentOnline = data.agents > 0;
                if (agentOnline) dot.classList.remove('offline');
                else dot.classList.add('offline');

                // 如果自动刷新开着但设备离线了，关掉自动刷新
                if (!agentOnline && document.getElementById('autoRefreshToggle').checked) {
                    stopAutoRefresh();
                    document.getElementById('autoRefreshToggle').checked = false;
                }
            } catch(e) {}
        }

        // Toast
        function showToast(msg, success) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.className = 'toast ' + (success === true ? 'success' : success === false ? 'error' : '');
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 2000);
        }

        function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

        // 启动时刷新
        refreshStatus();
        setInterval(refreshStatus, 30000);

        // 页面不可见时停止自动刷新节省流量
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && autoRefreshTimer) {
                stopAutoRefresh();
                const wasOn = document.getElementById('autoRefreshToggle').checked;
                if (wasOn) {
                    document.getElementById('autoRefreshToggle').dataset.wasOn = 'true';
                    document.getElementById('autoRefreshToggle').checked = false;
                }
            } else if (!document.hidden && document.getElementById('autoRefreshToggle').dataset.wasOn === 'true') {
                document.getElementById('autoRefreshToggle').dataset.wasOn = '';
                document.getElementById('autoRefreshToggle').checked = true;
                startAutoRefresh();
            }
        });
    </script>
</body>
</html>"""


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>云端大脑 - Brain</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            background: rgba(255,255,255,0.05);
            padding: 16px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .header h1 {
            font-size: 22px;
            background: linear-gradient(90deg, #00d2ff, #3a7bd5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .status-badge {
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-connected { background: #00c85333; color: #00c853; }
        .status-disconnected { background: #ff174433; color: #ff1744; }
        .main {
            display: flex;
            flex: 1;
            overflow: hidden;
        }
        .sidebar {
            width: 280px;
            background: rgba(255,255,255,0.03);
            border-right: 1px solid rgba(255,255,255,0.08);
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .sidebar h3 {
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #888;
        }
        .agent-card {
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 12px;
            font-size: 13px;
        }
        .agent-card .name { font-weight: 600; color: #00d2ff; }
        .agent-card .info { color: #999; margin-top: 4px; font-size: 11px; }
        .stats {
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 12px;
            font-size: 13px;
        }
        .stats .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
        }
        .chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
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
            line-height: 1.5;
            font-size: 14px;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .msg.user {
            align-self: flex-end;
            background: linear-gradient(135deg, #3a7bd5, #00d2ff);
            color: #fff;
            border-bottom-right-radius: 4px;
        }
        .msg.assistant {
            align-self: flex-start;
            background: rgba(255,255,255,0.08);
            border-bottom-left-radius: 4px;
        }
        .msg.system {
            align-self: center;
            background: rgba(255,255,255,0.04);
            color: #888;
            font-size: 12px;
            padding: 6px 14px;
            border-radius: 8px;
        }
        .msg .cmd-tag {
            display: inline-block;
            background: #00c85333;
            color: #00c853;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            margin-top: 6px;
        }
        .input-area {
            padding: 16px 20px;
            background: rgba(255,255,255,0.03);
            border-top: 1px solid rgba(255,255,255,0.08);
            display: flex;
            gap: 10px;
        }
        .input-area input {
            flex: 1;
            padding: 12px 16px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            color: #e0e0e0;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }
        .input-area input:focus { border-color: #3a7bd5; }
        .input-area button {
            padding: 12px 20px;
            background: linear-gradient(135deg, #3a7bd5, #00d2ff);
            border: none;
            border-radius: 10px;
            color: #fff;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .input-area button:hover { opacity: 0.9; }
        .input-area button:disabled { opacity: 0.5; cursor: not-allowed; }
    </style>
</head>
<body>
    <div class="header">
        <h1>云端大脑 Brain</h1>
        <div>
            <span class="status-badge" id="agentStatus">无 Agent 连接</span>
        </div>
    </div>
    <div class="main">
        <div class="sidebar">
            <h3>已连接 Agent</h3>
            <div id="agentList">
                <div class="agent-card" style="color:#888;">等待 Agent 连接...</div>
            </div>
            <h3>系统状态</h3>
            <div class="stats">
                <div class="stat-row"><span>Redis</span><span id="redisStatus">-</span></div>
                <div class="stat-row"><span>队列任务</span><span id="queueCount">0</span></div>
                <div class="stat-row"><span>活跃会话</span><span id="sessionCount">0</span></div>
            </div>
        </div>
        <div class="chat-area">
            <div class="messages" id="messages">
                <div class="msg system">欢迎使用云端大脑！输入消息与 AI 对话，或发送指令给本地 Agent 执行。</div>
            </div>
            <div class="input-area">
                <input type="text" id="input" placeholder="输入消息或指令..." autofocus
                       onkeydown="if(event.key==='Enter') sendMessage()">
                <button id="sendBtn" onclick="sendMessage()">发送</button>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        const sessionId = 'web_' + Date.now();

        socket.on('connect', () => {
            addMessage('system', '已连接到云端大脑');
            socket.emit('register', { type: 'web', session_id: sessionId });
        });

        socket.on('disconnect', () => {
            addMessage('system', '连接已断开');
        });

        socket.on('agent_update', (data) => {
            updateAgentList(data.agents);
            updateStats(data.stats);
        });

        socket.on('brain_reply', (data) => {
            addMessage('assistant', data.reply, data.command);
        });

        socket.on('command_result', (data) => {
            const text = `[${data.command}] ${data.result}`;
            addMessage('system', text);
        });

        function sendMessage() {
            const input = document.getElementById('input');
            const text = input.value.trim();
            if (!text) return;

            addMessage('user', text);
            input.value = '';
            document.getElementById('sendBtn').disabled = true;

            socket.emit('brain_message', {
                session_id: sessionId,
                message: text,
            });
        }

        socket.on('message_done', () => {
            document.getElementById('sendBtn').disabled = false;
            document.getElementById('input').focus();
        });

        function addMessage(role, text, cmd) {
            const container = document.getElementById('messages');
            const div = document.createElement('div');
            div.className = 'msg ' + role;
            div.textContent = text;
            if (cmd) {
                const tag = document.createElement('span');
                tag.className = 'cmd-tag';
                tag.textContent = '指令: ' + cmd.type;
                div.appendChild(document.createElement('br'));
                div.appendChild(tag);
            }
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }

        function updateAgentList(agents) {
            const container = document.getElementById('agentList');
            const badge = document.getElementById('agentStatus');

            if (!agents || agents.length === 0) {
                container.innerHTML = '<div class="agent-card" style="color:#888;">无 Agent 连接</div>';
                badge.textContent = '无 Agent 连接';
                badge.className = 'status-badge status-disconnected';
                return;
            }

            badge.textContent = agents.length + ' Agent 在线';
            badge.className = 'status-badge status-connected';

            container.innerHTML = agents.map(a =>
                '<div class="agent-card">' +
                '<div class="name">' + a.name + '</div>' +
                '<div class="info">ID: ' + a.id + ' | ' + a.status + '</div>' +
                '</div>'
            ).join('');
        }

        function updateStats(stats) {
            document.getElementById('redisStatus').textContent = stats.redis ? '已连接' : '内存模式';
            document.getElementById('queueCount').textContent = stats.queue_length;
            document.getElementById('sessionCount').textContent = stats.sessions;
        }
    </script>
</body>
</html>"""


@app.route("/")
def index():
    """Web 控制台首页"""
    return render_template_string(INDEX_HTML)


@app.route("/mobile")
def mobile():
    """移动端遥控面板"""
    return render_template_string(MOBILE_HTML)


@app.route("/api/health")
def health():
    """健康检查接口"""
    return jsonify({
        "status": "ok",
        "time": datetime.now().isoformat(),
        "agents": len(connected_agents),
        "redis": queue.is_connected,
        "queue_length": queue.get_queue_length(),
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """HTTP API 对话接口"""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "缺少 message 字段"}), 400

    session_id = data.get("session_id", "api_default")
    message = data["message"]

    try:
        result = process_user_message(session_id, message, source="api")
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/task/<task_id>")
def api_task_result(task_id):
    """查询任务执行结果"""
    result = queue.get_result(task_id)
    if result:
        return jsonify(result)
    return jsonify({"status": "pending", "task_id": task_id})


@app.route("/api/action", methods=["POST"])
def api_action():
    """直接发送指令给 Agent（跳过 AI，直达执行）"""
    data = request.get_json()
    if not data or "command" not in data:
        return jsonify({"error": "缺少 command 字段"}), 400

    command = data["command"]
    params = data.get("params", "")
    session_id = data.get("session_id", "mobile_direct")

    task_id = queue.push_task({
        "command": command,
        "params": params,
        "session_id": session_id,
        "source": "mobile",
    })

    socketio.emit("agent_command", {
        "task_id": task_id,
        "command": command,
        "params": params,
    }, room="agents")

    return jsonify({"task_id": task_id, "command": command, "status": "sent"})


@app.route("/api/models")
def api_models():
    """查询模型状态"""
    return jsonify(model_router.get_status())


@app.route("/api/agents")
def api_agents():
    """查询已连接 Agent 列表"""
    with agents_lock:
        agents_list = [
            {
                "id": info["id"],
                "name": info["name"],
                "status": info["status"],
                "hostname": info.get("hostname", ""),
                "connected_at": info.get("connected_at", ""),
                "last_heartbeat": info.get("last_heartbeat", ""),
            }
            for info in connected_agents.values()
        ]
    return jsonify({"agents": agents_list, "count": len(agents_list)})


@app.route("/api/screenshot")
def api_screenshot():
    """获取最新截图的 base64 数据"""
    with screenshot_lock:
        if latest_screenshot:
            return jsonify({"image": latest_screenshot, "has_image": True})
    return jsonify({"image": None, "has_image": False})


@app.route("/api/screenshot/trigger", methods=["POST"])
def api_screenshot_trigger():
    """触发 Agent 截图并返回结果（同步等待）"""
    data = request.get_json() or {}
    task_id = queue.push_task({
        "command": "screenshot",
        "params": "",
        "session_id": data.get("session_id", "screenshot_trigger"),
        "source": "mobile_screenshot",
    })
    socketio.emit("agent_command", {
        "task_id": task_id,
        "command": "screenshot",
        "params": "",
    }, room="agents")
    return jsonify({"task_id": task_id, "status": "sent"})


# ==================== QQ / 外部 Webhook 回调 ====================

@app.route("/webhook/qq", methods=["POST"])
def webhook_qq():
    """QQ Bot 回调（示例）"""
    data = request.get_json()
    if not data:
        return jsonify({"code": 0})

    user_message = data.get("message", "") or data.get("raw_message", "")
    user_id = data.get("user_id", "qq_unknown")
    session_id = f"qq_{user_id}"

    if not user_message.strip():
        return jsonify({"code": 0})

    print(f"[QQ] 收到消息: {user_message[:50]}...")

    # 在后台线程处理，避免阻塞 HTTP 响应
    def handle():
        result = process_user_message(session_id, user_message, source="qq")
        # 将回复放入待发送队列
        with replies_lock:
            pending_replies.append({
                "session_id": session_id,
                "reply": result["reply"],
                "command": result["command"],
                "task_id": result["task_id"],
                "user_id": user_id,
            })

    threading.Thread(target=handle, daemon=True).start()
    return jsonify({"code": 0})


@app.route("/webhook/custom", methods=["POST"])
def webhook_custom():
    """通用外部 Webhook 回调"""
    data = request.get_json()
    if not data:
        return jsonify({"code": 0, "error": "no data"})

    user_message = data.get("message", "") or data.get("text", "")
    user_id = data.get("user_id", data.get("from", "custom_unknown"))
    session_id = f"custom_{user_id}"

    if not user_message.strip():
        return jsonify({"code": 0})

    print(f"[Webhook] 收到消息: {user_message[:50]}...")

    def handle():
        result = process_user_message(session_id, user_message, source="webhook")
        with replies_lock:
            pending_replies.append({
                "session_id": session_id,
                "reply": result["reply"],
                "command": result["command"],
                "task_id": result["task_id"],
            })

    threading.Thread(target=handle, daemon=True).start()
    return jsonify({"code": 0})


@app.route("/webhook/wechat", methods=["POST"])
def webhook_wechat():
    """微信回调（企业微信 / 个人微信桥接）"""
    data = request.get_json()
    if not data:
        return jsonify({"code": 0})

    # 使用 wechat_bot 处理（如果已初始化）
    if wechat_bot:
        msg = wechat_bot.process_callback(data)
        user_message = msg.get("text", "")
        user_id = msg.get("user_id", "wx_unknown")
        session_id = f"wx_{user_id}"
    else:
        user_message = data.get("message", "") or data.get("text", "") or data.get("Content", "")
        user_id = data.get("user_id", data.get("FromUserName", "wx_unknown"))
        session_id = f"wx_{user_id}"

    if not user_message.strip():
        return jsonify({"code": 0})

    print(f"[WeChat] 收到消息: {user_message[:50]}...")

    def handle():
        result = process_user_message(session_id, user_message, source="wechat")
        # 尝试通过企业微信机器人回复
        if wechat_bot and wechat_bot.mode == "wecom" and wechat_bot.webhook_url:
            wechat_bot.send_wecom_text(result["reply"])
        else:
            with replies_lock:
                pending_replies.append({
                    "session_id": session_id,
                    "reply": result["reply"],
                    "command": result["command"],
                    "task_id": result["task_id"],
                    "user_id": user_id,
                })

    threading.Thread(target=handle, daemon=True).start()
    return jsonify({"code": 0})


# ==================== WebSocket 事件处理 ====================

@socketio.on("connect")
def handle_connect():
    """客户端连接"""
    print(f"[Socket] 客户端连接: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    """客户端断开"""
    with agents_lock:
        to_remove = [aid for aid, info in connected_agents.items() if info.get("sid") == request.sid]
        for aid in to_remove:
            print(f"[Agent] 离线: {aid}")
            del connected_agents[aid]

    broadcast_agent_update()


@socketio.on("register")
def handle_register(data: dict):
    """客户端注册（Web 界面 或 Agent）"""
    client_type = data.get("type", "web")

    if client_type == "agent":
        agent_id = data.get("agent_id", request.sid[:8])
        agent_name = data.get("name", f"Agent-{agent_id[:4]}")
        with agents_lock:
            connected_agents[agent_id] = {
                "id": agent_id,
                "name": agent_name,
                "sid": request.sid,
                "status": "online",
                "connected_at": datetime.now().isoformat(),
                "hostname": data.get("hostname", "unknown"),
            }
        join_room("agents")
        print(f"[Agent] 上线: {agent_name} ({agent_id})")
        emit("registered", {"agent_id": agent_id, "status": "ok"})

    elif client_type == "web":
        join_room(data.get("session_id", "web"))

    broadcast_agent_update()


@socketio.on("brain_message")
def handle_brain_message(data: dict):
    """Web 界面发送消息给大脑"""
    session_id = data.get("session_id", "default")
    message = data.get("message", "")

    if not message:
        return

    result = process_user_message(session_id, message, source="web")

    emit("brain_reply", {
        "reply": result["reply"],
        "command": result["command"],
    })
    emit("message_done")


@socketio.on("agent_result")
def handle_agent_result(data: dict):
    """Agent 返回指令执行结果"""
    task_id = data.get("task_id", "")
    result_text = data.get("result", "")
    success = data.get("success", True)
    agent_id = data.get("agent_id", "unknown")
    command = data.get("command", "")

    print(f"[结果] 任务 {task_id}: {result_text[:80]}")

    # 如果是截图结果，提取 base64 数据
    screenshot_b64 = None
    if command == "screenshot" and result_text.startswith("BASE64_JPEG:"):
        screenshot_b64 = result_text[len("BASE64_JPEG:"):]
        with screenshot_lock:
            global latest_screenshot
            latest_screenshot = screenshot_b64
        # 通过 Socket 推送截图到所有 Web 客户端
        socketio.emit("screenshot_update", {
            "image": screenshot_b64,
            "timestamp": datetime.now().isoformat(),
        })
        print(f"[截图] 已推送截图数据 ({len(screenshot_b64)} 字符)")

    # 保存到 Redis
    queue.set_result(task_id, {
        "task_id": task_id,
        "result": result_text,
        "success": success,
        "agent_id": agent_id,
        "status": "completed",
        "screenshot": screenshot_b64,  # 附带截图数据
    })

    # 广播结果到 Web 界面
    socketio.emit("command_result", {
        "task_id": task_id,
        "command": command,
        "result": result_text,
        "success": success,
        "agent_id": agent_id,
    })


@socketio.on("agent_capability")
def handle_agent_capability(data: dict):
    """Agent 上报能力信息"""
    agent_id = data.get("agent_id", "")
    if agent_id:
        with agents_lock:
            if agent_id in connected_agents:
                connected_agents[agent_id]["capabilities"] = data
                connected_agents[agent_id]["commands"] = data.get("commands", [])
        print(f"[Agent] {agent_id} 能力: {len(data.get('commands', []))} 种指令")


@socketio.on("agent_heartbeat")
def handle_heartbeat(data: dict):
    """Agent 心跳"""
    agent_id = data.get("agent_id")
    if agent_id:
        with agents_lock:
            if agent_id in connected_agents:
                connected_agents[agent_id]["last_heartbeat"] = datetime.now().isoformat()
    emit("heartbeat_ack", {"time": datetime.now().isoformat()})


def broadcast_agent_update():
    """广播 Agent 状态更新到所有 Web 客户端"""
    with agents_lock:
        agents_list = [
            {
                "id": info["id"],
                "name": info["name"],
                "status": info["status"],
            }
            for info in connected_agents.values()
        ]
    socketio.emit("agent_update", {
        "agents": agents_list,
        "stats": {
            "redis": queue.is_connected,
            "queue_length": queue.get_queue_length(),
            "sessions": len(conversations),
        },
    })


# ==================== 定时广播 ====================

def periodic_broadcast():
    """定期广播状态更新"""
    while True:
        time.sleep(10)
        broadcast_agent_update()


# ==================== 启动 ====================

def main():
    print("=" * 60)
    print("  云端大脑 Brain 启动中...")
    print("=" * 60)
    print(f"  Web 控制台: http://localhost:{PORT}")
    print(f"  API 接口:   http://localhost:{PORT}/api/health")
    print(f"  QQ Webhook: POST http://localhost:{PORT}/webhook/qq")
    print(f"  微信Webhook: POST http://localhost:{PORT}/webhook/wechat")
    print(f"  Telegram:   {'已配置' if TELEGRAM_ENABLED else '未配置 (设置 TELEGRAM_BOT_TOKEN)'}")
    print(f"  Redis:      {'已连接' if queue.is_connected else '内存模式'}")
    print(f"  默认模型:   {DEEPSEEK_MODEL}")
    print("=" * 60)

    # 检查模型状态
    model_status = model_router.get_status()
    for name, info in model_status.items():
        icon = "[OK]" if info["available"] else "[--]"
        print(f"  {icon} {name}: {info['model']} ({info['type']})")

    local_models = model_router.list_local_models()
    if local_models:
        print(f"  本地模型: {', '.join(local_models)}")
    print("=" * 60)

    # 启动后台线程
    threading.Thread(target=periodic_broadcast, daemon=True).start()
    threading.Thread(target=message_worker, daemon=True).start()
    threading.Thread(target=reply_sender, daemon=True).start()

    # 启动 QQ Bot（如果启用）
    if qq_bot:
        def on_qq_message(msg):
            print(f"[QQ] 收到: {msg['text'][:50]}...")
            session_id = f"qq_{msg['user_id']}"
            result = process_user_message(session_id, msg['text'], source="qq")
            # 通过 QQ 回复
            if msg['type'] == 'private':
                qq_bot.send_private_msg(msg['user_id'], result['reply'])
            elif msg.get('group_id'):
                qq_bot.send_group_msg(msg['group_id'], result['reply'])

        qq_bot.on_message = on_qq_message
        qq_bot.start(mode="ws")
        print("[QQ] QQ Bot 已启动")

    # 启动微信 Bot（如果启用）
    if wechat_bot:
        wechat_bot.start()
        print("[WeChat] 微信 Bot 已启动")

    # 启动 Telegram Bot（如果启用）
    if telegram_bot:
        def on_telegram_message(msg):
            """处理 Telegram 消息：发给 AI → 解析指令 → 回复结果"""
            chat_id = msg["chat_id"]
            text = msg["text"]
            session_id = f"tg_{msg['user_id']}"

            if text.startswith("/start"):
                telegram_bot.send_message(chat_id,
                    "🤖 <b>云端大脑已就绪！</b>\n\n"
                    "你可以用自然语言和我对话，比如：\n"
                    "• <code>你好</code> - 闲聊\n"
                    "• <code>截个屏</code> - 电脑截图\n"
                    "• <code>现在几点</code> - 查看时间\n"
                    "• <code>打开百度</code> - 浏览器操作\n"
                    "• <code>系统状态</code> - 查看电脑信息\n"
                    "• <code>查看进程</code> - 电脑进程列表\n\n"
                    "/help - 查看帮助\n"
                    "/status - 系统状态\n"
                    "/agent - 连接的电脑"
                )
                return

            if text.startswith("/help"):
                telegram_bot.send_message(chat_id,
                    "<b>📋 可用指令</b>\n\n"
                    "<b>电脑控制:</b>\n"
                    "• 截个屏 / 截图\n"
                    "• 打开XX程序\n"
                    "• 打开XX网页\n"
                    "• 音量增大/减小/静音\n"
                    "• 锁定屏幕\n"
                    "• 查看进程\n"
                    "• 系统信息\n"
                    "• 输入文字XXX\n"
                    "• 按键 Ctrl+C 等\n\n"
                    "<b>文件操作:</b>\n"
                    "• 查看文件夹XX\n"
                    "• 读取文件XX\n\n"
                    "<b>其他:</b>\n"
                    "• 现在几点\n"
                    "• 执行命令XXX\n\n"
                    "<b>命令:</b>\n"
                    "/start /help /status /agent"
                )
                return

            if text.startswith("/status"):
                from datetime import datetime
                agents_list = list(connected_agents.values())
                status_text = "<b>📊 系统状态</b>\n\n"
                status_text += f"🕐 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                status_text += f"💾 Redis: {'已连接' if queue.is_connected else '内存模式'}\n"
                status_text += f"📋 队列: {queue.get_queue_length()} 个任务\n"
                status_text += f"💬 会话: {len(conversations)} 个\n"
                status_text += f"🖥️ Agent: {len(agents_list)} 台在线\n"
                for a in agents_list:
                    status_text += f"  • {a['name']} ({a['hostname']}) - {a['status']}\n"
                telegram_bot.send_message(chat_id, status_text)
                return

            if text.startswith("/agent"):
                agents_list = list(connected_agents.values())
                if agents_list:
                    text_out = "<b>🖥️ 已连接的电脑</b>\n\n"
                    for i, a in enumerate(agents_list):
                        text_out += f"{i+1}. <b>{a['name']}</b>\n"
                        text_out += f"   主机名: {a.get('hostname', '?')}\n"
                        text_out += f"   状态: {a['status']}\n"
                        cmds = a.get('commands', [])
                        if cmds:
                            text_out += f"   支持指令: {len(cmds)} 种\n"
                        text_out += "\n"
                else:
                    text_out = "⚠️ 当前没有电脑在线"
                telegram_bot.send_message(chat_id, text_out)
                return

            # 正常对话：发给 AI
            telegram_bot.send_typing(chat_id)
            result = process_user_message(session_id, text, source="telegram")

            # 构建回复
            reply = result["reply"]
            if result["command"]:
                reply += f"\n\n<i>🔧 已发送指令: {result['command']['type']}</i>"

            telegram_bot.send_message(chat_id, reply)

            # 如果有指令发送给 Agent，Agent 返回结果后也转发到 Telegram
            if result.get("task_id"):
                def wait_and_reply():
                    for _ in range(30):  # 最多等30秒
                        time.sleep(1)
                        task_result = queue.get_result(result["task_id"])
                        if task_result:
                            status_icon = "✅" if task_result.get("success") else "❌"
                            telegram_bot.send_message(chat_id,
                                f"{status_icon} <b>执行结果</b>\n\n"
                                f"<pre>{task_result.get('result', '')[:3500]}</pre>"
                            )
                            break

                threading.Thread(target=wait_and_reply, daemon=True).start()

        telegram_bot.on_message = on_telegram_message
        telegram_bot.start()
        print("[Telegram] Telegram Bot 已启动")

    # 启动 SocketIO 服务
    socketio.run(
        app,
        host=HOST,
        port=PORT,
        debug=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
