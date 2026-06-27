#!/usr/bin/env python3
"""绕过 Nginx 直接测试 Flask 端口，用于区分 Nginx/Flask 问题"""
import requests
import re
import sys

# Flask 直连端口（修改为实际端口）
FLASK_PORT = 5100
BASE = f"http://127.0.0.1:{FLASK_PORT}"
PASSWORD = "admin123"

def get_captcha(session):
    r = session.get(f"{BASE}/login")
    m = re.search(r'<div class="captcha-code">([A-Z0-9]{4})</div>', r.text)
    return m.group(1) if m else None

def login(session):
    captcha = get_captcha(session)
    if not captcha:
        return False
    r = session.post(f"{BASE}/login", data={
        'username': 'admin', 'password': PASSWORD, 'captcha': captcha
    }, allow_redirects=False)
    return r.status_code == 302

def test(path, session, name=""):
    try:
        r = session.get(f"{BASE}{path}", allow_redirects=False)
        ok = r.status_code in (200, 302)
        label = name or path
        print(f"  [{'OK' if ok else 'FAIL'}] {label} -> {r.status_code}")
        return ok
    except Exception as e:
        print(f"  [ERROR] {name or path}: {e}")
        return False

def main():
    s = requests.Session()
    if not login(s):
        print("登录失败，终止测试")
        sys.exit(1)
    print(f"登录成功，直连端口 {FLASK_PORT} 测试...\n")

    pages = [
        "/", "/index", "/range", "/modules",
        "/port_scanner", "/network_scanner", "/scan",
        "/dvwa_overview", "/dvwa_vulnerabilities",
        "/vulnerabilities/sql_injection", "/vulnerabilities/xss_reflected",
        "/lab_vulhub", "/lab_webgoat",
        "/progress", "/questions", "/users", "/audit_logs",
        "/logout",
    ]

    passed = 0
    failed = 0
    for p in pages:
        if test(p, s):
            passed += 1
        else:
            failed += 1

    # 登出后重复登陆测试
    print("\n--- 反复登出/登录测试 ---")
    for i in range(3):
        s2 = requests.Session()
        if login(s2):
            r = s2.get(f"{BASE}/logout", allow_redirects=False)
            print(f"  第{i+1}轮: 登出 -> {r.status_code}")
            if r.status_code == 302:
                passed += 1
            else:
                failed += 1
        else:
            print(f"  第{i+1}轮: 登录失败")
            failed += 1

    print(f"\n=== 直连端口结果: {passed} 通过, {failed} 失败 ===")
    return failed == 0

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
