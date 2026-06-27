#!/usr/bin/env python3
"""深度交互检测 - 测试 POST 操作和 API 交互"""
import requests
import re
import sys
import json

BASE = "http://127.0.0.1:5100"
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

def test_post(name, path, data, session, expected_status=(200, 302)):
    try:
        r = session.post(f"{BASE}{path}", data=data, allow_redirects=False)
        ok = r.status_code in expected_status
        print(f"  [{'OK' if ok else 'FAIL'}] POST {name}: {path} -> {r.status_code}")
        return ok
    except Exception as e:
        print(f"  [ERROR] POST {name}: {e}")
        return False

def test_api(name, path, session):
    try:
        r = session.get(f"{BASE}{path}", allow_redirects=False)
        ok = r.status_code == 200
        print(f"  [{'OK' if ok else 'FAIL'}] API {name}: {path} -> {r.status_code}")
        if ok:
            try:
                data = r.json()
                print(f"         Response keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
            except:
                print(f"         Response (text): {r.text[:100]}")
        return ok
    except Exception as e:
        print(f"  [ERROR] API {name}: {e}")
        return False

def test_vuln_interact(name, path, data, session):
    """测试漏洞练习页面的POST交互"""
    try:
        r = session.post(f"{BASE}{path}", data=data, allow_redirects=False)
        ok = r.status_code in (200, 302)
        print(f"  [{'OK' if ok else 'FAIL'}] 交互 {name}: {path} -> {r.status_code}")
        return ok
    except Exception as e:
        print(f"  [ERROR] 交互 {name}: {e}")
        return False

def main():
    s = requests.Session()
    if not login(s):
        print("登录失败，终止测试")
        sys.exit(1)
    print("登录成功，开始深度检测...\n")

    passed = 0
    failed = 0

    # ===== POST 操作 =====
    print("--- POST 操作 ---")
    post_tests = [
        ("暴力破解", "/vulnerabilities/brute_force", {"username": "test", "password": "test"}),
        ("命令注入", "/vulnerabilities/command_injection", {"ip": "127.0.0.1"}),
        ("CSRF", "/vulnerabilities/csrf", {"password_new": "test", "password_conf": "test"}),
        ("文件包含", "/vulnerabilities/file_inclusion", {"page": "file1.php"}),
        ("文件上传", "/vulnerabilities/file_upload", {}),  # 需要文件
        ("SQL注入", "/vulnerabilities/sql_injection", {"id": "1"}),
        ("SQL盲注", "/vulnerabilities/sql_injection_blind", {"id": "1"}),
        ("XSS反射", "/vulnerabilities/xss_reflected", {"name": "test"}),
        ("XSS存储", "/vulnerabilities/xss_stored", {"name": "test", "message": "test"}),
        ("XSS DOM", "/vulnerabilities/xss_dom", {"default": "English"}),
        ("CSP绕过", "/vulnerabilities/csp_bypass", {"include": "test"}),
        ("JS安全", "/vulnerabilities/javascript", {"phrase": "success", "token": "ChangeMe"}),
        ("启动扫描", "/start_scan", {"target": "127.0.0.1", "scan_type": "port"}),
    ]
    for t in post_tests:
        if test_post(t[0], t[1], t[2], s):
            passed += 1
        else:
            failed += 1

    # ===== 通关检测 API =====
    print("\n--- 通关检测 ---")
    vuln_types = ["brute_force", "command_injection", "csrf", "sql_injection"]
    for vt in vuln_types:
        if test_api(f"通关-{vt}", f"/check_pass/{vt}", s):
            passed += 1
        else:
            failed += 1

    # ===== 扫描状态 API =====
    print("\n--- 扫描 API ---")
    api_tests = [
        ("扫描状态", "/scan_status"),
        ("扫描结果-1", "/scan_result/1"),
        ("扫描等级配置", "/scan_level_config"),
    ]
    for t in api_tests:
        if test_api(t[0], t[1], s):
            passed += 1
        else:
            failed += 1

    # ===== 登出 =====
    print("\n--- 登出 ---")
    r = s.get(f"{BASE}/logout", allow_redirects=False)
    if r.status_code == 302:
        print("  [OK] 登出: /logout -> 302")
        passed += 1
    else:
        print(f"  [FAIL] 登出: /logout -> {r.status_code}")
        failed += 1

    # ===== 错误页面 =====
    print("\n--- 错误页面 ---")
    s2 = requests.Session()
    for path in ["/nonexistent_404", "/trigger_500"]:
        r = s2.get(f"{BASE}{path}")
        # 404 或 500 都算正常渲染
        ok = r.status_code in (404, 500)
        print(f"  [{'OK' if ok else 'FAIL'}] {path} -> {r.status_code}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n=== 深度检测结果: {passed} 通过, {failed} 失败 (共 {passed + failed}) ===")
    return failed == 0

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
