"""上传颜色优化后的模板到服务器"""
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

    # 上传模板文件
    local_file = r"f:\AI_Assistant\deploy\netsec\templates\dvwa_vulnerabilities.html"
    remote_tmp = "/tmp/dvwa_vulnerabilities.html"
    remote_path = "/opt/ai_assistant/netsec/templates/dvwa_vulnerabilities.html"
    
    print("Uploading...")
    sftp = client.open_sftp()
    sftp.put(local_file, remote_tmp)
    sftp.close()
    print(f"[OK] Uploaded")

    print("Deploying...")
    stdin, stdout, stderr = client.exec_command(
        f"sudo cp {remote_tmp} {remote_path} && sudo systemctl restart netsec_assistant && echo '[OK] Done'"
    )
    print(stdout.read().decode().strip())
    err = stderr.read().decode().strip()
    if err:
        print(f"[stderr] {err}")

    print("\n[OK] 部署完成！刷新 http://122.51.97.86/netsec/dvwa/vulnerabilities 查看效果")

except Exception as e:
    print(f"[FAIL] {e}")
finally:
    client.close()
