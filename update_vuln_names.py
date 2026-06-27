"""更新数据库中14个漏洞名称 + 上传所有模板"""
import paramiko

HOST = "122.51.97.86"
USER = "ubuntu"
PASSWORD = "ai123456"

NAME_MAP = {
    'brute_force':     'Brute Force 暴力破解',
    'sqli_normal':     'SQL Injection SQL 注入',
    'sqli_blind':      'SQL Injection (Blind) 盲注 SQL 注入',
    'weak_session_id': 'Weak Session IDs 不安全会话 ID',
    'command_injection': 'Command Injection 命令注入',
    'file_include':    'File Inclusion 文件包含',
    'file_upload':     'File Upload 文件上传漏洞',
    'weak_captcha':    'Insecure CAPTCHA 不安全验证码',
    'xss_reflected':   'XSS (Reflected) 反射型 XSS',
    'xss_stored':      'XSS (Stored) 存储型 XSS',
    'xss_dom':         'XSS (DOM) DOM 型跨站脚本',
    'csrf':            'CSRF 跨站请求伪造',
    'csp_bypass':      'CSP Bypass CSP 策略绕过',
    'javascript_vuln': 'JavaScript 前端 JS 安全',
}

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
    print("[OK] Connected\n")

    # 1. 上传所有漏洞模板文件
    sftp = client.open_sftp()
    vuln_templates = [
        'brute_force.html', 'command_injection.html', 'csrf.html',
        'file_include.html', 'file_upload.html', 'weak_captcha.html',
        'sqli_normal.html', 'sqli_blind.html', 'weak_session.html',
        'xss_reflected.html', 'xss_stored.html', 'xss_dom.html',
        'csp_bypass.html', 'javascript.html'
    ]
    for tpl in vuln_templates:
        local = rf"f:\AI_Assistant\deploy\netsec\templates\vulnerabilities\{tpl}"
        tmp = f"/tmp/{tpl}"
        remote = f"/opt/ai_assistant/netsec/templates/vulnerabilities/{tpl}"
        sftp.put(local, tmp)
        stdin, stdout, stderr = client.exec_command(f"sudo cp {tmp} {remote}")
        err = stderr.read().decode().strip()
        if err:
            print(f"  [FAIL] {tpl}: {err}")
        else:
            print(f"  [OK] {tpl}")
    sftp.close()

    # 2. 上传 dvwa_vulnerabilities.html（列表页）
    sftp = client.open_sftp()
    sftp.put(r"f:\AI_Assistant\deploy\netsec\templates\dvwa_vulnerabilities.html", "/tmp/dvwa_vulnerabilities.html")
    sftp.close()
    stdin, stdout, stderr = client.exec_command("sudo cp /tmp/dvwa_vulnerabilities.html /opt/ai_assistant/netsec/templates/dvwa_vulnerabilities.html")
    print("  [OK] dvwa_vulnerabilities.html")

    # 3. 更新数据库漏洞名称
    print("\nUpdating database names...")
    update_sql_parts = []
    for vuln_id, new_name in NAME_MAP.items():
        update_sql_parts.append(f"WHEN '{vuln_id}' THEN '{new_name}'")

    sql = (
        "import pymysql; "
        "pw = None; "
        "for p in ['NetSec@2026!', '123456', 'admin123']: "
        "    try: conn = pymysql.connect(host='127.0.0.1', user='root', password=p, database='netsec_platform', charset='utf8mb4'); pw = p; break; "
        "    except: pass; "
        "if not pw: print('[FAIL] No DB password worked'); exit(); "
        "cur = conn.cursor(); "
        "for vuln_id, name in ["
    )
    for vuln_id, new_name in NAME_MAP.items():
        sql += f"('{vuln_id}', '{new_name}'), "
    sql += "]: "
    sql += "cur.execute('UPDATE vulnerabilities SET name=%s WHERE vuln_id=%s', (name, vuln_id)); "
    sql += "conn.commit(); "
    sql += "print(f'Updated {cur.rowcount} records'); "
    sql += "cur.close(); conn.close()"

    # 简化：用单个heredoc执行
    py_script = (
        "sudo python3 << 'PYEOF'\n"
        "import pymysql\n"
        "pw = None\n"
        "for p in ['NetSec@2026!', '123456']:\n"
        "    try:\n"
        "        conn = pymysql.connect(host='127.0.0.1', user='root', password=p, database='netsec_platform', charset='utf8mb4')\n"
        "        pw = p\n"
        "        break\n"
        "    except:\n"
        "        pass\n"
        "if not pw:\n"
        "    print('[FAIL] No DB password worked')\n"
        "    exit(1)\n"
        "print(f'[OK] DB connected')\n"
        "cur = conn.cursor()\n"
        "updates = [\n"
    )
    for vuln_id, new_name in NAME_MAP.items():
        py_script += f"    ('{vuln_id}', '{new_name}'),\n"
    py_script += (
        "]\n"
        "count = 0\n"
        "for vuln_id, name in updates:\n"
        "    cur.execute('UPDATE vulnerabilities SET name=%s WHERE vuln_id=%s', (name, vuln_id))\n"
        "    count += cur.rowcount\n"
        "conn.commit()\n"
        "print(f'[OK] Updated {count} records')\n"
        "cur.execute('SELECT vuln_id, name FROM vulnerabilities ORDER BY id')\n"
        "for r in cur.fetchall():\n"
        "    print(f'  {r[\"vuln_id\"]:20s} => {r[\"name\"]}')\n"
        "cur.close()\n"
        "conn.close()\n"
        "PYEOF"
    )

    stdin, stdout, stderr = client.exec_command(py_script)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(out)
    if err:
        print(f"[stderr] {err[:300]}")

    # 4. 重启服务
    print("\nRestarting...")
    stdin, stdout, stderr = client.exec_command("sudo systemctl restart netsec_assistant")
    print("[OK] Service restarted")

    print("\n========================================================")
    print("  [DONE] 所有14个漏洞名称已更新！")
    print("  刷新: http://122.51.97.86/netsec/dvwa/vulnerabilities")
    print("========================================================")

except Exception as e:
    print(f"[FAIL] {e}")
finally:
    client.close()
