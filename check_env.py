import os, subprocess

# 获取进程环境
pid = subprocess.check_output(['pgrep', '-f', 'netsec/run.py']).decode().strip().split('\n')[0]
with open(f'/proc/{pid}/environ', 'rb') as f:
    env_data = f.read().decode('utf-8', errors='replace')
    for line in env_data.split('\x00'):
        if any(k in line for k in ['DEEPSEEK', 'ROUTER', 'MYSQL_PASSWORD', 'MODE']):
            print(line)

print('---')
print('PID:', pid)

# 检查 run.py 中 ModelRouter 调用
run_py = open('/opt/ai_assistant/netsec/run.py').read()
for i, line in enumerate(run_py.split('\n'), 1):
    if 'ModelRouter(mode=' in line:
        print(f'line {i}: {line.strip()}')

# 检查是否有 load_dotenv
if 'load_dotenv' in run_py:
    print('load_dotenv: FOUND in run.py')
else:
    print('load_dotenv: MISSING in run.py')
