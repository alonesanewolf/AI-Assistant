"""上传所有带快速上手卡片的漏洞模板到服务器"""
import paramiko

HOST = "122.51.97.86"
USER = "ubuntu"
PASSWORD = "ai123456"

TEMPLATES = [
    'brute_force.html', 'weak_captcha.html', 'csrf.html',
    'sqli_normal.html', 'sqli_blind.html', 'command_injection.html',
    'file_include.html', 'file_upload.html',
    'xss_reflected.html', 'xss_stored.html', 'xss_dom.html',
    'csp_bypass.html', 'javascript.html'
]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
    print("[OK] Connected\n")

    sftp = client.open_sftp()
    for tpl in TEMPLATES:
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

    print("\nRestarting service...")
    stdin, stdout, stderr = client.exec_command("sudo systemctl restart netsec_assistant")
    print("[OK] Service restarted")

    print("\n" + "=" * 60)
    print("  DONE! 所有漏洞页面已添加快速上手卡片！")
    print("  http://122.51.97.86/netsec/dvwa/vulnerabilities")
    print("=" * 60)

except Exception as e:
    print(f"[FAIL] {e}")
finally:
    client.close()
