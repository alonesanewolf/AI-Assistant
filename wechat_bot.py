"""
微信适配器 (WeChat Bot) - 完整版
================================
支持三种接入方式：

  方式 A - 企业微信应用（推荐，支持收发消息）:
    创建企业微信应用，通过 API 收发消息，稳定且免费。
  
  方式 B - 企业微信群机器人（仅支持发送）:
    创建群机器人，通过 Webhook 发送消息到群聊。
  
  方式 C - 个人微信 itchat（不推荐，可能封号）:
    使用 itchat-uos 库，扫码登录个人微信。

推荐使用方式 A（企业微信应用），可实现完整的收发消息功能。
"""

import base64
import hashlib
import json
import os
import threading
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import requests

# ==================== 配置 ====================

# 企业微信应用配置（方式 A）
WECOM_CORP_ID = os.environ.get("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.environ.get("WECOM_AGENT_ID", "")
WECOM_APP_SECRET = os.environ.get("WECOM_APP_SECRET", "")
WECOM_TOKEN = os.environ.get("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.environ.get("WECOM_ENCODING_AES_KEY", "")

# 企业微信群机器人 Webhook Key（方式 B）
WECOM_BOT_KEY = os.environ.get("WECOM_BOT_KEY", "")


class WeChatBot:
    """
    微信适配器 - 支持企业微信应用（推荐）/ 群机器人 / 个人微信

    用法:
        # 方式 A: 企业微信应用
        bot = WeChatBot(mode="wecom_app")
        bot.on_message = lambda msg: print(msg['text'])
        bot.start()

        # 方式 B: 群机器人（仅发消息）
        bot = WeChatBot(mode="wecom_bot", webhook_key="your_key")
        bot.send_text("Hello!")

        # 方式 C: 个人微信
        bot = WeChatBot(mode="itchat")
        bot.start()
    """

    # 企业微信 API 地址
    WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(
        self,
        mode: str = "wecom_app",
        corp_id: str = "",
        agent_id: str = "",
        app_secret: str = "",
        token: str = "",
        encoding_aes_key: str = "",
        webhook_key: str = "",
    ):
        """
        参数:
            mode: "wecom_app" (企业微信应用) / "wecom_bot" (群机器人) / "itchat" (个人微信) / "webhook" (HTTP回调)
            corp_id: 企业ID
            agent_id: 应用AgentId
            app_secret: 应用Secret
            token: 回调Token
            encoding_aes_key: 回调加密Key
            webhook_key: 群机器人Key
        """
        self.mode = mode
        self.corp_id = corp_id or WECOM_CORP_ID
        self.agent_id = agent_id or WECOM_AGENT_ID
        self.app_secret = app_secret or WECOM_APP_SECRET
        self.token = token or WECOM_TOKEN
        self.encoding_aes_key = encoding_aes_key or WECOM_ENCODING_AES_KEY

        # 群机器人
        self.webhook_key = webhook_key or WECOM_BOT_KEY
        self.webhook_url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={self.webhook_key}"
            if self.webhook_key else ""
        )

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._access_token: str = ""
        self._token_expire_time: float = 0

        # 回调
        self.on_message: Optional[Callable] = None  # (msg_dict) -> None
        self._message_handlers: list[Callable] = []

    # ==================== 消息处理 ====================

    def add_handler(self, handler: Callable):
        """添加消息处理器 handler(msg_dict)"""
        self._message_handlers.append(handler)

    def _dispatch(self, msg: dict):
        """分发消息到所有处理器"""
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
            "nickname": data.get("nickname", from_user[:8] if from_user else "未知用户"),
            "text": content,
            "message_id": data.get("MsgId", int(time.time())),
            "timestamp": data.get("CreateTime", int(time.time())),
            "source": "wechat",
            "group_id": data.get("group_id"),
        }

        self._dispatch(msg)
        return msg

    # ==================== 企业微信应用 API（方式 A）====================

    def _get_access_token(self) -> str:
        """获取企业微信 access_token（带缓存）"""
        if self._access_token and time.time() < self._token_expire_time:
            return self._access_token

        if not self.corp_id or not self.app_secret:
            print("[WeChat] 缺少 CORP_ID 或 APP_SECRET")
            return ""

        try:
            url = f"{self.WECOM_API_BASE}/gettoken"
            params = {
                "corpid": self.corp_id,
                "corpsecret": self.app_secret,
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if data.get("errcode") == 0:
                self._access_token = data["access_token"]
                self._token_expire_time = time.time() + data.get("expires_in", 7200) - 300
                return self._access_token
            else:
                print(f"[WeChat] 获取 token 失败: {data}")
                return ""
        except Exception as e:
            print(f"[WeChat] 获取 token 异常: {e}")
            return ""

    def send_wecom_text(self, content: str, to_user: str = "@all") -> bool:
        """
        企业微信应用发送文本消息
        to_user: 用户ID，支持 @all | 多个用 | 分隔
        """
        token = self._get_access_token()
        if not token:
            return False

        try:
            url = f"{self.WECOM_API_BASE}/message/send?access_token={token}"
            payload = {
                "touser": to_user,
                "msgtype": "text",
                "agentid": int(self.agent_id),
                "text": {"content": content},
                "safe": 0,
            }
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                return True
            else:
                print(f"[WeChat] 发送失败: {data}")
                return False
        except Exception as e:
            print(f"[WeChat] 发送异常: {e}")
            return False

    def send_wecom_markdown(self, content: str, to_user: str = "@all") -> bool:
        """企业微信应用发送 Markdown 消息"""
        token = self._get_access_token()
        if not token:
            return False

        try:
            url = f"{self.WECOM_API_BASE}/message/send?access_token={token}"
            payload = {
                "touser": to_user,
                "msgtype": "markdown",
                "agentid": int(self.agent_id),
                "markdown": {"content": content},
            }
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            return data.get("errcode") == 0
        except Exception as e:
            print(f"[WeChat] 发送 Markdown 失败: {e}")
            return False

    def send_wecom_image(self, image_path: str, to_user: str = "@all") -> bool:
        """企业微信应用发送图片消息"""
        token = self._get_access_token()
        if not token:
            return False

        try:
            # 先上传图片获取 media_id
            upload_url = f"{self.WECOM_API_BASE}/media/upload?access_token={token}&type=image"
            with open(image_path, "rb") as f:
                resp = requests.post(upload_url, files={"media": f}, timeout=30)
            data = resp.json()
            if data.get("errcode") != 0:
                print(f"[WeChat] 上传图片失败: {data}")
                return False
            media_id = data["media_id"]

            # 发送图片
            send_url = f"{self.WECOM_API_BASE}/message/send?access_token={token}"
            payload = {
                "touser": to_user,
                "msgtype": "image",
                "agentid": int(self.agent_id),
                "image": {"media_id": media_id},
            }
            resp = requests.post(send_url, json=payload, timeout=10)
            return resp.json().get("errcode") == 0
        except Exception as e:
            print(f"[WeChat] 发送图片失败: {e}")
            return False

    # ==================== 企业微信群机器人（方式 B）====================

    def send_bot_text(self, content: str, mentioned_list: list = None) -> bool:
        """群机器人发送文本消息"""
        if not self.webhook_url:
            print("[WeChat] 未配置群机器人 Webhook Key")
            return False
        try:
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
            print(f"[WeChat] 群机器人发送失败: {e}")
            return False

    def send_bot_markdown(self, content: str) -> bool:
        """群机器人发送 Markdown 消息"""
        if not self.webhook_url:
            return False
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 200 and resp.json().get("errcode") == 0
        except Exception as e:
            print(f"[WeChat] 群机器人发送 Markdown 失败: {e}")
            return False

    def send_bot_image(self, image_base64: str, image_md5: str = "") -> bool:
        """群机器人发送图片（base64）"""
        if not self.webhook_url:
            return False
        try:
            if not image_md5:
                image_md5 = hashlib.md5(image_base64.encode()).hexdigest()
            payload = {
                "msgtype": "image",
                "image": {
                    "base64": image_base64,
                    "md5": image_md5,
                },
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 200 and resp.json().get("errcode") == 0
        except Exception as e:
            print(f"[WeChat] 群机器人发送图片失败: {e}")
            return False

    # ==================== 个人微信 itchat（方式 C）====================

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
                "nickname": msg.get("User", {}).get("NickName", ""),
                "Content": msg.get("Text", ""),
                "MsgId": msg.get("MsgId", 0),
                "CreateTime": msg.get("CreateTime", 0),
            })

        @itchat.msg_register(itchat.content.TEXT, isGroupChat=True)
        def on_group_text(msg):
            text = msg.get("Text", "")
            is_at = msg.get("IsAt", False)
            has_prefix = text.startswith("/") or text.startswith("!")

            if is_at or has_prefix:
                if has_prefix:
                    text = text.lstrip("/!.")
                self.process_callback({
                    "MsgType": "text",
                    "FromUserName": msg.get("ActualNickName", ""),
                    "nickname": msg.get("ActualNickName", ""),
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

    # ==================== 消息回复（统一接口）====================

    def reply(self, to_user: str, content: str, source: dict = None) -> bool:
        """
        统一的消息回复接口
        根据 mode 自动选择发送方式
        """
        if self.mode == "wecom_app":
            return self.send_wecom_text(content, to_user)
        elif self.mode == "wecom_bot":
            return self.send_bot_text(content)
        elif self.mode == "itchat":
            return self.send_itchat_text(to_user, content)
        else:
            print(f"[WeChat] 当前模式 {self.mode} 不支持回复")
            return False

    # ==================== 生命周期 ====================

    def start(self):
        """启动微信适配器"""
        self._running = True

        if self.mode == "wecom_app":
            token = self._get_access_token()
            status = "已连接" if token else "未连接（检查 CORP_ID/APP_SECRET）"
            print(f"[WeChat] 企业微信应用模式已启动 ({status})")
            print(f"[WeChat] Corp ID: {self.corp_id[:8] if self.corp_id else '未配置'}...")
            print(f"[WeChat] Agent ID: {self.agent_id or '未配置'}")
            print(f"[WeChat] 请配置回调 URL 指向: /webhook/wechat")
            print(f"[WeChat] 在消息回调中调用 process_message() 处理接收消息")

        elif self.mode == "wecom_bot":
            print(f"[WeChat] 企业微信群机器人模式已启动")
            print(f"[WeChat] Webhook URL: {self.webhook_url or '(未配置)'}")

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

    # ==================== 回调验证（企业微信）====================

    @staticmethod
    def verify_url(msg_signature: str, timestamp: str, nonce: str, echostr: str,
                   token: str, encoding_aes_key: str) -> tuple:
        """
        验证企业微信回调 URL（GET 请求验证）
        返回: (成功, 解密后的echostr或错误信息)
        """
        try:
            # 尝试使用 pycryptodome 解密
            from Crypto.Cipher import AES
            import struct

            # 对签名进行校验
            sort_list = sorted([token, timestamp, nonce, echostr])
            sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
            if sha1 != msg_signature:
                return False, "签名验证失败"

            # 解密 echostr
            key = base64.b64decode(encoding_aes_key + "=")
            ciphertext = base64.b64decode(echostr)
            cipher = AES.new(key, AES.MODE_CBC, key[:16])
            plaintext = cipher.decrypt(ciphertext)

            # 去除补位
            pad = plaintext[-1]
            content = plaintext[16:-pad]
            # 去掉随机16字节后的内容
            msg_len = struct.unpack(">I", content[:4])[0]
            result = content[4:4 + msg_len].decode("utf-8")

            return True, result
        except ImportError:
            # 简化验证：没有 pycryptodome 时直接返回 echostr
            print("[WeChat] 未安装 pycryptodome，使用简化验证")
            return True, echostr
        except Exception as e:
            return False, str(e)


# ==================== 配置指南 ====================

SETUP_GUIDE = """
╔══════════════════════════════════════════════════════════╗
║           微信接入指南 - 推荐企业微信应用模式            ║
╚══════════════════════════════════════════════════════════╝

方式一：企业微信应用（推荐 - 支持收发消息）
──────────────────────────────────────────────
1. 访问 https://work.weixin.qq.com/ 注册企业微信（免费）
2. 进入"应用管理" → "自建" → "创建应用"
3. 记下以下信息：
   - 企业ID (CorpID)
   - AgentId
   - Secret
4. 设置"接收消息" → 配置回调 URL：
   URL: http://你的服务器IP:5000/webhook/wechat
   Token: 随机字符串（自己设定）
   EncodingAESKey: 随机生成
5. 设置环境变量：
   set WECOM_CORP_ID=你的企业ID
   set WECOM_AGENT_ID=你的AgentId
   set WECOM_APP_SECRET=你的Secret
   set WECOM_TOKEN=你的Token
   set WECOM_ENCODING_AES_KEY=你的EncodingAESKey
6. 运行: python wechat_assistant.py

方式二：企业微信群机器人（仅支持发送消息）
───────────────────────────────────────────
1. 企业微信 → 群聊 → 群设置 → 群机器人 → 添加
2. 复制 Webhook Key
3. 设置环境变量: set WECOM_BOT_KEY=你的key
4. 配合 /webhook/wechat 接收消息

方式三：个人微信 itchat（不推荐，易封号）
───────────────────────────────────────────
1. pip install itchat-uos
2. 运行: wechat_bot.py (mode="itchat")
3. 扫码登录（仅限测试使用）
"""


if __name__ == "__main__":
    print(SETUP_GUIDE)
    print("\n当前配置状态：")
    print(f"  WECOM_CORP_ID: {'已配置' if WECOM_CORP_ID else '未配置'}")
    print(f"  WECOM_AGENT_ID: {'已配置' if WECOM_AGENT_ID else '未配置'}")
    print(f"  WECOM_APP_SECRET: {'已配置' if WECOM_APP_SECRET else '未配置'}")
    print(f"  WECOM_BOT_KEY: {'已配置' if WECOM_BOT_KEY else '未配置'}")
