#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云端大脑 + SecureRAG 一键部署与更新
部署到 /opt/ 目录下
"""

import subprocess, sys, os, shutil, tempfile

REMOTE_HOST = "122.51.97.86"
REMOTE_USER = "root"

# 本地文件 -> 远程路径
FILES = {
    "c:\\AI_Assistant\\brain.py": "/opt/ai_assistant/brain.py",
    "c:\\AI_Assistant\\agent_client.py": "/opt/ai_assistant/agent_client.py",
    "c:\\AI_Assistant\\assistant.py": "/opt/ai_assistant/assistant.py",
    "c:\\AI_Assistant\\config.py": "/opt/ai_assistant/config.py",
    "c:\\AI_Assistant\\start_all.py": "/opt/ai_assistant/start_all.py",
}

def run(cmd):
    print(f">>> {cmd}")
    subprocess.run(cmd, shell=True, check=True)

def main():
    # 上传文件
    for local, remote in FILES.items():
        if os.path.exists(local):
            run(f'scp "{local}" {REMOTE_USER}@{REMOTE_HOST}:{remote}')

    # 重启云端大脑
    run(f'ssh {REMOTE_USER}@{REMOTE_HOST} "fuser -k 5200/tcp 2>/dev/null; sleep 2; cd /opt/ai_assistant && nohup python3 brain.py > /var/log/brain.log 2>&1 & echo Brain PID: \\$!"')

    # 验证
    run(f'ssh {REMOTE_USER}@{REMOTE_HOST} "sleep 3; curl -s http://127.0.0.1:5200/api/health"')

    print("\n部署完成!")

if __name__ == "__main__":
    main()
