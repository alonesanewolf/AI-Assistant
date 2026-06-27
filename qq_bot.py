"""
QQ Bot 适配器 (基于 OneBot v11 协议)
====================================
支持通过 go-cqhttp / NapCatQQ / LLOneBot 等 OneBot 实现接收 QQ 消息。

两种工作模式：
  模式 A - 正向 WebSocket（推荐）: QQ Bot 直连 Brain
  模式 B - HTTP POST 回调: Brain 暴露 /webhook/qq 端点，QQ Bot 推送消息

依赖: pip install websocket-client (模式 A)

OneBot 协议参考: https://github.com/botuniverse/onebot-11
"""

import json
import threading
import time
from typing import Callable, Optional

# ==================== 配置 ====================

# 正向 WebSocket 地址（OneBot 实现监听的地址）
ONEBOT_WS_URL = "ws://localhost:3001"  # go-cqhttp 默认正向 WS 端口

# 反向 HTTP 回调地址
CALLBACK_URL = "http://localhost:5000/webhook/qq"


class QQBot:
    """
    QQ Bot 适配器

    用法:
        bot = QQBot()
        bot.on_message = lambda msg: print(f"收到: {msg['text']}")
        bot.start()  # 启动正向 WebSocket 连接
    """

    def __init__(self, ws_url: str = ONEBOT_WS_URL):
        self.ws_url = ws_url
        self._ws = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.on_message: Optional[Callable] = None  # 消息回调: (msg_dict) -> None
        self.on_event: Optional[Callable] = None    # 事件回调: (event_dict) -> None

        # 用户消息回调注册
        self._message_handlers: list[Callable] = []

    # ---- 消息处理 ----

    def add_handler(self, handler: Callable):
        """添加消息处理器 handler(msg_dict)"""
        self._message_handlers.append(handler)

    def _process_message(self, data: dict):
        """处理 OneBot 事件"""
        post_type = data.get("post_type", "")
        message_type = data.get("message_type", "")

        # 私聊消息
        if post_type == "message" and message_type == "private":
            msg = {
                "type": "private",
                "user_id": str(data.get("user_id", "")),
                "nickname": data.get("sender", {}).get("nickname", ""),
                "text": data.get("raw_message", ""),
                "message_id": data.get("message_id", 0),
                "timestamp": data.get("time", int(time.time())),
                "group_id": None,
                "source": "qq",
            }
            self._dispatch(msg)

        # 群聊消息（包含 @机器人 或特定前缀）
        elif post_type == "message" and message_type == "group":
            raw = data.get("raw_message", "")
            # 检查是否 @了机器人 或包含特定前缀
            is_mentioned = "[CQ:at,qq=" in raw
            has_prefix = raw.startswith("/") or raw.startswith("!") or raw.startswith(".")

            if is_mentioned or has_prefix:
                # 清理消息（去掉 @ 和前缀）
                text = raw
                if is_mentioned:
                    # 去掉 [CQ:at,qq=xxx] 标签
                    import re
                    text = re.sub(r"\[CQ:at,qq=\d+\]\s*", "", text).strip()
                if has_prefix:
                    text = text.lstrip("/!.")

                msg = {
                    "type": "group",
                    "user_id": str(data.get("user_id", "")),
                    "nickname": data.get("sender", {}).get("nickname", ""),
                    "group_id": str(data.get("group_id", "")),
                    "text": text,
                    "message_id": data.get("message_id", 0),
                    "timestamp": data.get("time", int(time.time())),
                    "source": "qq",
                }
                self._dispatch(msg)

        # 其他事件
        elif post_type in ("notice", "request", "meta_event"):
            if self.on_event:
                self.on_event(data)

    def _dispatch(self, msg: dict):
        """分发消息到所有处理器"""
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception as e:
                print(f"[QQ] on_message 回调异常: {e}")

        for handler in self._message_handlers:
            try:
                handler(msg)
            except Exception as e:
                print(f"[QQ] handler 异常: {e}")

    # ---- 正向 WebSocket 模式 ----

    def _ws_connect(self):
        """通过正向 WebSocket 连接 OneBot"""
        try:
            import websocket
        except ImportError:
            print("[QQ] 请安装 websocket-client: pip install websocket-client")
            return

        print(f"[QQ] 正在连接 OneBot WebSocket: {self.ws_url}")

        def on_message(ws, message):
            try:
                data = json.loads(message)
                self._process_message(data)
            except json.JSONDecodeError:
                pass

        _last_error_time = [0]  # 用于节流错误日志

        def on_error(ws, error):
            now = time.time()
            if now - _last_error_time[0] > 300:
                print(f"[QQ] WebSocket 错误: {error}")
                _last_error_time[0] = now

        def on_close(ws, close_status_code, close_msg):
            pass  # 不打印断开日志，避免刷屏。由重连逻辑统一处理

        def on_open(ws):
            print(f"[QQ] 已连接到 OneBot: {self.ws_url}")

        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                    on_open=on_open,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                self._retry_count = getattr(self, '_retry_count', 0) + 1
                if self._retry_count <= 3 or self._retry_count % 60 == 0:
                    print(f"[QQ] 连接失败 (第{self._retry_count}次): {e}，60秒后重试...")
                # 指数退避: 10s -> 60s，降低 CPU 空耗
                delay = 60 if self._retry_count > 10 else 10
                time.sleep(delay)

    # ---- 消息发送 ----

    def _to_int_id(self, raw_id: str) -> int:
        """安全转换 QQ 号（支持纯数字 ID 和 str ID）"""
        try:
            return int(raw_id)
        except (ValueError, TypeError):
            # 字符串 ID（如负值机器人）使用 hash
            return abs(hash(raw_id)) % (10 ** 10)

    def send_private_msg(self, user_id: str, text: str) -> bool:
        """发送私聊消息（需要正向 WS 连接）"""
        return self._send_api("send_private_msg", {
            "user_id": self._to_int_id(user_id),
            "message": text,
        })

    def send_group_msg(self, group_id: str, text: str) -> bool:
        """发送群聊消息"""
        return self._send_api("send_group_msg", {
            "group_id": self._to_int_id(group_id),
            "message": text,
        })

    def _send_api(self, action: str, params: dict) -> bool:
        """调用 OneBot API"""
        if not self._ws:
            print(f"[QQ] WebSocket 未连接，无法发送消息")
            return False
        try:
            payload = json.dumps({
                "action": action,
                "params": params,
            })
            self._ws.send(payload)
            return True
        except Exception as e:
            print(f"[QQ] 发送失败: {e}")
            return False

    # ---- 生命周期 ----

    def start(self, mode: str = "ws"):
        """
        启动 QQ Bot

        参数:
            mode: "ws" (正向 WebSocket) 或 "http" (仅注册 HTTP 回调端点)
        """
        if mode == "ws":
            self._running = True
            self._thread = threading.Thread(target=self._ws_connect, daemon=True)
            self._thread.start()
            print("[QQ] QQ Bot 已启动 (正向 WebSocket 模式)")
        elif mode == "http":
            print("[QQ] QQ Bot 已启动 (HTTP 回调模式，等待 /webhook/qq 接收消息)")

    def stop(self):
        """停止 QQ Bot"""
        self._running = False
        if self._ws:
            self._ws.close()
        print("[QQ] QQ Bot 已停止")


# ==================== 配置指南 ====================

SETUP_GUIDE = """
=== QQ Bot 接入指南 ===

1. 下载 go-cqhttp: https://github.com/Mrs4s/go-cqhttp/releases
   或使用 NapCatQQ: https://github.com/NapNeko/NapCatQQ

2. 配置正向 WebSocket:
   config.yml 中设置:
     - ws:
         host: 0.0.0.0
         port: 3001

3. 配置反向 HTTP:
   config.yml 中设置:
     - http:
         host: 0.0.0.0
         port: 5700
         post_url:
           - http://你的服务器IP:5000/webhook/qq

4. 扫码登录后即可接收消息
"""


# ==================== 测试 ====================

if __name__ == "__main__":
    print("=== QQ Bot 测试 ===")
    print(SETUP_GUIDE)

    bot = QQBot()

    def handle_message(msg):
        print(f"\n[收到QQ消息]")
        print(f"  类型: {msg['type']}")
        print(f"  用户: {msg['nickname']} ({msg['user_id']})")
        print(f"  内容: {msg['text']}")
        if msg.get("group_id"):
            print(f"  群组: {msg['group_id']}")

    bot.on_message = handle_message

    print("\n启动 QQ Bot (正向 WebSocket 模式)...")
    print("请确保 go-cqhttp 已启动并配置了正向 WS")
    bot.start(mode="ws")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bot.stop()
