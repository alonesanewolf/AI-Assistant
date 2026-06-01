"""
Telegram Bot 独立版 - 本地运行，通过 HTTP API 调用云端大脑
=============================================================
用途: 国内服务器无法直连 Telegram API，所以 Bot 在本地电脑跑，
      通过 HTTP 调用云端大脑 (brain.py) 的 /api/chat 接口。

使用:
  python telegram_bot_standalone.py

依赖:
  - requests (已有)
  - 本地可直连 Telegram API
"""

import json
import os
import threading
import time
from typing import Callable, Optional

# ==================== 配置 ====================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8898227219:AAHd2KbeaZ_HUbt6H1EaPDmzBLW1dibby6E")
TELEGRAM_API_BASE = "https://api.telegram.org"
BRAIN_API_URL = os.environ.get("BRAIN_URL", "http://122.51.97.86:5000")


class TelegramBotStandalone:
    """独立运行的 Telegram Bot，通过 HTTP 调用云端大脑"""

    def __init__(self, token: str = "", brain_url: str = ""):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.brain_url = brain_url or BRAIN_API_URL
        if not self.token:
            raise ValueError("未设置 TELEGRAM_BOT_TOKEN")

        self.api_url = f"{TELEGRAM_API_BASE}/bot{self.token}"
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0

        # 回调
        self.on_message: Optional[Callable] = None

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

    def _call_brain(self, session_id: str, message: str) -> dict:
        """调用云端大脑 HTTP API"""
        import requests
        try:
            resp = requests.post(
                f"{self.brain_url}/api/chat",
                json={"session_id": session_id, "message": message},
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"reply": f"[云端大脑返回错误: HTTP {resp.status_code}]", "command": None, "task_id": None}
        except Exception as e:
            return {"reply": f"[无法连接云端大脑: {e}]", "command": None, "task_id": None}

    def _poll_task_result(self, task_id: str) -> Optional[dict]:
        """轮询任务结果"""
        import requests
        for _ in range(30):
            time.sleep(1)
            try:
                resp = requests.get(f"{self.brain_url}/api/task/{task_id}", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "completed":
                        return data
            except Exception:
                pass
        return None

    def send_message(self, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
        """发送文本消息"""
        if len(text) > 4000:
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

    def send_typing(self, chat_id: str) -> bool:
        """发送'正在输入'状态"""
        return self._api_call("sendChatAction", {
            "chat_id": chat_id,
            "action": "typing",
        }) is not None

    # ---- 消息处理 ----

    def _process_update(self, update: dict):
        """处理一条 Telegram Update"""
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        user = message.get("from", {})
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "") or message.get("caption", "")

        if not text:
            return

        msg = {
            "type": "private" if chat.get("type") == "private" else "group",
            "chat_id": chat_id,
            "user_id": str(user.get("id", "")),
            "username": user.get("username", ""),
            "first_name": user.get("first_name", ""),
            "nickname": user.get("first_name", "") or user.get("username", "Unknown"),
            "text": text,
            "message_id": message.get("message_id", 0),
            "timestamp": message.get("date", int(time.time())),
        }

        print(f"[Telegram] {msg['nickname']}: {text[:80]}")
        self._dispatch(msg)

    def _dispatch(self, msg: dict):
        """分发消息"""
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception as e:
                print(f"[Telegram] on_message 异常: {e}")

    # ---- 轮询 ----

    def _polling_loop(self):
        """长轮询主循环"""
        print("[Telegram] 开始长轮询...")

        while self._running:
            try:
                updates = self._api_call("getUpdates", {
                    "offset": self._last_update_id + 1,
                    "timeout": 30,
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
            print("[Telegram] 未配置 Token")
            return

        info = self.get_me()
        if info:
            print(f"[Telegram] Bot: @{info.get('username')} ({info.get('first_name')})")
            print(f"[Telegram] 手机搜索 @{info.get('username')} 即可对话")
            print(f"[Telegram] 云端大脑: {self.brain_url}")
        else:
            print("[Telegram] Token 无效或网络不通，请检查")
            return

        self._running = True
        self._thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._thread.start()
        print("[Telegram] Bot 已启动！用手机发消息试试")

    def stop(self):
        """停止 Bot"""
        self._running = False
        print("[Telegram] Bot 已停止")


# ==================== 主程序 ====================

def main():
    bot = TelegramBotStandalone()

    def handle_message(msg):
        chat_id = msg["chat_id"]
        text = msg["text"]
        session_id = f"tg_{msg['user_id']}"

        # 内置命令
        if text.startswith("/start"):
            bot.send_message(chat_id,
                "<b>云端大脑已就绪！</b>\n\n"
                "你可以用自然语言指挥电脑：\n"
                "  <code>截个屏</code> - 电脑截图\n"
                "  <code>现在几点</code> - 查看时间\n"
                "  <code>打开百度</code> - 浏览器操作\n"
                "  <code>系统状态</code> - 查看电脑信息\n"
                "  <code>查看进程</code> - 进程列表\n"
                "  <code>输入文字XXX</code> - 键盘输入\n"
                "  <code>按键 Ctrl+C</code> - 模拟按键\n\n"
                "/help - 帮助\n/status - 系统状态\n/agent - 连接的电脑"
            )
            return

        if text.startswith("/help"):
            bot.send_message(chat_id,
                "<b>支持的操作</b>\n\n"
                "<b>电脑控制:</b>\n"
                "  截屏, 打开XX程序, 打开XX网页,\n"
                "  音量增大/减小/静音, 锁定屏幕,\n"
                "  查看进程, 系统信息, 输入文字, 按键\n\n"
                "<b>文件:</b>\n"
                "  查看文件夹, 读取文件\n\n"
                "/start /help /status /agent"
            )
            return

        if text.startswith("/status") or text.startswith("/agent"):
            import requests
            try:
                resp = requests.get(f"{bot.brain_url}/api/health", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    agents_resp = requests.get(f"{bot.brain_url}/api/agents", timeout=10)
                    agents_data = agents_resp.json() if agents_resp.status_code == 200 else {"agents": []}

                    status_text = "<b>系统状态</b>\n\n"
                    status_text += f"Agent: {data.get('agents', 0)} 台在线\n"
                    status_text += f"Redis: {'已连接' if data.get('redis') else '内存模式'}\n"
                    status_text += f"队列: {data.get('queue_length', 0)} 个任务\n"

                    for a in agents_data.get("agents", []):
                        status_text += f"\n  {a['name']} ({a.get('hostname', '?')}) - {a['status']}"

                    bot.send_message(chat_id, status_text)
                else:
                    bot.send_message(chat_id, f"云端大脑状态异常: HTTP {resp.status_code}")
            except Exception as e:
                bot.send_message(chat_id, f"无法连接云端大脑: {e}")
            return

        # 正常对话：发给云端大脑
        bot.send_typing(chat_id)
        result = bot._call_brain(session_id, text)

        reply = result.get("reply", "[无回复]")
        if result.get("command"):
            reply += f"\n\n<i>已发送指令: {result['command']['type']}</i>"

        bot.send_message(chat_id, reply)

        # 等待 Agent 执行结果
        task_id = result.get("task_id")
        if task_id:
            def wait_result():
                task_result = bot._poll_task_result(task_id)
                if task_result:
                    icon = "OK" if task_result.get("success") else "X"
                    bot.send_message(chat_id,
                        f"<b>[{icon}] 执行结果</b>\n\n"
                        f"<pre>{task_result.get('result', '')[:3500]}</pre>"
                    )
                else:
                    bot.send_message(chat_id, "<i>任务执行超时（Agent 可能离线）</i>")

            threading.Thread(target=wait_result, daemon=True).start()

    bot.on_message = handle_message
    bot.start()

    print("\n" + "=" * 50)
    print("  Telegram Bot 独立版运行中")
    print("  手机打开 Telegram 搜索 Bot 即可对话")
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止...")
        bot.stop()


if __name__ == "__main__":
    main()
