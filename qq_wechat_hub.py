"""
QQ/微信 AI 助手 - 本地桥接中心
================================
功能：接收 QQ/微信消息，调用 DeepSeek API 智能回复

架构：
  QQ 消息  → OneBot v11 HTTP POST → /qq   → DeepSeek API → 回复给 QQ
  微信消息 → 企业微信回调         → /wechat → DeepSeek API → 回复给微信

运行: python qq_wechat_hub.py
访问: http://localhost:5055
"""

import json
import os
import re
import threading
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, request

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

# ==================== 配置 ====================
# OneBot HTTP API 地址（QQ Bot 发送消息的接口）
ONEBOT_HTTP_API = os.environ.get("ONEBOT_HTTP_API", "http://localhost:3000")

# 服务端口
PORT = int(os.environ.get("HUB_PORT", "5055"))

# 对话历史（按用户 Session）
MAX_HISTORY = 20

app = Flask(__name__)

# 用户对话历史存储
user_sessions: dict[str, list[dict]] = {}
sessions_lock = threading.Lock()


# ==================== DeepSeek API 调用 ====================

def call_deepseek(session_id: str, user_message: str) -> str:
    """调用 DeepSeek API 获取 AI 回复"""
    with sessions_lock:
        if session_id not in user_sessions:
            user_sessions[session_id] = []
        history = user_sessions[session_id]

    # 构建消息
    messages = [
        {"role": "system", "content": "你是 AI 智能助手，通过 QQ/微信为用户提供服务。回答简洁友好，中文回复。"}
    ]
    messages.extend(history[-MAX_HISTORY:])
    messages.append({"role": "user", "content": user_message})

    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2000,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]

            # 保存对话历史
            with sessions_lock:
                user_sessions[session_id].append({"role": "user", "content": user_message})
                user_sessions[session_id].append({"role": "assistant", "content": reply})
                if len(user_sessions[session_id]) > MAX_HISTORY * 2:
                    user_sessions[session_id] = user_sessions[session_id][-MAX_HISTORY * 2:]

            return reply
        else:
            print(f"[DeepSeek] API 错误: {resp.status_code} {resp.text[:200]}")
            return f"AI 服务暂时不可用（{resp.status_code}），请稍后重试。"
    except requests.exceptions.Timeout:
        return "AI 响应超时，请稍后重试。"
    except Exception as e:
        print(f"[DeepSeek] 异常: {e}")
        return f"AI 服务异常: {str(e)[:100]}"


# ==================== QQ 消息回复（通过 OneBot HTTP API） ====================

def send_qq_message(message_type: str, target_id: str, text: str, group_id: str = None):
    """通过 OneBot HTTP API 发送 QQ 消息"""
    try:
        if message_type == "private":
            url = f"{ONEBOT_HTTP_API}/send_private_msg"
            payload = {"user_id": target_id, "message": text}
        elif message_type == "group" and group_id:
            url = f"{ONEBOT_HTTP_API}/send_group_msg"
            payload = {"group_id": group_id, "message": text}
        else:
            return

        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[QQ] 回复成功 → {target_id}")
        else:
            print(f"[QQ] 回复失败: {resp.status_code}")
    except Exception as e:
        print(f"[QQ] 发送异常: {e}")


# ==================== 微信消息回复（企业微信群机器人 Webhook） ====================

def send_wechat_message(webhook_url: str, text: str):
    """通过企业微信群机器人 Webhook 发送消息"""
    if not webhook_url:
        return
    try:
        resp = requests.post(
            webhook_url,
            json={
                "msgtype": "text",
                "text": {"content": text},
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"[微信] 回复成功")
        else:
            print(f"[微信] 回复失败: {resp.status_code}")
    except Exception as e:
        print(f"[微信] 发送异常: {e}")


# ==================== Webhook 路由 ====================

@app.route("/", methods=["GET"])
def index():
    """状态页面"""
    session_count = len(user_sessions)
    return f"""
    <html><head><meta charset="utf-8"><title>QQ/微信 AI 助手</title>
    <style>body{{font-family:Arial;max-width:600px;margin:50px auto;padding:20px}}
    .ok{{color:green}}.card{{background:#f5f5f5;padding:15px;border-radius:8px;margin:10px 0}}
    code{{background:#e0e0e0;padding:2px 6px;border-radius:3px}}</style></head><body>
    <h1>🤖 QQ/微信 AI 助手 - 桥接中心</h1>
    <div class="card">
      <p class="ok">✅ 服务运行中 (端口 {PORT})</p>
      <p>🕐 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
      <p>👥 活跃会话: {session_count}</p>
      <p>🧠 AI 引擎: DeepSeek ({DEEPSEEK_MODEL})</p>
    </div>
    <h3>📱 QQ 接入</h3>
    <div class="card">
      <p>OneBot 回调地址: <code>http://localhost:{PORT}/qq</code></p>
      <p>OneBot HTTP API: <code>{ONEBOT_HTTP_API}</code></p>
      <p>状态: <span class="ok">✅ 已就绪</span></p>
    </div>
    <h3>💬 微信接入</h3>
    <div class="card">
      <p>微信回调地址: <code>http://localhost:{PORT}/wechat</code></p>
      <p>群机器人 Webhook: <code>配置在 WECOM_BOT_KEY 环境变量</code></p>
    </div>
    <h3>⚡ 快速测试</h3>
    <div class="card">
      <p>POST <code>/qq</code> 或 <code>/wechat</code> 发送 JSON:</p>
      <pre>{{"message":"你好","user_id":"test"}}</pre>
    </div>
    </body></html>
    """


@app.route("/qq", methods=["POST"])
def webhook_qq():
    """
    QQ OneBot v11 HTTP 回调
    收到 QQ 消息 → DeepSeek 回复 → OneBot HTTP API 发送
    """
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "") or data.get("raw_message", "")
    user_id = str(data.get("user_id", "unknown"))
    message_type = data.get("message_type", "private")  # private / group
    group_id = data.get("group_id", "")

    if not user_message.strip():
        return jsonify({"code": 0, "msg": "empty message"})

    session_id = f"qq_{user_id}"
    print(f"[QQ] {user_id} ({message_type}): {user_message[:80]}")

    def handle():
        reply = call_deepseek(session_id, user_message)
        send_qq_message(message_type, user_id, reply, group_id)

    threading.Thread(target=handle, daemon=True).start()
    return jsonify({"code": 0, "msg": "processing"})


@app.route("/wechat", methods=["POST"])
def webhook_wechat():
    """
    企业微信回调（简化版）
    支持群机器人直接 POST 和自建应用回调
    """
    data = request.get_json(silent=True) or {}

    # 企业微信群机器人格式
    if "msgtype" in data and data.get("msgtype") == "text":
        user_message = data.get("text", {}).get("content", "")
        user_id = data.get("chatid", data.get("from", {}).get("userid", "wx_unknown"))
    else:
        # 自建应用回调 / 通用格式
        user_message = data.get("message", "") or data.get("text", "") or data.get("Content", "")
        user_id = str(data.get("user_id", data.get("FromUserName", "wx_unknown")))

    webhook_url = data.get("webhook_url", os.environ.get("WECOM_BOT_KEY", ""))

    if not user_message.strip():
        return jsonify({"code": 0, "msg": "empty message"})

    session_id = f"wx_{user_id}"
    print(f"[微信] {user_id}: {user_message[:80]}")

    def handle():
        reply = call_deepseek(session_id, user_message)
        if webhook_url and webhook_url.startswith("http"):
            send_wechat_message(webhook_url, reply)

    threading.Thread(target=handle, daemon=True).start()
    return jsonify({"code": 0, "msg": "processing"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "sessions": len(user_sessions)})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """通用 API 聊天接口（供外部调用）"""
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")
    user_id = data.get("user_id", "api_user")
    if not user_message:
        return jsonify({"error": "message required"}), 400

    session_id = f"api_{user_id}"
    reply = call_deepseek(session_id, user_message)
    return jsonify({"reply": reply, "session_id": session_id})


# ==================== 启动 ====================

if __name__ == "__main__":
    print("=" * 55)
    print("  QQ/微信 AI 助手 - 本地桥接中心")
    print("=" * 55)
    print(f"  监听端口 : {PORT}")
    print(f"  AI 引擎  : DeepSeek ({DEEPSEEK_MODEL})")
    print(f"  QQ 回调  : http://localhost:{PORT}/qq")
    print(f"  微信回调 : http://localhost:{PORT}/wechat")
    print(f"  API 接口 : http://localhost:{PORT}/api/chat")
    print(f"  状态页   : http://localhost:{PORT}")
    print("=" * 55)
    print()
    print("  QQ 接入: 在 OneBot 客户端中配置 HTTP 回调 → 本机 :{0}".format(PORT))
    print("  微信接入: 企业微信应用 → 回调 URL → 本机 :{0}".format(PORT))
    print()

    # 使用 Flask 内置服务器（适合本地使用）
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
