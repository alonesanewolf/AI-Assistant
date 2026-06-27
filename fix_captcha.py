"""Upload fixed run.py to server and restart"""
import paramiko

HOST = "122.51.97.86"
USER = "ubuntu"
PASSWORD = "ai123456"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

print("Connecting...")
client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
print("[OK] Connected\n")

sftp = client.open_sftp()
local = r"f:\AI_Assistant\deploy\netsec\run.py"
tmp = "/tmp/run.py"
remote = "/opt/ai_assistant/netsec/run.py"

print("Uploading run.py...")
sftp.put(local, tmp)
sftp.close()

stdin, stdout, stderr = client.exec_command(f"sudo cp {tmp} {remote}")
err = stderr.read().decode().strip()
if err:
    print(f"[FAIL] {err}")
else:
    print("[OK] run.py uploaded")

print("\nRestarting service...")
stdin, stdout, stderr = client.exec_command("sudo systemctl restart netsec_assistant 2>&1; echo DONE:$?")
print(stdout.read().decode().strip())

client.close()
print("\nDone! Now try: username=admin, password=admin, captcha=页面显示的验证码")
