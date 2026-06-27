#!/usr/bin/env python3
"""重置管理员密码（服务器端执行）"""
import sqlite3
from werkzeug.security import generate_password_hash
import os

DB_PATH = os.environ.get('DB_PATH', '/opt/ai_assistant/ai_assistant.db')
NEW_PASSWORD = os.environ.get('NEW_PASSWORD', 'admin123')

def reset_password():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 查看当前用户
    cursor.execute("SELECT id, username, password_hash FROM users WHERE username = 'admin'")
    user = cursor.fetchone()
    if not user:
        print(f"未找到 admin 用户")
        conn.close()
        return False

    new_hash = generate_password_hash(NEW_PASSWORD)
    cursor.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (new_hash,))
    conn.commit()
    conn.close()

    print(f"管理员密码已重置为: {NEW_PASSWORD}")
    return True

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    reset_password()
