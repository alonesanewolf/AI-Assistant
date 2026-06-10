"""
企业微信 AI 助手 - 群机器人版
================================
使用企业微信群机器人 Webhook 收发消息。
无需内网穿透、无需域名备案、免费稳定。

使用方法:
1. 在企业微信中创建一个群聊
2. 群设置 → 群机器人 → 添加机器人 → 复制 Webhook 地址
3. 设置环境变量:
   set WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
4. 运行: python wechat_assistant.py
5. 在群里 @机器人 发送消息即可对话

也支持接收消息回调（推荐）:
- 在企业微信后台创建自建应用
- 配置接收消息 API 回调
"""

import os
import sys
import json
import hashlib
import threading
import time
import traceback
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote

if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (ValueError, AttributeError):
        pass

from flask import Flask, request, jsonify, render_template_string
import requests

# ==================== 配置 ====================

# 群机器人 Webhook（从企业微信群聊添加机器人获取）
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")

# 应用回调配置（自建应用模式，可选，更强大）
WECOM_CORP_ID = os.environ.get("WECOM_CORP_ID", "")
WECOM_AGENT_SECRET = os.environ.get("WECOM_AGENT_SECRET", "")
WECOM_TOKEN = os.environ.get("WECOM_TOKEN", "mytoken123")
WECOM_ENCODING_AES_KEY = os.environ.get("WECOM_ENCODING_AES_KEY", "")

# AI 配置
AI_MODE = os.environ.get("AI_MODE", "cloud_only")  # 企业微信用云端模型更稳定
PORT = int(os.environ.get("PORT", "5050"))

# ==================== 初始化 AI 模块 ====================

import config  # noqa: F401 — 加载 .env
from model_router import ModelRouter
from memory import MemoryStore
from actions import ComputerActions

router = ModelRouter(mode=AI_MODE)
memory = MemoryStore()
actions = ComputerActions()

user_sessions: dict = {}
MAX_HISTORY = 10

stats = {
    "received": 0,
    "sent": 0,
    "cmds": 0,
    "start": datetime.now().isoformat(),
}


def call_ai(user_id: str, text: str) -> str:
    """调用 AI"""
    try:
        if user_id not in user_sessions:
            user_sessions[user_id] = []

        history = user_sessions[user_id]

        memories = memory.list_memories() or []
        mem_ctx = ""
        if memories:
            mem_ctx = "已知信息:\n" + "\n".join(f"- {m['key']}: {m['value']}" for m in memories[:5])

        system = f"""你是企业微信 AI 助手。回复简洁友好，不超过 500 字。

{mem_ctx if mem_ctx else ''}

电脑操作指令（输出格式 [CMD:类型]参数[/CMD]）：
screenshot, open_url, open_program, sysinfo, volume(up/down/mute), lock_screen, clipboard, get_processes, kill_process, run_command, list_files, create_file(路径|内容), read_file, press_keys, type_text, get_time, notify(标题|内容), remember(键|值), recall, forget, search

当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})

        result = router.chat(messages=messages)

        if result.get("success"):
            reply = result["content"]
            print(f"[AI] {result.get('source')}/{result.get('model')}")
        else:
            reply = f"AI 暂时不可用: {result.get('error')}"

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        if len(history) > MAX_HISTORY * 2:
            user_sessions[user_id] = history[-MAX_HISTORY * 2:]

        return reply
    except Exception as e:
        print(f"[AI错误] {e}")
        traceback.print_exc()
        return f"出错了: {e}"


def parse_and_execute(reply: str):
    """解析并执行 CMD 指令"""
    m = re.search(r'\[CMD:(\w+)\](.*?)\[/CMD\]', reply)
    if not m:
        return reply, None

    cmd_type, params = m.group(1), m.group(2).strip()
    clean = re.sub(r'\[CMD:\w+\].*?\[/CMD\]', '', reply).strip()

    result = None
    try:
        if cmd_type == "screenshot":
            result = actions.screenshot(); stats["cmds"] += 1
        elif cmd_type == "open_url":
            result = actions.open_url(params); stats["cmds"] += 1
        elif cmd_type == "open_program":
            result = actions.open_program(params); stats["cmds"] += 1
        elif cmd_type == "sysinfo":
            result = actions.system_info(); stats["cmds"] += 1
        elif cmd_type == "volume":
            result = actions.volume_control(params); stats["cmds"] += 1
        elif cmd_type == "lock_screen":
            result = actions.lock_screen(); stats["cmds"] += 1
        elif cmd_type == "clipboard":
            result = actions.clipboard_read() if not params else actions.clipboard_write(params); stats["cmds"] += 1
        elif cmd_type == "get_processes":
            result = actions.get_processes(params); stats["cmds"] += 1
        elif cmd_type == "kill_process":
            result = actions.kill_process(params); stats["cmds"] += 1
        elif cmd_type == "run_command":
            result = actions.run_command(params); stats["cmds"] += 1
        elif cmd_type == "list_files":
            result = actions.list_files(params); stats["cmds"] += 1
        elif cmd_type == "create_file":
            result = actions.create_file(params); stats["cmds"] += 1
        elif cmd_type == "read_file":
            result = actions.read_file(params); stats["cmds"] += 1
        elif cmd_type == "press_keys":
            result = actions.press_keys(params); stats["cmds"] += 1
        elif cmd_type == "type_text":
            result = actions.type_text(params); stats["cmds"] += 1
        elif cmd_type == "get_time":
            result = actions.get_time(); stats["cmds"] += 1
        elif cmd_type == "notify":
            p = params.split("|", 1)
            result = actions.send_notification(p[0].strip(), p[1].strip() if len(p) > 1 else ""); stats["cmds"] += 1
        elif cmd_type == "remember":
            p = params.split("|", 1)
            if len(p) >= 2:
                memory.set_memory(p[0].strip(), p[1].strip())
                result = f"已记住: {p[0].strip()}"; stats["cmds"] += 1
        elif cmd_type == "recall":
            val = memory.get_memory(params)
            result = f"回忆 '{params}': {val}" if val else f"没有关于 '{params}' 的记忆"
        elif cmd_type == "forget":
            memory.delete_memory(params)
            result = f"已忘记: {params}"; stats["cmds"] += 1
        elif cmd_type == "search":
            try:
                from search import WebSearch
                result = WebSearch().search_and_summarize(params)
            except ImportError:
                result = f"搜索: {params} (搜索模块未加载)"
        else:
            result = f"未知指令: {cmd_type}"
    except Exception as e:
        result = f"执行失败: {e}"
        print(f"[CMD错误] {cmd_type}: {e}")

    if result:
        print(f"[CMD] {cmd_type}: {str(result)[:100]}")
    return clean, result


# ==================== 企业微信 Webhook 发送 ====================

def send_webhook_message(content: str, msg_type: str = "text",
                          mentioned_list: list = None, mentioned_mobile_list: list = None):
    """通过群机器人 Webhook 发送消息"""
    if not WECOM_WEBHOOK:
        print("[发送] Webhook 未配置，跳过发送")
        return False

    content = content[:2048] if len(content) > 2048 else content

    if msg_type == "markdown":
        body = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
    else:
        body = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": mentioned_list or [],
                "mentioned_mobile_list": mentioned_mobile_list or [],
            }
        }

    try:
        r = requests.post(WECOM_WEBHOOK, json=body, timeout=10)
        result = r.json()
        if result.get("errcode") == 0:
            print(f"[发送] -> 群聊: {content[:80]}")
            return True
        else:
            print(f"[发送失败] {result}")
            return False
    except Exception as e:
        print(f"[发送异常] {e}")
        return False


# ==================== 企业微信消息加解密 ====================

def wecom_decrypt_msg(encrypt: str, msg_signature: str, timestamp: str, nonce: str) -> str:
    """
    解密企业微信回调消息
    需要 WECOM_ENCODING_AES_KEY 配置
    """
    if not WECOM_ENCODING_AES_KEY:
        print("[解密] 未配置 EncodingAESKey，跳过解密")
        return ""

    try:
        from Crypto.Cipher import AES
        import base64
        import struct
        import random

        # AES Key = Base64.decode(EncodingAESKey + "=")
        key = base64.b64decode(WECOM_ENCODING_AES_KEY + "=")
        ciphertext = base64.b64decode(encrypt)

        # AES 解密 (CBC mode, IV = key[:16])
        cipher = AES.new(key, AES.MODE_CBC, key[:16])
        decrypted = cipher.decrypt(ciphertext)

        # PKCS7 unpad
        pad = decrypted[-1]
        decrypted = decrypted[:-pad]

        # 解析: random(16) + msg_len(4) + msg + corpid
        content = decrypted[16:]  # 去掉16字节随机数
        msg_len = struct.unpack(">I", content[:4])[0]
        msg = content[4:4 + msg_len].decode("utf-8")
        corp_id = content[4 + msg_len:].decode("utf-8")

        print(f"[解密] 成功, CorpID: {corp_id}")
        return msg
    except ImportError:
        print("[解密] 需要安装 pycryptodome: pip install pycryptodome")
        return ""
    except Exception as e:
        print(f"[解密失败] {e}")
        traceback.print_exc()
        return ""


# ==================== Flask Web 服务 ====================

app = Flask(__name__)


@app.route("/")
def index():
    """状态页面"""
    mode_name = "群机器人" if WECOM_WEBHOOK else "自建应用"
    webhook_ok = bool(WECOM_WEBHOOK)
    callback_ok = bool(WECOM_CORP_ID and WECOM_AGENT_SECRET and WECOM_ENCODING_AES_KEY)

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>企业微信 AI 助手</title>
    <style>
        body { font-family: 'Microsoft YaHei', sans-serif; max-width: 700px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .card { background: white; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 20px; }
        h1 { color: #07c160; margin-top: 0; }
        .status { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 14px; }
        .ok { background: #e8f5e9; color: #2e7d32; }
        .warn { background: #fff3e0; color: #e65100; }
        .info { margin: 8px 0; color: #666; }
        .divider { border: none; border-top: 1px solid #eee; margin: 20px 0; }
        code { background: #f0f0f0; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
        pre { background: #f8f8f8; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 13px; }
        .section-title { color: #333; font-size: 16px; font-weight: bold; margin-top: 20px; }
        ol { padding-left: 20px; }
        ol li { margin: 8px 0; }
    </style></head>
    <body>
        <div class="card">
            <h1>🤖 企业微信 AI 助手</h1>
            <p>模式: <strong>{{ mode_name }}</strong></p>
            <p>群机器人: <span class="status {{ 'ok' if webhook_ok else 'warn' }}">{{ '已配置' if webhook_ok else '未配置' }}</span></p>
            <p>回调接收: <span class="status {{ 'ok' if callback_ok else 'warn' }}">{{ '已配置' if callback_ok else '未配置' }}</span></p>
            <hr class="divider">
            <p class="info">📨 收到消息: {{ stats.received }}</p>
            <p class="info">📤 发送消息: {{ stats.sent }}</p>
            <p class="info">⚡ 执行指令: {{ stats.cmds }}</p>
            <p class="info">🕐 启动时间: {{ stats.start }}</p>
            <p class="info">🧠 AI 模式: {{ ai_mode }}</p>
        </div>

        {% if not webhook_ok and not callback_ok %}
        <div class="card">
            <h3>📋 快速配置（二选一）</h3>

            <div class="section-title">方式一：群机器人（推荐，最简单）</div>
            <ol>
                <li>打开企业微信 → 创建或进入一个群聊</li>
                <li>群设置（右上角...）→ 群机器人 → 添加机器人</li>
                <li>复制 Webhook 地址（形如 <code>https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx</code>）</li>
                <li>设置环境变量后重启:
                    <pre>set WECOM_WEBHOOK=你的webhook地址</pre>
                </li>
                <li>运行后，在群里发消息程序会通过 Webhook 回复</li>
            </ol>

            <div class="section-title">方式二：自建应用（更强大，支持 @机器人）</div>
            <ol>
                <li>打开 <a href="https://work.weixin.qq.com/" target="_blank">企业微信管理后台</a></li>
                <li>应用管理 → 创建应用 → 获取 CorpID、AgentID、Secret</li>
                <li>配置接收消息回调 URL（需要公网 IP 或隧道）</li>
                <li>设置环境变量:
                    <pre>set WECOM_CORP_ID=你的CorpID
set WECOM_AGENT_SECRET=你的Secret
set WECOM_TOKEN=你的Token
set WECOM_ENCODING_AES_KEY=你的EncodingAESKey</pre>
                </li>
            </ol>
        </div>
        {% endif %}

        {% if webhook_ok %}
        <div class="card">
            <h3>💬 交互式对话</h3>
            <p>在群聊中发消息，AI 会自动回复。也可以在这里直接对话：</p>
            <form id="chatForm" style="display:flex; gap:8px;">
                <input type="text" id="msgInput" placeholder="输入消息..." style="flex:1; padding:10px; border:1px solid #ddd; border-radius:6px; font-size:14px;">
                <button type="submit" style="padding:10px 20px; background:#07c160; color:white; border:none; border-radius:6px; cursor:pointer; font-size:14px;">发送</button>
            </form>
            <div id="chatLog" style="margin-top:16px; max-height:400px; overflow-y:auto; border:1px solid #eee; border-radius:8px; padding:12px;"></div>
        </div>
        <script>
            document.getElementById('chatForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const input = document.getElementById('msgInput');
                const msg = input.value.trim();
                if (!msg) return;
                const log = document.getElementById('chatLog');
                log.innerHTML += `<div style="margin:8px 0;"><b>🧑 你:</b> ${msg}</div>`;
                input.value = '';
                try {
                    const resp = await fetch('/api/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({message: msg})
                    });
                    const data = await resp.json();
                    log.innerHTML += `<div style="margin:8px 0;"><b>🤖 AI:</b> ${data.reply}</div>`;
                    log.scrollTop = log.scrollHeight;
                } catch(err) {
                    log.innerHTML += `<div style="margin:8px 0; color:red;"><b>❌ 错误:</b> ${err}</div>`;
                }
            });
        </script>
        {% endif %}
    </body>
    </html>
    """, mode_name=mode_name, webhook_ok=webhook_ok, callback_ok=callback_ok,
       stats=stats, ai_mode=AI_MODE)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Web 页面直接对话接口"""
    data = request.get_json()
    text = data.get("message", "")
    if not text:
        return jsonify({"reply": "请输入消息"})

    user_id = "web_user"
    reply = call_ai(user_id, text)
    clean_reply, cmd_result = parse_and_execute(reply)

    final = clean_reply
    if cmd_result:
        final += f"\n\n[{str(cmd_result)[:300]}]"

    stats["received"] += 1
    stats["sent"] += 1

    # 同时推送到群机器人
    if WECOM_WEBHOOK:
        send_webhook_message(f"💬 Web端用户: {text}\n\n🤖 {final}")

    return jsonify({"reply": final})


# ==================== 群机器人 Webhook 接收 ====================

@app.route("/webhook/receive", methods=["POST"])
def receive_webhook():
    """
    接收群机器人的消息转发
    需要在企业微信后台配置回调 URL，或使用第三方消息中转
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"errcode": 0, "errmsg": "ok"})

    print(f"[Webhook接收] {json.dumps(data, ensure_ascii=False)[:500]}")

    # 处理来自群机器人的消息（通过消息推送）
    msg_type = data.get("msgtype", "")
    if msg_type == "text":
        text_content = data.get("text", {}).get("content", "")
        from_user = data.get("from", {}).get("userid", "unknown")

        # 去除 @机器人 部分
        text_content = re.sub(r'@\S+\s*', '', text_content).strip()
        if text_content:
            reply = call_ai(from_user, text_content)
            clean_reply, cmd_result = parse_and_execute(reply)
            final = clean_reply
            if cmd_result:
                final += f"\n\n[{str(cmd_result)[:300]}]"
            send_webhook_message(final)
            stats["received"] += 1
            stats["sent"] += 1

    return jsonify({"errcode": 0, "errmsg": "ok"})


# ==================== 企业微信回调（自建应用） ====================

@app.route("/webhook/wecom", methods=["GET", "POST"])
def wecom_callback():
    """企业微信自建应用回调"""
    if request.method == "GET":
        # URL 验证
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echostr = request.args.get("echostr", "")

        if not WECOM_ENCODING_AES_KEY:
            print("[回调验证] 未配置 EncodingAESKey")
            return "not configured", 500

        try:
            decrypted = wecom_decrypt_msg(echostr, msg_signature, timestamp, nonce)
            print(f"[回调验证] 成功: {decrypted}")
            return decrypted
        except Exception as e:
            print(f"[回调验证失败] {e}")
            return str(e), 500

    # POST: 接收消息
    try:
        xml_data = request.data.decode("utf-8")
        print(f"[回调消息] XML: {xml_data[:300]}")

        root = ET.fromstring(xml_data)

        # 加密消息需要解密
        encrypt_elem = root.find("Encrypt")
        if encrypt_elem is not None:
            encrypt = encrypt_elem.text
            msg_signature = request.args.get("msg_signature", "")
            timestamp = request.args.get("timestamp", "")
            nonce = request.args.get("nonce", "")

            decrypted_xml = wecom_decrypt_msg(encrypt, msg_signature, timestamp, nonce)
            if decrypted_xml:
                root = ET.fromstring(decrypted_xml)

        msg_type = root.find("MsgType")
        msg_type = msg_type.text if msg_type is not None else ""

        if msg_type == "text":
            from_user = root.find("FromUserName").text
            content = root.find("Content").text

            # 去除 @机器人 前缀
            content = re.sub(r'@\S+\s*', '', content).strip()

            if content:
                print(f"[收到] {from_user}: {content}")
                stats["received"] += 1

                reply = call_ai(from_user, content)
                clean_reply, cmd_result = parse_and_execute(reply)
                final = clean_reply
                if cmd_result:
                    final += f"\n\n[{str(cmd_result)[:300]}]"

                # 通过群机器人回复（或自建应用 API）
                send_webhook_message(final)
                stats["sent"] += 1

        return "success"
    except Exception as e:
        print(f"[回调错误] {e}")
        traceback.print_exc()
        return "error", 500


# ==================== 启动 ====================

def main():
    print("=" * 55)
    print("  企业微信 AI 助手")
    print("=" * 55)
    print(f"  服务端口: {PORT}")
    print(f"  AI 模式: {AI_MODE}")
    print(f"  群机器人: {'已配置' if WECOM_WEBHOOK else '未配置'}")
    print(f"  自建应用: {'已配置' if WECOM_CORP_ID else '未配置'}")
    print("=" * 55)
    print()

    if not WECOM_WEBHOOK and not WECOM_CORP_ID:
        print("  ⚠ 未配置任何企业微信接入方式！")
        print()
        print("  【推荐】群机器人方式（最简单）:")
        print("  1. 企业微信 → 群聊 → 群设置 → 群机器人 → 添加")
        print("  2. 复制 Webhook 地址")
        print("  3. 设置环境变量:")
        print("     set WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx")
        print("  4. 重新运行本程序")
        print()

    if WECOM_WEBHOOK:
        print(f"  Webhook: {WECOM_WEBHOOK[:60]}...")
        print("  在群聊中发送消息，AI 会自动回复")
        print()

    print("  打开 http://localhost:5050/ 查看状态页面")
    print("  按 Ctrl+C 停止服务")
    print("=" * 55)
    print()

    # 启动时发送上线通知
    if WECOM_WEBHOOK:
        send_webhook_message(
            f"🤖 AI 助手已上线\n\n"
            f"模式: {AI_MODE}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"直接发消息即可对话，支持电脑操作指令"
        )

    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
