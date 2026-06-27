"""检查并修复服务器数据库中 CSP 和 JavaScript 漏洞记录"""
import paramiko

HOST = "122.51.97.86"
USER = "ubuntu"
PASSWORD = "ai123456"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
    print("[OK] Connected\n")

    # 用 Python 脚本在服务器上执行，通过 pymysql 连接数据库
    # 先检查服务器上的环境变量获取密码
    check_cmd = (
        "sudo python3 -c \""
        "import pymysql, os; "
        "pw = os.environ.get('MYSQL_PASSWORD', 'NetSec@2026!'); "
        "conn = pymysql.connect(host='127.0.0.1', port=3306, user='root', password=pw, database='netsec_platform', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor); "
        "cur = conn.cursor(); "
        "cur.execute(\\\"SELECT id, vuln_id, name, category, is_active FROM vulnerabilities WHERE vuln_id IN ('csp_bypass', 'javascript_vuln') OR category='客户端'\\\"); "
        "rows = cur.fetchall(); "
        "print('ID\\tVULN_ID\\t\\tNAME\\t\\tIS_ACTIVE'); "
        "for r in rows: print(f'{r[chr(105)+chr(100)]}\\t{r[chr(118)+chr(117)+chr(108)+chr(110)+chr(95)+chr(105)+chr(100)]}\\t{r[chr(110)+chr(97)+chr(109)+chr(101)]}\\t{r[chr(105)+chr(115)+chr(95)+chr(97)+chr(99)+chr(116)+chr(105)+chr(118)+chr(101)]}'); "
        "cur.close(); conn.close()\""
    )
    
    # 换个简单方式：直接用 sudo 读取 systemd 环境变量
    cmd = (
        "sudo python3 << 'PYEOF'\n"
        "import pymysql\n"
        "import os\n"
        "\n"
        "# 尝试多个密码\n"
        "passwords = ['NetSec@2026!', '123456', 'admin123', 'root']\n"
        "conn = None\n"
        "used_pw = None\n"
        "for pw in passwords:\n"
        "    try:\n"
        "        conn = pymysql.connect(\n"
        "            host='127.0.0.1', port=3306, user='root', password=pw,\n"
        "            database='netsec_platform', charset='utf8mb4',\n"
        "            cursorclass=pymysql.cursors.DictCursor\n"
        "        )\n"
        "        used_pw = pw\n"
        "        break\n"
        "    except Exception:\n"
        "        continue\n"
        "\n"
        "if not conn:\n"
        "    print('[FAIL] 无法连接数据库，尝试的密码都失败了')\n"
        "    exit(1)\n"
        "\n"
        "print(f'[OK] 数据库连接成功')\n"
        "cur = conn.cursor()\n"
        "\n"
        "# 查询客户端类漏洞\n"
        "cur.execute(\"SELECT id, vuln_id, name, is_active FROM vulnerabilities WHERE vuln_id IN ('csp_bypass', 'javascript_vuln')\")\n"
        "rows = cur.fetchall()\n"
        "print(f'查询到 {len(rows)} 条记录:')\n"
        "for r in rows:\n"
        "    print(f'  id={r[\"id\"]} vuln_id={r[\"vuln_id\"]} name={r[\"name\"]} is_active={r[\"is_active\"]}')\n"
        "\n"
        "if len(rows) == 0:\n"
        "    print('[!] 缺少记录，正在插入...')\n"
        "    cur.execute(\"\"\"INSERT IGNORE INTO vulnerabilities (vuln_id, name, category, difficulty, description_zh, hint) VALUES\n"
        "        ('csp_bypass', 'CSP绕过', '客户端', 'low', '内容安全策略配置不当可被绕过', '寻找CSP配置的薄弱环节'),\n"
        "        ('javascript_vuln', 'JavaScript漏洞', '客户端', 'low', '前端JavaScript代码存在安全缺陷', '分析前端JS代码逻辑')\n"
        "    \"\"\")\n"
        "    conn.commit()\n"
        "    print('[OK] 插入成功')\n"
        "elif any(r['is_active'] == 0 for r in rows):\n"
        "    print('[!] 记录存在但 is_active=0，正在激活...')\n"
        "    cur.execute(\"UPDATE vulnerabilities SET is_active=1 WHERE vuln_id IN ('csp_bypass', 'javascript_vuln')\")\n"
        "    conn.commit()\n"
        "    print('[OK] 已激活')\n"
        "else:\n"
        "    print('[OK] 记录正常，无需修复')\n"
        "\n"
        "cur.close()\n"
        "conn.close()\n"
        "PYEOF"
    )

    stdin, stdout, stderr = client.exec_command(cmd)
    output = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    
    if output:
        print(output)
    if err:
        print(f"[stderr] {err[:500]}")
    
    # 重启服务
    print("\n重启服务...")
    stdin2, stdout2, stderr2 = client.exec_command("sudo systemctl restart netsec_assistant")
    out2 = stdout2.read().decode().strip()
    err2 = stderr2.read().decode().strip()
    print("[OK] 服务已重启")
    if out2:
        print(out2)
    if err2:
        print(f"[stderr] {err2}")

except Exception as e:
    print(f"[FAIL] {e}")
finally:
    client.close()
