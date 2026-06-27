"""
微信 ClawBot 适配器 — 官方个人微信 Bot
========================================
ClawBot 是微信官方推出的 Bot API（基于 iLink 协议），
支持扫码登录个人微信，收发文本消息。

协议: https://ilinkai.weixin.qq.com (腾讯官方服务器)
前置: 微信 → 我 → 设置 → 插件 → ClawBot → 开启

用法:
    python clawbot.py                    # 启动 ClawBot 服务
    python clawbot.py --once             # 单次运行后退出

架构:
    微信用户消息 → ilinkai.weixin.qq.com → ClawBot长轮询 → AI大脑 → 回复
"""

import os
import sys
import json
import base64
import time
import random
import struct
import hashlib
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional
from io import BytesIO

# ==================== 编码修复 ====================
if sys.platform == "win32":
    # Python 3.7+ recomended way
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

# ==================== 配置 ====================

import config  # 加载 .env

# ClawBot 配置
CLAWBOT_ENABLED = os.environ.get("CLAWBOT_ENABLED", "").lower() in ("true", "1", "yes")
CLAWBOT_CONFIG_FILE = Path(__file__).parent / "clawbot_config.json"

# AI 大脑配置
BRAIN_API = os.environ.get("BRAIN_API", "http://127.0.0.1:5000/api/chat")

# ClawBot API 基础地址
ILINK_BASE = "https://ilinkai.weixin.qq.com"

# ==================== 配置持久化 ====================

def load_config() -> dict:
    """加载 ClawBot 配置"""
    if CLAWBOT_CONFIG_FILE.exists():
        try:
            return json.loads(CLAWBOT_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    """保存 ClawBot 配置"""
    CLAWBOT_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ==================== ClawBot 核心客户端 ====================

class ClawBotClient:
    """
    微信 ClawBot iLink 协议客户端

    基于腾讯官方 @tencent-weixin/openclaw-weixin 逆向分析，
    纯 Python 实现，零第三方依赖（二维码渲染可选 pillow/qrcode）。
    """

    def __init__(self, config_path: Path = CLAWBOT_CONFIG_FILE):
        self.config_path = config_path
        self.cfg = load_config()

        # 会话状态
        self.bot_token: str = self.cfg.get("bot_token", "")
        self.user_id: str = self.cfg.get("user_id", "")  # 自己的微信ID
        self.base_url: str = self.cfg.get("base_url", ILINK_BASE)  # 登录后可能变化
        self.update_buf: str = ""  # 长轮询游标

        # 用户 typing_ticket 缓存（发送消息前必须获取）
        self._typing_tickets: dict = {}

        # 消息处理器
        self.on_message = None  # Callable[[dict], Optional[str]]

        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ==================== 工具方法 ====================

    @staticmethod
    def _random_uin() -> str:
        """生成随机的 X-WECHAT-UIN"""
        return base64.b64encode(str(random.randint(1, 2 ** 32 - 1)).encode()).decode()

    @staticmethod
    def _random_hex(length: int = 8) -> str:
        return hashlib.md5(str(random.random()).encode()).hexdigest()[:length]

    def _headers(self, auth_required: bool = True) -> dict:
        """构造请求头
        auth_required: 登录流程中的接口不需要鉴权，传 False
        """
        h = {
            "Content-Type": "application/json",
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": "1",  # 根据逆向分析，版本号应为 "1"
            "Connection": "close",  # 避免 HTTPS 长连接复用被服务端断开
        }
        if auth_required and self.bot_token:
            h["AuthorizationType"] = "ilink_bot_token"
            h["Authorization"] = f"Bearer {self.bot_token}"
            h["X-WECHAT-UIN"] = self._random_uin()
        return h

    def _base_info(self) -> dict:
        return {
            "base_info": {
                "channel_version": "2.4.3",
                "bot_agent": "weixin-ClawBot-API/1.0.1 (python)",
            }
        }

    def _post(self, endpoint: str, payload: dict, params: dict = None, timeout: int = 15, auth: bool = True) -> dict:
        """发送 POST 请求到 iLink API"""
        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.post(url, json=payload, params=params, headers=self._headers(auth), timeout=timeout)
            ct = resp.headers.get("Content-Type", "")
            if "application/json" in ct:
                return resp.json()
            elif "octet-stream" in ct:
                return json.loads(resp.text)
            else:
                try:
                    return resp.json()
                except Exception:
                    return json.loads(resp.text) if resp.text else {}
        except requests.exceptions.Timeout:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    def _get(self, endpoint: str, params: dict = None, timeout: int = 15, auth: bool = True) -> dict:
        """发送 GET 请求"""
        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.get(url, params=params, headers=self._headers(auth), timeout=timeout)
            ct = resp.headers.get("Content-Type", "")
            if "application/json" in ct:
                return resp.json()
            else:
                try:
                    return json.loads(resp.text)
                except Exception:
                    return {"error": f"bad json: {resp.text[:100]}"}
        except Exception as e:
            return {"error": str(e)}

    # ==================== 登录流程 ====================

    def get_login_qrcode(self) -> Optional[str]:
        """
        获取登录二维码
        返回: 二维码 URL（不是图片数据本身，是 https 链接）
        """
        print("[ClawBot] 正在连接微信iLink服务器获取二维码...", flush=True)
        result = self._get("/ilink/bot/get_bot_qrcode", params={"bot_type": "3"}, timeout=20, auth=False)
        if result.get("error"):
            print(f"[ClawBot] 获取二维码失败: {result['error']}", flush=True)
            return None

        # 打印完整响应用于调试（含 token 是否存在但隐藏值）
        has_bot_token = "bot_token" in result
        debug = {k: v for k, v in result.items() if k not in ("bot_token",)}
        debug["_has_bot_token"] = has_bot_token
        print(f"[DEBUG] get_bot_qrcode 响应: {json.dumps(debug, ensure_ascii=False)}", flush=True)

        # 服务器在 get_bot_qrcode 阶段就可能返回 token（扫码预授权）
        if has_bot_token:
            self.bot_token = result["bot_token"]
            self.cfg["bot_token"] = self.bot_token
            print(f"[ClawBot] 获取到 bot_token: {self.bot_token[:30]}...", flush=True)

        qrcode_url = result.get("qrcode_img_content", result.get("qrcode_url", ""))
        qrcode_id = result.get("qrcode", result.get("uuid", result.get("qr_code", "")))

        # 保存 qrcode 用于轮询
        if qrcode_id:
            self.cfg["login_qrcode"] = qrcode_id
            save_config(self.cfg)
            print(f"[ClawBot] 二维码ID: {qrcode_id}", flush=True)
        else:
            print("[ClawBot] 警告: 未获取到二维码ID，无法轮询状态", flush=True)

        if qrcode_url:
            print(f"[ClawBot] 二维码URL: {qrcode_url}", flush=True)
            return qrcode_url
        return None

    def wait_for_scan(self, timeout: int = 120) -> bool:
        """
        等待用户扫码确认
        返回: 是否登录成功
        """
        login_qrcode = self.cfg.get("login_qrcode", "")
        if not login_qrcode:
            print("[ClawBot] 没有 login_qrcode，请先获取二维码")
            return False

        print("[ClawBot] 等待扫码... (请在微信中扫描二维码)", flush=True)
        print("[ClawBot] 提示: 扫码后点确认才能完成登录", flush=True)
        start = time.time()
        last_logged_status = ""  # 避免重复打印

        while time.time() - start < timeout:
            # 服务器长轮询，hold 连接最多约 40 秒，所以设 45 秒超时
            result = self._get("/ilink/bot/get_qrcode_status", {
                "qrcode": login_qrcode,
            }, timeout=45, auth=False)

            status = result.get("status", "")
            ret = result.get("ret", None)
            errcode = result.get("errcode", None)
            errmsg = result.get("errmsg", "")
            error_field = result.get("error", "")

            # 长轮询超时：服务器 hold 连接 40s 后客户端超时，表示"状态未变"，静默重试
            if error_field and "timed out" in str(error_field).lower():
                if int(time.time() - start) % 10 == 0:
                    print(f"  等待中... ({int(time.time() - start)}s) [长轮询模式]", flush=True)
                continue

            # 打印完整响应用于调试（去敏感字段，但标注 token 是否存在）
            debug_result = {k: v for k, v in result.items() if k not in ("bot_token",)}
            if "bot_token" in result:
                debug_result["_has_bot_token"] = True
            if status != last_logged_status:
                print(f"[DEBUG] get_qrcode_status 响应: {json.dumps(debug_result, ensure_ascii=False)}", flush=True)
                last_logged_status = status

            # 状态处理（兼容多种可能的返回值）
            if status in ("wait", "waiting", "unused", "pending"):
                if int(time.time() - start) % 5 == 0:
                    print(f"  等待中... ({int(time.time() - start)}s)", flush=True)
                time.sleep(2)

            elif status in ("scaned", "scanned", "scan"):
                print("  [ClawBot] 已扫码，请在手机上点击确认...", flush=True)
                time.sleep(2)

            elif status in ("confirmed", "confirm", "success", "ok", "logged_in", "login"):
                # bot_token 可能在 get_bot_qrcode 阶段就已返回，这里只做补充
                new_token = result.get("bot_token", "")
                if new_token:
                    self.bot_token = new_token
                # 兼容: ilink_bot_id 只是 bot ID，不是完整 token
                new_user = result.get("user_id", result.get("ilink_user_id", result.get("openid", "")))
                if new_user:
                    self.user_id = new_user
                # 服务器可能返回不同的 base URL（通常与 ILINK_BASE 相同）
                baseurl = result.get("baseurl", result.get("base_url", ""))
                if baseurl:
                    self.base_url = baseurl
                    self.cfg["base_url"] = baseurl

                self.cfg["bot_token"] = self.bot_token
                self.cfg["user_id"] = self.user_id
                self.cfg.pop("login_qrcode", None)
                save_config(self.cfg)

                print(f"[ClawBot] 登录成功!", flush=True)
                print(f"  user_id: {self.user_id}", flush=True)
                print(f"  base_url: {self.base_url}", flush=True)
                print(f"  bot_token: {self.bot_token[:30] if self.bot_token else 'N/A'}...", flush=True)
                return True

            elif status in ("expired", "expire", "timeout"):
                print("[ClawBot] 二维码已过期，重新获取...", flush=True)
                self.cfg.pop("login_qrcode", None)
                save_config(self.cfg)
                return False

            elif status in ("cancelled", "cancel", "refuse", "rejected"):
                print("[ClawBot] 用户在手机上取消了登录", flush=True)
                self.cfg.pop("login_qrcode", None)
                save_config(self.cfg)
                return False

            elif error_field and ("connection" in str(error_field).lower() or "refused" in str(error_field).lower()):
                # 连接级别的错误（非超时），等久一点再重试
                print(f"[ClawBot] 连接错误: {error_field}", flush=True)
                time.sleep(5)

            elif errcode is not None:
                err_detail = errmsg or f"errcode={errcode}"
                print(f"[ClawBot] API 错误: {err_detail}", flush=True)
                time.sleep(3)

            elif ret is not None and ret != 0:
                print(f"[ClawBot] 返回 ret={ret}, 继续轮询...", flush=True)
                time.sleep(2)

            else:
                # 未知状态，打印完整响应
                print(f"[ClawBot] 未知状态码: '{status}'", flush=True)
                print(f"[DEBUG] 完整响应: {json.dumps(debug_result, ensure_ascii=False)}", flush=True)
                time.sleep(2)

        print("[ClawBot] 扫码超时", flush=True)
        return False

    def _validate_token(self) -> bool:
        """验证 token 是否有效（使用非长轮询端点，快速返回）"""
        if not self.bot_token:
            return False
        
        # 用 getupdates 验证，超时 = token 有效（服务器接受了鉴权）
        # 只有 HTTP 401 或明确 errcode 才表示 token 无效
        result = self._post("/ilink/bot/getupdates", {
            **self._base_info(),
            "get_updates_buf": "",
        }, auth=True, timeout=10)
        
        error = result.get("error", "")
        # 超时 = 长轮询正常返回，token 有效
        if error:
            if "timeout" in error.lower():
                print("[ClawBot] Token 有效，已恢复会话", flush=True)
                return True
            # 其他网络错误，再试一次
            print(f"[ClawBot] 验证 token 网络错误: {error}，重试...", flush=True)
            time.sleep(2)
            result2 = self._post("/ilink/bot/getupdates", {
                **self._base_info(),
                "get_updates_buf": "",
            }, auth=True, timeout=10)
            error2 = result2.get("error", "")
            if error2 and "timeout" in error2.lower():
                print("[ClawBot] Token 有效（重试后网络恢复）", flush=True)
                return True
            # 两次都非超时，可能真是过期了
            errcode = result2.get("errcode") or result.get("errcode")
            if errcode is not None:
                print(f"[ClawBot] Token 无效: errcode={errcode}", flush=True)
                return False
            # 无法判断，保守起见走登录流程
            return False
        
        # 无 error（拿到了消息），token 肯定有效
        print("[ClawBot] Token 有效，已恢复会话", flush=True)
        return True

    def login(self) -> bool:
        """完整的登录流程（二维码过期自动重试）"""
        print("[ClawBot] 启动登录流程...", flush=True)
        # 清理残留的旧 qrcode
        if self.cfg.get("login_qrcode"):
            self.cfg.pop("login_qrcode", None)
        
        # 如果已有有效 token，尝试直接用
        if self.bot_token:
            print("[ClawBot] 已有 token，尝试验证...", flush=True)
            if self._validate_token():
                return True
            else:
                print("[ClawBot] Token 已过期，重新登录...", flush=True)
                self.bot_token = ""
                self.user_id = ""
                self.cfg["bot_token"] = ""
                self.cfg["user_id"] = ""
                save_config(self.cfg)

        # 获取二维码（带重试）
        for attempt in range(3):
            qrcode_url = self.get_login_qrcode()
            if not qrcode_url:
                print(f"[ClawBot] 获取二维码失败 (第{attempt+1}/3次)", flush=True)
                time.sleep(3)
                continue

            print("[ClawBot] 二维码已获取，渲染中...", flush=True)
            # 渲染二维码
            self._render_qrcode(qrcode_url)

            # 等待扫码（内部处理过期重试）
            if self.wait_for_scan(timeout=150):
                return True

            print(f"[ClawBot] 将重新获取二维码 (第{attempt+1}次)...", flush=True)
            time.sleep(2)

        print("[ClawBot] 多次尝试后登录失败", flush=True)
        return False

    def _render_qrcode(self, qrcode_url: str):
        """在终端渲染二维码"""
        # 先下载二维码图片
        try:
            resp = requests.get(qrcode_url, timeout=15)
            if resp.status_code != 200:
                print(f"\n[ClawBot] 请用微信扫描二维码:", flush=True)
                print(f"  {qrcode_url}\n", flush=True)
                return

            img_data = resp.content

            # 用 pillow 渲染到终端
            try:
                from PIL import Image
                img = Image.open(BytesIO(img_data))
                img = img.resize((37, 37), Image.NEAREST).convert("L")
                pixels = img.load()

                print()
                for y in range(37):
                    line = ""
                    for x in range(37):
                        line += "  " if pixels[x, y] > 128 else "■■"
                    print(f"  {line}")
                print()
                print(f"  [ClawBot] 请用微信扫描上方二维码", flush=True)
                print(f"  直链: {qrcode_url}", flush=True)
                print()
            except ImportError:
                print(f"\n[ClawBot] 请用微信扫描二维码:", flush=True)
                print(f"  {qrcode_url}\n", flush=True)
        except Exception:
            print(f"\n[ClawBot] 请用微信扫描二维码:", flush=True)
            print(f"  {qrcode_url}\n", flush=True)

    # ==================== 获取配置（typing_ticket） ====================

    def get_config(self, to_user_id: str) -> str:
        """
        获取用户配置（必须调用，获取 typing_ticket）
        返回: typing_ticket
        """
        if to_user_id in self._typing_tickets:
            return self._typing_tickets[to_user_id]

        result = self._post("/ilink/bot/getconfig", {
            **self._base_info(),
            "user_id_list": [to_user_id],
        })

        tickets = result.get("user_config_list", [])
        for uc in tickets:
            uid = uc.get("user_id", "")
            ticket = uc.get("typing_ticket", "")
            if uid and ticket:
                self._typing_tickets[uid] = ticket
                if uid == to_user_id:
                    return ticket
        return ""

    # ==================== 发送消息 ====================

    def send_typing(self, to_user_id: str, status: int = 1):
        """
        发送"正在输入"状态
        status: 1=开始输入, 2=取消输入
        """
        ticket = self.get_config(to_user_id)
        if not ticket:
            return

        self._post("/ilink/bot/sendtyping", {
            **self._base_info(),
            "to_user_id": to_user_id,
            "typing_ticket": ticket,
            "status": status,
        })

    def send_text(self, to_user_id: str, text: str, context_token: str = "") -> bool:
        """
        发送文本消息
        context_token: 回复消息时必须携带接收到的消息的 context_token
        """
        if not self.bot_token:
            print("[ClawBot] 未登录")
            return False

        # 截断过长消息（微信限制约2048字符，留余量）
        if len(text) > 1800:
            text = text[:1797] + "..."

        # 发送"正在输入"
        self.send_typing(to_user_id, 1)

        client_id = f"openclaw-weixin-{self._random_hex(16)}"

        payload = {
            **self._base_info(),
            "msg": {
                "from_user_id": "",  # 必须为空字符串
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token or "",
                "item_list": [
                    {
                        "type": 1,  # 文本类型
                        "text_item": {"text": text},
                    }
                ],
            },
        }

        # 直接发请求并捕获原始响应
        url = f"{self.base_url}/ilink/bot/sendmessage"
        try:
            resp = requests.post(url, json=payload, headers=self._headers(auth=True), timeout=15)
            print(f"[DEBUG] sendmessage HTTP {resp.status_code} | len={len(resp.text)}", flush=True)
            if resp.text:
                print(f"[DEBUG] sendmessage body: {resp.text[:300]}", flush=True)
            
            ct = resp.headers.get("Content-Type", "")
            if "application/json" in ct:
                result = resp.json()
            elif resp.text:
                try:
                    result = json.loads(resp.text)
                except Exception:
                    print(f"[DEBUG] sendmessage 非JSON响应: {resp.text[:200]}", flush=True)
                    result = {"error": f"非JSON: {resp.text[:100]}"}
            else:
                print(f"[DEBUG] sendmessage 空响应体", flush=True)
                result = {}
        except requests.exceptions.Timeout:
            result = {"error": "timeout"}
        except Exception as e:
            result = {"error": str(e)}
        
        self.send_typing(to_user_id, 2)  # 取消"正在输入"

        if result.get("error"):
            print(f"[ClawBot] 发送失败: {result['error']}")
            return False

        ret = result.get("ret", -1)
        if ret != 0:
            print(f"[ClawBot] 发送失败: ret={ret}, response={json.dumps(result, ensure_ascii=False)[:200]}")
            return False

        return True

    # ==================== 消息轮询 ====================

    def poll_messages(self) -> list:
        """长轮询获取新消息"""
        payload = {
            **self._base_info(),
            "get_updates_buf": self.update_buf,
        }

        result = self._post("/ilink/bot/getupdates", payload, timeout=40)

        if result.get("error"):
            if result["error"] != "timeout":
                print(f"[ClawBot] 轮询错误: {result['error']}")
            return []

        # 更新游标
        self.update_buf = result.get("get_updates_buf", "")

        msgs = result.get("msgs", [])
        return msgs

    # ==================== AI 对话 ====================

    def ask_ai(self, user_id: str, text: str) -> str:
        """调用大脑 AI（带重试）"""
        last_error = ""
        for attempt in range(3):
            try:
                resp = requests.post(
                    BRAIN_API,
                    json={
                        "message": text,
                        "session_id": f"clawbot_{user_id}",
                    },
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "ClawBot/1.0",
                        "Connection": "close",  # 避免 keep-alive 连接池问题
                    },
                    timeout=90,
                )
                data = resp.json()
                if data.get("success"):
                    return data.get("reply", "嗯嗯")
                
                # 打印完整响应用于调试
                print(f"[DEBUG] AI 响应 (HTTP {resp.status_code}): {json.dumps(data, ensure_ascii=False)[:300]}", flush=True)
                err_msg = data.get("error", data.get("reply", "未知错误"))
                print(f"[ClawBot] AI 返回错误: {err_msg}", flush=True)
                last_error = err_msg
                
                # 非服务器错误就不重试了
                if resp.status_code < 500:
                    break
                    
            except requests.exceptions.Timeout:
                print(f"[ClawBot] AI 调用超时 (第{attempt+1}/3次)", flush=True)
                last_error = "连接超时"
            except requests.exceptions.ConnectionError as e:
                print(f"[ClawBot] AI 连接失败 (第{attempt+1}/3次): {e}", flush=True)
                last_error = "无法连接大脑服务器"
                time.sleep(2)  # 等2秒再重试
            except Exception as e:
                print(f"[ClawBot] AI 调用失败 (第{attempt+1}/3次): {e}", flush=True)
                last_error = str(e)[:60]
                time.sleep(1)
        
        # 返回简短错误消息，避免发送失败
        return f"[AI离线] {last_error[:30]}，稍后重试"

    # ==================== 消息处理循环 ====================

    def process_message(self, msg: dict):
        """处理单条消息"""
        from_user = msg.get("from_user_id", "")
        context_token = msg.get("context_token", "")
        items = msg.get("item_list", [])

        if not from_user or not items:
            return

        for item in items:
            item_type = item.get("type", 0)
            if item_type == 1:  # 文本
                text = item.get("text_item", {}).get("text", "")
                if not text.strip():
                    continue

                print(f"[ClawBot] {from_user}: {text[:80]}")

                # 调用 AI
                reply = self.ask_ai(from_user, text)

                # 发送回复
                self.send_text(from_user, reply, context_token)
                print(f"[ClawBot] 回复: {reply[:80]}")

                # 触发回调
                if self.on_message:
                    try:
                        self.on_message({
                            "user_id": from_user,
                            "text": text,
                            "reply": reply,
                            "source": "clawbot",
                            "timestamp": datetime.now().isoformat(),
                        })
                    except Exception as e:
                        print(f"[ClawBot] 回调异常: {e}")

    def _poll_loop(self):
        """消息轮询主循环"""
        print("[ClawBot] 开始监听消息...")
        while self._running:
            try:
                msgs = self.poll_messages()
                for msg in msgs:
                    self.process_message(msg)
            except Exception as e:
                if self._running:
                    print(f"[ClawBot] 轮询异常: {e}")
                    traceback.print_exc()
                    time.sleep(3)

    # ==================== 生命周期 ====================

    def start(self, block: bool = True):
        """启动 ClawBot"""
        if not self.login():
            print("[ClawBot] 登录失败，无法启动")
            return False

        self._running = True

        if block:
            self._poll_loop()
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()
            print("[ClawBot] 已后台启动")

        return True

    def stop(self):
        """停止 ClawBot"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        save_config(self.cfg)
        print("[ClawBot] 已停止")

    def logout(self):
        """退出登录"""
        self.stop()
        self.bot_token = ""
        self.user_id = ""
        self.update_buf = ""
        self._typing_tickets.clear()
        if CLAWBOT_CONFIG_FILE.exists():
            CLAWBOT_CONFIG_FILE.unlink()
        print("[ClawBot] 已退出登录")


# ==================== 便捷函数 ====================

def start_clawbot(once: bool = False):
    """启动 ClawBot 的便捷入口"""
    bot = ClawBotClient()

    if once:
        # 单次运行模式
        if not bot.login():
            return
        print("[ClawBot] 单次运行模式，收到消息后退出...")
        bot._running = True
        msgs = bot.poll_messages()
        for msg in msgs:
            bot.process_message(msg)
        bot.stop()
    else:
        # 持续运行模式
        try:
            bot.start(block=True)
        except KeyboardInterrupt:
            print("\n[ClawBot] 收到中断信号")
            bot.stop()


# ==================== 命令行入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="微信 ClawBot - 官方个人微信 AI 助手")
    parser.add_argument("--once", action="store_true", help="单次运行模式")
    parser.add_argument("--logout", action="store_true", help="退出登录")
    parser.add_argument("--login", action="store_true", help="仅登录，获取 token")

    args = parser.parse_args()

    # 网络预检（仅测试连接，不带鉴权）    
    print("[ClawBot] 检测网络连接...", flush=True)
    try:
        test_resp = requests.get(f"{ILINK_BASE}/ilink/bot/get_bot_qrcode", 
                                 params={"bot_type": "3"}, timeout=10,
                                 headers={"Connection": "close"})
        print(f"[ClawBot] iLink API 可达 (HTTP {test_resp.status_code})", flush=True)
    except requests.exceptions.Timeout:
        print("[ClawBot] 警告: iLink API 连接超时 (10s)，可能网络较慢", flush=True)
    except Exception as e:
        print(f"[ClawBot] 警告: iLink API 不可达: {e}", flush=True)
        print("[ClawBot] 将继续尝试，可能需要检查代理/VPN设置", flush=True)

    if args.logout:
        bot = ClawBotClient()
        bot.logout()
    elif args.login:
        bot = ClawBotClient()
        bot.login()
    else:
        print("=" * 55)
        print("  微信 ClawBot — 官方个人微信 AI 助手")
        print("=" * 55)
        print(f"  大脑 API:  {BRAIN_API}")
        print(f"  API 服务器: {ILINK_BASE}")
        print(f"  配置文件:  {CLAWBOT_CONFIG_FILE}")
        print()
        print("  前提: 微信 → 我 → 设置 → 插件 → ClawBot → 开启")
        print("=" * 55)
        print()

        start_clawbot(once=args.once)
