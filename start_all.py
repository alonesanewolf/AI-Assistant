"""
AI 助手统一平台 - 一键启动脚本
用法: python start_all.py [选项]
  --web      启动 Web 界面
  --brain    启动云端大脑
  --rag      启动知识库
  --agent    启动本地 Agent
  --all      启动全部
"""

import subprocess, sys, os, time, signal

PROCESSES = {}

def start_service(name, cmd, cwd=None):
    print(f"[启动] {name}...")
    env = os.environ.copy()
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, env=env)
    PROCESSES[name] = p
    time.sleep(2)
    if p.poll() is not None:
        print(f"[错误] {name} 启动失败")
        return False
    print(f"[OK] {name} PID={p.pid}")
    return True

def stop_all():
    print("\n[停止] 正在关闭所有服务...")
    for name, p in list(PROCESSES.items()):
        print(f"  关闭 {name} ({p.pid})...")
        try:
            if sys.platform == "win32":
                p.terminate()
            else:
                p.send_signal(signal.SIGTERM)
        except:
            pass
        try:
            p.wait(timeout=5)
        except:
            try:
                p.kill()
            except:
                pass
    print("[OK] 所有服务已关闭")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    mode = sys.argv[1].lower()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    services = {
        "brain": ("云端大脑", f"{sys.executable} brain.py", script_dir),
        "rag": ("知识库 RAG", f"{sys.executable} app.py", os.path.join(script_dir, "..", "SecureRAG")),
        "web": ("Web 界面", f"{sys.executable} local_assistant.py", script_dir),
    }

    if mode == "--all" or mode == "all":
        targets = list(services.keys())
    else:
        name = mode.replace("--", "")
        if name not in services:
            print(f"未知服务: {name}  可选: {list(services.keys())}")
            return
        targets = [name]

    for target in targets:
        label, cmd, cwd = services[target]
        start_service(label, cmd, cwd)

    print(f"\n[就绪] 服务运行中 (Ctrl+C 停止)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_all()

if __name__ == "__main__":
    main()
