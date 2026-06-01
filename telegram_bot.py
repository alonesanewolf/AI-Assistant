"""
Telegram Bot 适配器 - 手机遥控云端大脑 + 电脑
===============================================
通过 Telegram Bot API 实现手机与云端大脑的双向通信。
手机发指令 → 云端大脑处理 → 转发给本地 Agent 执行 → 结果返回手机。

优势:
  - 手机装 Telegram 即可，无需额外配置
  - API 稳定，不会被封号
  - 支持文字/图片/文件，双向通信
  - 轮询模式不需要公网回调地址

使用步骤:
  1. 在 Telegram 搜索 @BotFather，创建 Bot 获取 Token
  2. 设置环境变量: set TELEGRAM_BOT_TOKEN=你的token
  3. 启动 Brain，Bot 自动运行
  4. 手机打开 Telegram，搜索你的 Bot，发送消息即可
"""

import json
import os
import threading
import time
from typing import Callable, Optional

# ==================== 配置 ====================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramBot:
    """
    Telegram Bot 适配器（长轮询模式）

    用法:
        bot = TelegramBot(token="123456:ABC...")
        bot.on_message = lambda msg: print(msg['text'])
        bot.start()
    """

    def __init__(self, token: str = ""):
        self.token = token or TELEGRAM_BOT_TOKEN
        if not self.token:
            print("[Telegram] 未设置 TELEGRAM_BOT_TOKEN，Bot 不会启动")

        self.api_url = f"{TELEGRAM_API_BASE}/bot{self.token}"
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0

        # 回调
        self.on_message: Optional[Callable] = None  # (msg_dict) -> None
        self._message_handlers: list[Callable] = []

        # 用户状态: 用于等待 Agent 执行结果后回复
        self._pending_tasks: dict = {}  # chat_id -> task_info

        # Bot 信息
        self.bot_info: dict = {}

    # ---- API 调用 ----

    def _api_call(self, method: str, params: dict = None, files: dict = None) -> Optional[dict]:
        """调用 Telegram Bot API"""
        import requests
        url = f"{self.api_url}/{method}"
        try:
            if files:
                resp = requests.post(url, data=params, files=files, timeout=30)
            elif params:
                resp = requests.post(url, json=params, timeout=15)
            else:
                resp = requests.get(url, timeout=15)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("result")
                else:
                    print(f"[Telegram] API 错误: {data.get('description', 'unknown')}")
                    return None
            else:
                print(f"[Telegram] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"[Telegram] 网络错误: {e}")
            return None

    def send_message(self, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
        """发送文本消息"""
        if len(text) > 4000:
            # Telegram 消息长度限制 4096，超长分段发送
            return self._send_long_message(chat_id, text, parse_mode)

        result = self._api_call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        })
        return result is not None

    def _send_long_message(self, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
        """分段发送超长消息"""
        chunks = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > 3800:
                chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)

        success = True
        for i, chunk in enumerate(chunks):
            prefix = f"<i>({i+1}/{len(chunks)})</i>\n" if len(chunks) > 1 else ""
            if not self.send_message(chat_id, prefix + chunk, parse_mode):
                success = False
        return success

    def send_photo(self, chat_id: str, photo_path: str, caption: str = "") -> bool:
        """发送图片"""
        try:
            with open(photo_path, "rb") as f:
                result = self._api_call("sendPhoto",
                    params={"chat_id": chat_id, "caption": caption} if caption else {"chat_id": chat_id},
                    files={"photo": f},
                )
            return result is not None
        except Exception as e:
            print(f"[Telegram] 发送图片失败: {e}")
            return False

    def send_file(self, chat_id: str, file_path: str, caption: str = "") -> bool:
        """发送文件"""
        try:
            with open(file_path, "rb") as f:
                result = self._api_call("sendDocument",
                    params={"chat_id": chat_id, "caption": caption} if caption else {"chat_id": chat_id},
                    files={"document": f},
                )
            return result is not None
        except Exception as e:
            print(f"[Telegram] 发送文件失败: {e}")
            return False

    def send_typing(self, chat_id: str) -> bool:
        """发送'正在输入'状态"""
        return self._api_call("sendChatAction", {
            "chat_id": chat_id,
            "action": "typing",
        }) is not None

    # ---- 消息处理 ----

    def add_handler(self, handler: Callable):
        """添加消息处理器"""
        self._message_handlers.append(handler)

    def _process_update(self, update: dict):
        """处理一条 Telegram Update"""
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        user = message.get("from", {})
        chat_id = str(chat.get("id", ""))

        # 提取文本
        text = message.get("text", "") or message.get("caption", "")

        # 提取图片
        photos = message.get("photo", [])
        has_photo = len(photos) > 0

        # 提取文件
        document = message.get("document")

        if not text and not has_photo and not document:
            return  # 不支持的消息类型（如贴纸、语音等）

        msg = {
            "type": "private" if chat.get("type") == "private" else "group",
            "chat_id": chat_id,
            "user_id": str(user.get("id", "")),
            "username": user.get("username", ""),
            "first_name": user.get("first_name", ""),
            "nickname": user.get("first_name", "") or user.get("username", "未知"),
            "text": text,
            "message_id": message.get("message_id", 0),
            "timestamp": message.get("date", int(time.time())),
            "source": "telegram",
            "has_photo": has_photo,
            "has_document": document is not None,
            "raw_message": message,  # 保留原始消息用于下载文件等
        }

        print(f"[Telegram] 收到消息 from {msg['nickname']}: {text[:80]}")
        self._dispatch(msg)

    def _dispatch(self, msg: dict):
        """分发消息到处理器"""
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception as e:
                print(f"[Telegram] on_message 异常: {e}")

        for handler in self._message_handlers:
            try:
                handler(msg)
            except Exception as e:
                print(f"[Telegram] handler 异常: {e}")

    # ---- 轮询主循环 ----

    def _polling_loop(self):
        """长轮询主循环"""
        print("[Telegram] 开始长轮询...")

        while self._running:
            try:
                updates = self._api_call("getUpdates", {
                    "offset": self._last_update_id + 1,
                    "timeout": 30,  # 长轮询超时
                    "allowed_updates": ["message", "edited_message"],
                })

                if updates:
                    for update in updates:
                        self._last_update_id = max(self._last_update_id, update.get("update_id", 0))
                        try:
                            self._process_update(update)
                        except Exception as e:
                            print(f"[Telegram] 处理 update 异常: {e}")

            except Exception as e:
                print(f"[Telegram] 轮询异常: {e}，5秒后重试...")
                time.sleep(5)

    # ---- 生命周期 ----

    def get_me(self) -> dict:
        """获取 Bot 信息"""
        result = self._api_call("getMe")
        if result:
            self.bot_info = result
        return self.bot_info

    def start(self):
        """启动 Telegram Bot"""
        if not self.token:
            print("[Telegram] 未配置 Token，跳过启动")
            return

        # 获取 Bot 信息
        info = self.get_me()
        if info:
            print(f"[Telegram] Bot 信息: @{info.get('username')} ({info.get('first_name')})")
            print(f"[Telegram] 手机打开 Telegram 搜索 @{info.get('username')} 即可对话")
        else:
            print("[Telegram] 无法获取 Bot 信息，请检查 Token 是否正确")
            return

        self._running = True
        self._thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._thread.start()
        print("[Telegram] Bot 已启动！用手机发消息试试吧")

    def stop(self):
        """停止 Bot"""
        self._running = False
        print("[Telegram] Bot 已停止")


# ==================== 创建指南 ====================

SETUP_GUIDE = """
========================================
  Telegram Bot 创建指南
========================================

1. 手机下载 Telegram（App Store / Google Play）
   注册账号（需要手机号，仅首次验证用）

2. 在 Telegram 中搜索 @BotFather
   发送 /newbot 创建新 Bot
   按提示输入 Bot 名称和用户名（用户名必须以 bot 结尾）

3. 创建成功后 BotFather 会给你一串 Token，格式类似:
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

4. 在服务器上设置环境变量:
   export TELEGRAM_BOT_TOKEN="你的Token"
   或在 Windows:
   set TELEGRAM_BOT_TOKEN=你的Token

5. 重启 Brain，Bot 自动启动

6. 手机打开 Telegram，搜索你创建的 Bot 用户名
   发送 /start 即可开始对话！

命令示例:
  /start   - 开始使用
  /help    - 查看帮助
  /status  - 查看系统状态
  /agent   - 查看已连接的 Agent
  截个屏    - 让电脑截图发到手机
  现在几点  - 查看电脑时间
  打开百度  - 让电脑打开网页
"""


# ==================== 测试 ====================

if __name__ == "__main__":
    print(SETUP_GUIDE)

    token = input("\n请输入你的 Bot Token (回车跳过): ").strip()
    if not token:
        print("未输入 Token，退出")
        exit()

    bot = TelegramBot(token=token)
    bot.on_message = lambda msg: bot.send_message(
        msg['chat_id'],
        f"收到消息: {msg['text']}\n\n"
        f"<i>— 来自 {msg['nickname']}</i>"
    )

    bot.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止...")
        bot.stop()
