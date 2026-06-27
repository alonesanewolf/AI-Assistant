"""Upload all 14 vulnerability templates to server and restart service"""
import paramiko, os

HOST = "122.51.97.86"
USER = "ubuntu"
PASSWORD = "ai123456"
LOCAL_DIR = r"f:\AI_Assistant\deploy\netsec\templates\vulnerabilities"
REMOTE_DIR = "/opt/ai_assistant/netsec/templates/vulnerabilities"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

print("Connecting...")
client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
print("[OK] Connected\n")

sftp = client.open_sftp()

files = sorted([f for f in os.listdir(LOCAL_DIR) if f.endswith('.html')])
print(f"Uploading {len(files)} files...\n")

for fname in files:
    local = os.path.join(LOCAL_DIR, fname)
    tmp = f"/tmp/{fname}"
    remote = os.path.join(REMOTE_DIR, fname)
    sftp.put(local, tmp)
    stdin, stdout, stderr = client.exec_command(f"sudo cp {tmp} {remote}")
    err = stderr.read().decode().strip()
    if err:
        print(f"  [FAIL] {fname}: {err}")
    else:
        print(f"  [OK] {fname}")

sftp.close()

print("\nRestarting service...")
stdin, stdout, stderr = client.exec_command("sudo systemctl restart netsec_assistant 2>&1; echo DONE:$?")
print(stdout.read().decode().strip())

client.close()
print("\nDone! Refresh: http://122.51.97.86/netsec/dvwa/vulnerabilities")
