"""一键上传 run.py + 模板 + 清理"""
import paramiko

HOST = "122.51.97.86"
USER = "ubuntu"
PASSWORD = "ai123456"

FILES = [
    (r"f:\AI_Assistant\deploy\netsec\run.py", "/opt/ai_assistant/netsec/run.py"),
    (r"f:\AI_Assistant\deploy\netsec\templates\dvwa_vulnerabilities.html", "/opt/ai_assistant/netsec/templates/dvwa_vulnerabilities.html"),
]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
    print("[OK] Connected\n")

    sftp = client.open_sftp()
    for local, remote in FILES:
        tmp = "/tmp/" + remote.split("/")[-1]
        print(f"Uploading {local.split(chr(92))[-1]}...")
        sftp.put(local, tmp)
        stdin, stdout, stderr = client.exec_command(f"sudo cp {tmp} {remote}")
        err = stderr.read().decode().strip()
        if err:
            print(f"  [FAIL] {err}")
        else:
            print(f"  [OK]")
    sftp.close()

    print("\nRestarting service...")
    stdin, stdout, stderr = client.exec_command("sudo systemctl restart netsec_assistant")
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    print("[OK] Done!")

    print("\n========================================================")
    print("  刷新页面查看效果:")
    print("  http://122.51.97.86/netsec/dvwa/vulnerabilities")
    print("========================================================")

except Exception as e:
    print(f"[FAIL] {e}")
finally:
    client.close()
