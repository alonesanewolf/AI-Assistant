#!/usr/bin/env python3
"""全面页面响应检测 - 检测所有路由返回是否正常"""
import requests
import re
import sys

BASE = "http://127.0.0.1:5100"
PASSWORD = "admin123"

def get_captcha(session):
    r = session.get(f"{BASE}/login")
    m = re.search(r'<div class="captcha-code">([A-Z0-9]{4})</div>', r.text)
    return m.group(1) if m else None

def login(session):
    captcha = get_captcha(session)
    if not captcha:
        print("ERROR: 无法获取验证码")
        return False
    r = session.post(f"{BASE}/login", data={
        'username': 'admin', 'password': PASSWORD, 'captcha': captcha
    }, allow_redirects=False)
    return r.status_code == 302

def test(name, path, session, method='get'):
    try:
        if method == 'get':
            r = session.get(f"{BASE}{path}", allow_redirects=False)
        else:
            r = session.post(f"{BASE}{path}", allow_redirects=False)
        status = "OK" if r.status_code in (200, 302) else f"FAIL({r.status_code})"
        print(f"  [{status}] {name}: {path}")
        return r.status_code in (200, 302)
    except Exception as e:
        print(f"  [ERROR] {name}: {path} - {e}")
        return False

def main():
    s = requests.Session()
    if not login(s):
        print("登录失败，终止测试")
        sys.exit(1)
    print("登录成功，开始检测...\n")

    routes = [
        # 主页
        ("首页", "/"),
        ("index", "/index"),
        ("靶场", "/range"),
        ("模块", "/modules"),

        # 扫描
        ("端口扫描", "/port_scanner"),
        ("网络扫描", "/network_scanner"),
        ("WAF检测", "/waf_scanner"),
        ("指纹识别", "/fingerprint_scanner"),
        ("目录扫描", "/directory_scanner"),
        ("子域名枚举", "/subdomain_scanner"),
        ("三级扫描", "/scan"),
        ("扫描历史", "/scan_history"),

        # 扫描 API
        ("启动扫描", "/start_scan", "post"),
        ("扫描状态", "/scan_status", "get"),

        # DVWA
        ("DVWA概览", "/dvwa_overview"),
        ("DVWA环境", "/dvwa_environment"),
        ("DVWA漏洞", "/dvwa_vulnerabilities"),

        # 漏洞练习
        ("暴力破解", "/vulnerabilities/brute_force"),
        ("命令注入", "/vulnerabilities/command_injection"),
        ("CSRF", "/vulnerabilities/csrf"),
        ("文件包含", "/vulnerabilities/file_inclusion"),
        ("文件上传", "/vulnerabilities/file_upload"),
        ("SQL注入", "/vulnerabilities/sql_injection"),
        ("SQL盲注", "/vulnerabilities/sql_injection_blind"),
        ("XSS反射", "/vulnerabilities/xss_reflected"),
        ("XSS存储", "/vulnerabilities/xss_stored"),
        ("XSS DOM", "/vulnerabilities/xss_dom"),
        ("CSP绕过", "/vulnerabilities/csp_bypass"),
        ("JS安全", "/vulnerabilities/javascript"),

        # 实验室
        ("Vulhub", "/lab_vulhub"),
        ("WebGoat", "/lab_webgoat"),
        ("JuiceShop", "/lab_juiceshop"),
        ("Metasploitable2", "/lab_metasploitable2"),
        ("TryHackMe", "/lab_tryhackme"),
        ("HTB", "/lab_htb"),

        # 管理
        ("进度管理", "/progress"),
        ("题目管理", "/questions"),
        ("用户管理", "/users"),
        ("角色管理", "/roles"),
        ("审计日志", "/audit_logs"),
        ("学习报告", "/report"),

        # AI攻防
        ("AI攻击", "/ai_attack"),

        # 登出
        ("登出", "/logout"),
    ]

    passed = 0
    failed = 0
    for route in routes:
        name = route[0]
        path = route[1]
        method = route[2] if len(route) > 2 else 'get'
        if test(name, path, s, method):
            passed += 1
        else:
            failed += 1

    print(f"\n=== 结果: {passed} 通过, {failed} 失败 (共 {passed + failed}) ===")
    return failed == 0

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
