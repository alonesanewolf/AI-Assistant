"""
微信适配器 (WeChat Bot)
========================
支持通过多种方式接入微信消息：

  方式 A - 企业微信机器人（推荐，稳定）: 创建群机器人，通过 Webhook 收发消息
  方式 B - 个人微信 itchat（不稳定，可能封号）: 使用 itchat 库
  方式 C - HTTP 回调桥接: 配合其他微信机器人框架使用

推荐使用方式 A（企业微信机器人），免费且不会被封号。
"""

import json
import os
import threading
import time
from typing import Callable, Optional


# ==================== 配置 ====================

# 企业微信机器人 Webhook Key
WECOM_BOT_KEY = os.environ.get("WECOM_BOT_KEY", "")
WECOM_WEBHOOK_URL = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECOM_BOT_KEY}" if WECOM_BOT_KEY else ""


class WeChatBot:
    """
    微信适配器

    用法:
        bot = WeChatBot(mode="wecom")   # 企业微信模式
        bot = WeChatBot(mode="itchat")  # 个人微信模式
        bot.on_message = lambda msg: print(msg['text'])
        bot.start()
    """

    def __init__(self, mode: str = "wecom", webhook_key: str = ""):
        """
        参数:
            mode: "wecom" (企业微信) / "itchat" (个人微信) / "webhook" (HTTP 回调)
            webhook_key: 企业微信机器人 key
        """
        self.mode = mode
        self.webhook_key = webhook_key or WECOM_BOT_KEY
        self.webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={self.webhook_key}" if self.webhook_key else ""
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self.on_message: Optional[Callable] = None
        self._message_handlers: list[Callable] = []

    # ---- 消息处理 ----

    def add_handler(self, handler: Callable):
        """添加消息处理器"""
        self._message_handlers.append(handler)

    def process_callback(self, data: dict) -> Optional[dict]:
        """
        处理来自 HTTP 回调的微信消息（供 brain.py /webhook/wechat 调用）

        返回: 格式化后的消息字典
        """
        msg_type = data.get("MsgType", data.get("msg_type", "text"))
        from_user = data.get("FromUserName", data.get("user_id", ""))
        content = data.get("Content", data.get("text", ""))

        msg = {
            "type": "private",
            "user_id": str(from_user),
            "nickname": data.get("nickname", from_user[:8]),
            "text": content,
            "message_id": data.get("MsgId", int(time.time())),
            "timestamp": data.get("CreateTime", int(time.time())),
            "source": "wechat",
            "group_id": data.get("group_id"),
        }

        self._dispatch(msg)
        return msg

    def _dispatch(self, msg: dict):
        """分发消息"""
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception as e:
                print(f"[WeChat] on_message 异常: {e}")

        for handler in self._message_handlers:
            try:
                handler(msg)
            except Exception as e:
                print(f"[WeChat] handler 异常: {e}")

    # ---- 企业微信机器人模式 ----

    def send_wecom_text(self, content: str, mentioned_list: list = None) -> bool:
        """发送企业微信文本消息"""
        if not self.webhook_url:
            print("[WeChat] 未配置企业微信 Webhook Key")
            return False
        try:
            import requests
            payload = {
                "msgtype": "text",
                "text": {
                    "content": content,
                    "mentioned_list": mentioned_list or [],
                },
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 200 and resp.json().get("errcode") == 0
        except Exception as e:
            print(f"[WeChat] 发送失败: {e}")
            return False

    def send_wecom_markdown(self, content: str) -> bool:
        """发送企业微信 Markdown 消息"""
        if not self.webhook_url:
            return False
        try:
            import requests
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 200 and resp.json().get("errcode") == 0
        except Exception as e:
            print(f"[WeChat] 发送 Markdown 失败: {e}")
            return False

    # ---- 个人微信 itchat 模式 ----

    def _itchat_loop(self):
        """运行 itchat"""
        try:
            import itchat
        except ImportError:
            print("[WeChat] 请安装 itchat: pip install itchat-uos")
            return

        @itchat.msg_register(itchat.content.TEXT)
        def on_text(msg):
            self.process_callback({
                "MsgType": "text",
                "FromUserName": msg.get("FromUserName", ""),
                "Content": msg.get("Text", ""),
                "MsgId": msg.get("MsgId", 0),
                "CreateTime": msg.get("CreateTime", 0),
            })

            # 自动回复（可选）
            # return "收到消息，处理中..."

        @itchat.msg_register(itchat.content.TEXT, isGroupChat=True)
        def on_group_text(msg):
            text = msg.get("Text", "")
            # 只响应 @机器人 或特定前缀的消息
            is_at = msg.get("IsAt", False)
            has_prefix = text.startswith("/") or text.startswith("!")

            if is_at or has_prefix:
                if has_prefix:
                    text = text.lstrip("/!.")
                self.process_callback({
                    "MsgType": "text",
                    "FromUserName": msg.get("ActualNickName", ""),
                    "Content": text,
                    "MsgId": msg.get("MsgId", 0),
                    "CreateTime": msg.get("CreateTime", 0),
                    "group_id": msg.get("FromUserName", ""),
                })

        print("[WeChat] 正在登录微信...")
        itchat.auto_login(hotReload=True)
        print("[WeChat] 微信登录成功，开始接收消息...")
        itchat.run()

    def send_itchat_text(self, user_id: str, text: str) -> bool:
        """通过 itchat 发送私聊消息"""
        try:
            import itchat
            itchat.send(text, toUserName=user_id)
            return True
        except Exception as e:
            print(f"[WeChat] itchat 发送失败: {e}")
            return False

    # ---- 生命周期 ----

    def start(self):
        """启动微信适配器"""
        self._running = True

        if self.mode == "wecom":
            print(f"[WeChat] 企业微信机器人已就绪")
            print(f"[WeChat] Webhook URL: {self.webhook_url or '(未配置)'}")
            print(f"[WeChat] 请将 /webhook/wechat 配置为回调地址")

        elif self.mode == "itchat":
            self._thread = threading.Thread(target=self._itchat_loop, daemon=True)
            self._thread.start()

        elif self.mode == "webhook":
            print("[WeChat] HTTP 回调模式已就绪，等待 /webhook/wechat 接收消息")

    def stop(self):
        """停止"""
        self._running = False
        if self.mode == "itchat":
            try:
                import itchat
                itchat.logout()
            except Exception:
                pass
        print("[WeChat] 已停止")


# ==================== 配置指南 ====================

SETUP_GUIDE = """
=== 微信接入指南 ===

方式一：企业微信机器人（推荐）
  1. 下载企业微信客户端，注册企业（免费）
  2. 创建群聊 → 群设置 → 群机器人 → 添加机器人
  3. 复制 Webhook Key，设置环境变量:
     set WECOM_BOT_KEY=你的key
  4. 企业微信机器人只能被动发送消息，接收消息需要配合:
     - 企业微信应用消息回调
     - 或使用 webhook 桥接转发

方式二：个人微信 itchat（注意封号风险）
  1. pip install itchat-uos
  2. 扫码登录
  3. 仅用于测试，不建议长期使用

方式三：HTTP 回调桥接
  配合第三方微信机器人框架（如 WeChatFerry、wxbot 等）
  将消息转发到 /webhook/wechat 端点
"""


if __name__ == "__main__":
    print("=== 微信适配器测试 ===")
    print(SETUP_GUIDE)
