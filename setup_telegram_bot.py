#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot 一键部署脚本
通过 Telegram 用自然语言远程控制你的电脑
"""

import subprocess, sys, os

REMOTE = "root@122.51.97.86"
BRAIN_DIR = "/opt/ai_assistant"

def run_remote(cmd, desc=""):
    print(f"[{desc}] {cmd}")
    result = subprocess.run(f'ssh {REMOTE} "{cmd}"', shell=True,
                           capture_output=True, text=True)
    out = result.stdout.strip()
    if result.returncode != 0:
        print(f"  STDERR: {result.stderr.strip()[:200]}")
    return out

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("=" * 60)
        print("  Telegram Bot 一键部署")
        print("=" * 60)
        print()
        print("步骤1: 创建 Bot 获取 Token")
        print("  1. 在 Telegram 搜索 @BotFather")
        print("  2. 发送 /newbot 并按要求设置名称")
        print("  3. 复制 Bot Token (格式: 123456:ABCdef...)")
        print()
        print("步骤2: 运行本脚本")
        print(f"  set TELEGRAM_BOT_TOKEN=你的token")
        print(f"  python {__file__}")
        print()
        print("步骤3: 在手机 Telegram 搜索你的 Bot，开始对话!")
        return

    print("=" * 60)
    print("  Telegram Bot 部署中...")
    print("=" * 60)

    # 1. 更新 .env 配置
    env_update = f"cd {BRAIN_DIR}/netsec && "
    env_update += "grep -q 'TELEGRAM_BOT_TOKEN=' .env 2>/dev/null && "
    env_update += f"sed -i 's|^#*\\s*TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN={token}|' .env || "
    env_update += f"echo 'TELEGRAM_BOT_TOKEN={token}' >> .env"
    run_remote(env_update, "更新配置")

    # 2. 安装依赖
    run_remote(f"pip3 install python-socketio requests 2>&1 | tail -3", "安装依赖")

    # 3. 上传 telegram_bot.py 到服务器
    local_telegram = os.path.join(os.path.dirname(__file__), "telegram_bot.py")
    if not os.path.exists(local_telegram):
        print("[错误] 找不到 telegram_bot.py")
        sys.exit(1)
    
    subprocess.run(f'scp "{local_telegram}" {REMOTE}:{BRAIN_DIR}/netsec/telegram_bot.py',
                   shell=True, check=True)
    print("[OK] 已上传 telegram_bot.py")

    # 4. 重启云端大脑
    run_remote("fuser -k 5200/tcp 2>/dev/null || true")
    run_remote(f"cd {BRAIN_DIR}/netsec && nohup python3 brain.py > /var/log/brain.log 2>&1 & sleep 4")

    # 5. 验证
    resp = run_remote("curl -s http://127.0.0.1:5200/api/health")
    if "ok" in resp:
        print(f"\n[OK] 云端大脑运行正常! {resp}")
        print(f"\n[Telegram Bot 已部署]")
        print(f"  在手机 Telegram 搜索你的 Bot 即可开始!")
        print(f"  试试说: '现在几点'、'截个屏'、'打开百度'")
    else:
        print(f"\n[警告] 云端大脑可能有异常: {resp}")
        print(f"  查看日志: ssh root@122.51.97.86 tail -30 /var/log/brain.log")

if __name__ == "__main__":
    main()
