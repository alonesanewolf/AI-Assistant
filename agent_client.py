"""
本地 Agent 客户端 - 连接云端大脑，执行操作指令
==================================================
支持指令: open_website, open_app, create_file, screenshot, run_command, get_time,
         file_info, send_file, clipboard, volume_control, system_info, shutdown,
         lock_screen, kill_process, press_keys, mouse_click, type_text

电脑串联功能:
  - 远程命令执行（带安全白名单）
  - 文件信息查询
  - 剪贴板读写
  - 音量控制
  - 系统控制（锁屏、关机）
  - 键盘鼠标模拟
"""

import base64
import io
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import socketio

import config  # noqa: F401 — 加载 .env

# ==================== Windows 编码修复 ====================
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (ValueError, AttributeError):
        pass

# ==================== 配置 ====================

BRAIN_URL = os.environ.get("BRAIN_URL", "http://localhost:5000")
AGENT_NAME = os.environ.get("AGENT_NAME", socket.gethostname())
AGENT_ID = f"agent_{socket.gethostname().lower().replace('-','_')}"

# 远程命令安全白名单（允许执行的命令模式）
COMMAND_WHITELIST = [
    "dir", "ls", "pwd", "cd", "echo", "type", "cat",
    "ipconfig", "ifconfig", "ping", "tracert", "nslookup",
    "tasklist", "ps", "netstat", "whoami", "hostname",
    "python --version", "pip list", "node --version",
    "git status", "git log", "git branch",
    "systeminfo", "wmic cpu", "wmic memorychip",
]

# 危险命令黑名单
COMMAND_BLACKLIST = [
    "rm -rf", "del /f", "format", "shutdown", "restart",
    "drop", "truncate", "> /dev/", "dd if=",
]


def is_command_safe(command: str) -> bool:
    """检查命令是否安全（防止命令注入和串联绕过）"""
    cmd_lower = command.lower().strip()

    # 检测危险分隔符（防止命令串联绕过白名单）
    dangerous_separators = ["&&", "||", ";", "|", "`", "$(", "${"]
    for sep in dangerous_separators:
        if sep in cmd_lower:
            return False

    # 检查黑名单
    for pattern in COMMAND_BLACKLIST:
        if pattern in cmd_lower:
            return False

    # 检查白名单
    if COMMAND_WHITELIST:
        for allowed in COMMAND_WHITELIST:
            if cmd_lower.startswith(allowed.lower()):
                return True
        return False

    return False  # 默认拒绝，除非白名单为空


# ==================== 指令执行器 ====================

class CommandExecutor:
    """本地指令执行（增强版）"""

    @staticmethod
    def open_website(url: str) -> str:
        """在默认浏览器中打开网页"""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return f"已打开网页: {url}"
        except Exception as e:
            return f"打开网页失败: {e}"

    @staticmethod
    def open_app(app_name: str) -> str:
        """打开系统程序"""
        try:
            if sys.platform == "win32":
                subprocess.Popen(app_name, shell=True)
            else:
                subprocess.Popen([app_name])
            return f"已启动程序: {app_name}"
        except FileNotFoundError:
            return f"找不到程序: {app_name}"
        except Exception as e:
            return f"启动失败: {e}"

    @staticmethod
    def create_file(params: str) -> str:
        """创建文件: 路径|内容"""
        parts = params.split("|", 1)
        file_path = parts[0].strip()
        content = parts[1] if len(parts) > 1 else ""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"文件已创建: {file_path}"
        except Exception as e:
            return f"创建文件失败: {e}"

    @staticmethod
    def screenshot(save_path: str = "") -> str:
        """截取全屏，返回 base64 编码的图片数据"""
        try:
            import pyautogui
            img = pyautogui.screenshot()
            # 转换为 base64 用于实时传输
            buffer = io.BytesIO()
            # 压缩质量 70%，减小传输大小
            img.save(buffer, format="JPEG", quality=70, optimize=True)
            b64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
            # 同时保存本地（如果指定了路径）
            if save_path:
                img.save(save_path)
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = f"screenshot_{timestamp}.png"
                img.save(save_path)
            # 返回 base64 数据（前缀标识）
            return f"BASE64_JPEG:{b64_data}"
        except ImportError:
            return "请安装 pyautogui: pip install pyautogui"
        except Exception as e:
            return f"截图失败: {e}"

    @staticmethod
    def run_command(command: str) -> str:
        """执行系统命令（带安全检查）"""
        if not is_command_safe(command):
            return f"[安全拦截] 命令被拒绝执行: {command[:60]}"

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            output = result.stdout.strip() or result.stderr.strip()
            if output:
                # 限制输出长度
                if len(output) > 2000:
                    output = output[:2000] + f"\n... (输出过长，已截断，共 {len(output)} 字符)"
                return output
            return "命令执行完毕（无输出）"
        except subprocess.TimeoutExpired:
            return "命令超时（30秒）"
        except Exception as e:
            return f"执行失败: {e}"

    @staticmethod
    def get_time() -> str:
        """获取当前时间"""
        now = datetime.now()
        weekday_map = {
            0: "星期一", 1: "星期二", 2: "星期三",
            3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日",
        }
        return f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} {weekday_map[now.weekday()]}"

    # ---- 新增指令 ----

    @staticmethod
    def file_info(file_path: str) -> str:
        """获取文件/目录信息"""
        path = Path(file_path.strip())
        if not path.exists():
            return f"路径不存在: {file_path}"

        info = []
        info.append(f"路径: {path.absolute()}")
        info.append(f"类型: {'目录' if path.is_dir() else '文件'}")
        info.append(f"大小: {path.stat().st_size:,} 字节" if path.is_file() else "")

        if path.is_file():
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            info.append(f"修改时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
            info.append(f"扩展名: {path.suffix or '(无)'}")

        if path.is_dir():
            try:
                items = list(path.iterdir())
                files = [f for f in items if f.is_file()]
                dirs = [d for d in items if d.is_dir()]
                info.append(f"包含: {len(dirs)} 个目录, {len(files)} 个文件")
                # 列出内容
                for item in sorted(items)[:20]:
                    prefix = "[DIR]" if item.is_dir() else "[FILE]"
                    info.append(f"  {prefix} {item.name}")
                if len(items) > 20:
                    info.append(f"  ... 还有 {len(items)-20} 个项目")
            except PermissionError:
                info.append("(无权限访问)")

        return "\n".join(filter(None, info))

    @staticmethod
    def read_file_content(file_path: str) -> str:
        """读取文件内容"""
        path = Path(file_path.strip())
        if not path.exists():
            return f"文件不存在: {file_path}"
        if not path.is_file():
            return f"不是文件: {file_path}"
        if path.stat().st_size > 500_000:  # 500KB 限制
            return f"文件太大 ({path.stat().st_size:,} 字节)，拒绝读取"

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > 3000:
                content = content[:3000] + f"\n... (内容过长，已截断，共 {len(content)} 字符)"
            return content
        except UnicodeDecodeError:
            return f"无法解码文件（可能是二进制文件）: {path.suffix}"
        except Exception as e:
            return f"读取失败: {e}"

    @staticmethod
    def clipboard(text: str = "") -> str:
        """剪贴板操作: 空=读取, 非空=写入"""
        try:
            import pyperclip
            if text.strip():
                pyperclip.copy(text)
                return f"已写入剪贴板 ({len(text)} 字符)"
            else:
                content = pyperclip.paste()
                if content:
                    return f"剪贴板内容 ({len(content)} 字符):\n{content[:500]}"
                return "剪贴板为空"
        except ImportError:
            # 回退到 subprocess
            if sys.platform == "win32":
                if text.strip():
                    subprocess.run(["clip"], input=text, text=True, shell=True)
                    return f"已写入剪贴板"
                else:
                    return "需要安装 pyperclip: pip install pyperclip"
            return "剪贴板操作需要安装 pyperclip: pip install pyperclip"

    @staticmethod
    def volume_control(action: str) -> str:
        """音量控制: up/down/mute/50 (设置到50%)"""
        action = action.strip().lower()

        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes

                VK_VOLUME_UP = 0xAF
                VK_VOLUME_DOWN = 0xAE
                VK_VOLUME_MUTE = 0xAD
                KEYEVENTF_KEYUP = 0x0002

                user32 = ctypes.windll.user32

                if action == "up":
                    user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                    user32.keybd_event(VK_VOLUME_UP, 0, KEYEVENTF_KEYUP, 0)
                    return "音量已增大"
                elif action == "down":
                    user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                    user32.keybd_event(VK_VOLUME_DOWN, 0, KEYEVENTF_KEYUP, 0)
                    return "音量已减小"
                elif action == "mute":
                    user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
                    user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_KEYUP, 0)
                    return "已切换静音"
                else:
                    return f"不支持的音量操作: {action} (支持: up/down/mute)"
            else:
                if action == "up":
                    subprocess.run(["amixer", "set", "Master", "5%+"])
                elif action == "down":
                    subprocess.run(["amixer", "set", "Master", "5%-"])
                elif action == "mute":
                    subprocess.run(["amixer", "set", "Master", "toggle"])
                return f"音量操作: {action}"
        except Exception as e:
            return f"音量控制失败: {e}"

    @staticmethod
    def system_info() -> str:
        """获取系统信息"""
        import platform

        info = []
        info.append(f"主机名: {socket.gethostname()}")
        info.append(f"系统: {platform.system()} {platform.release()}")
        info.append(f"架构: {platform.machine()}")
        info.append(f"Python: {platform.python_version()}")
        info.append(f"处理器: {platform.processor()}")

        try:
            import psutil
            info.append(f"CPU: {psutil.cpu_percent(interval=1):.1f}%")
            mem = psutil.virtual_memory()
            info.append(f"内存: {mem.used//(1024**2)}MB / {mem.total//(1024**2)}MB ({mem.percent:.1f}%)")
            disk = psutil.disk_usage("/")
            info.append(f"磁盘: {disk.used//(1024**3)}GB / {disk.total//(1024**3)}GB ({disk.percent:.1f}%)")
            info.append(f"启动时间: {datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')}")
        except ImportError:
            info.append("(安装 psutil 获取更多信息: pip install psutil)")

        return "\n".join(info)

    @staticmethod
    def lock_screen() -> str:
        """锁定屏幕"""
        try:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return "屏幕已锁定"
            elif sys.platform == "darwin":
                subprocess.run(["pmset", "displaysleepnow"])
                return "屏幕已锁定"
            else:
                subprocess.run(["xdg-screensaver", "lock"])
                return "屏幕已锁定"
        except Exception as e:
            return f"锁定失败: {e}"

    @staticmethod
    def kill_process(process_name: str) -> str:
        """终止进程"""
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", process_name],
                    capture_output=True, text=True
                )
            else:
                result = subprocess.run(
                    ["pkill", "-f", process_name],
                    capture_output=True, text=True
                )
            if result.returncode == 0:
                return f"已终止进程: {process_name}"
            return f"未找到进程或终止失败: {process_name}"
        except Exception as e:
            return f"终止失败: {e}"

    @staticmethod
    def press_keys(keys: str) -> str:
        """模拟按键: ctrl+c / alt+tab / enter / esc 等"""
        try:
            import pyautogui
            key_list = [k.strip().lower() for k in keys.split("+")]
            pyautogui.hotkey(*key_list)
            return f"已按键: {keys}"
        except ImportError:
            return "需要安装 pyautogui: pip install pyautogui"
        except Exception as e:
            return f"按键失败: {e}"

    @staticmethod
    def type_text(text: str) -> str:
        """模拟键盘输入文字"""
        try:
            import pyautogui
            pyautogui.write(text, interval=0.05)
            return f"已输入文字 ({len(text)} 字符)"
        except ImportError:
            return "需要安装 pyautogui"
        except Exception as e:
            return f"输入失败: {e}"

    @staticmethod
    def get_processes(filter_name: str = "") -> str:
        """获取进程列表"""
        try:
            if sys.platform == "win32":
                cmd = ["tasklist", "/FO", "CSV", "/NH"]
            else:
                cmd = ["ps", "aux"]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            lines = result.stdout.strip().split("\n")

            if filter_name:
                lines = [l for l in lines if filter_name.lower() in l.lower()]

            if len(lines) > 20:
                output = "\n".join(lines[:20])
                output += f"\n... (共 {len(lines)} 个进程，已截断)"
                return output
            return "\n".join(lines)
        except Exception as e:
            return f"获取进程失败: {e}"

    # 指令路由表
    ROUTES = {
        # 基础指令
        "open_website": open_website,
        "open_app": open_app,
        "create_file": create_file,
        "screenshot": screenshot,
        "run_command": run_command,
        "get_time": get_time,
        # 增强指令
        "file_info": file_info,
        "read_file": read_file_content,
        "clipboard": clipboard,
        "volume_control": volume_control,
        "system_info": system_info,
        "lock_screen": lock_screen,
        "kill_process": kill_process,
        "press_keys": press_keys,
        "type_text": type_text,
        "get_processes": get_processes,
    }

    @classmethod
    def execute(cls, command: str, params: str) -> tuple:
        """执行指令，返回 (success, result_text)"""
        func = cls.ROUTES.get(command)
        if not func:
            return False, f"未知指令: {command}"

        try:
            if command in ("get_time", "system_info", "lock_screen"):
                result = func()
            elif params:
                result = func(params)
            else:
                result = func()
            return True, result
        except Exception as e:
            return False, str(e)

    @classmethod
    def get_capabilities(cls) -> dict:
        """返回 Agent 的能力列表"""
        caps = {
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
            "hostname": socket.gethostname(),
            "platform": sys.platform,
            "commands": list(cls.ROUTES.keys()),
        }

        # 检测可选能力
        try:
            import pyautogui
            caps["pyautogui"] = True
        except ImportError:
            caps["pyautogui"] = False

        try:
            import pyperclip
            caps["pyperclip"] = True
        except ImportError:
            caps["pyperclip"] = False

        try:
            import psutil
            caps["psutil"] = True
        except ImportError:
            caps["psutil"] = False

        return caps


# ==================== SocketIO 客户端 ====================

class AgentClient:
    """Agent 客户端，连接云端大脑"""

    def __init__(self):
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=999,
            reconnection_delay=3,
            reconnection_delay_max=15,
            logger=False,
            engineio_logger=False,
        )
        self._setup_handlers()

    def _setup_handlers(self):
        """注册事件处理器"""

        @self.sio.on("connect")
        def on_connect():
            print(f"[连接] 已连接到大脑: {BRAIN_URL}")
            # 注册为 Agent
            self.sio.emit("register", {
                "type": "agent",
                "agent_id": AGENT_ID,
                "name": AGENT_NAME,
                "hostname": socket.gethostname(),
            })

        @self.sio.on("disconnect")
        def on_disconnect():
            reason = "未知原因"
            print(f"[连接] 与大脑断开连接 ({reason})")

        @self.sio.on("registered")
        def on_registered(data):
            print(f"[注册] Agent ID: {data.get('agent_id')}, Status: {data.get('status')}")

        @self.sio.on("agent_command")
        def on_agent_command(data):
            """收到大脑发来的指令"""
            task_id = data.get("task_id", "")
            command = data.get("command", "")
            params = data.get("params", "")

            print(f"\n[指令] 任务 {task_id}: {command} {params}")

            # 执行指令
            success, result = CommandExecutor.execute(command, params)

            status = "成功" if success else "失败"
            print(f"[结果] {status}: {result[:100]}")

            # 返回结果给大脑
            self.sio.emit("agent_result", {
                "task_id": task_id,
                "command": command,
                "result": result,
                "success": success,
                "agent_id": AGENT_ID,
            })

        @self.sio.on("agent_capability_request")
        def on_capability_request():
            """大脑请求 Agent 能力信息"""
            caps = CommandExecutor.get_capabilities()
            self.sio.emit("agent_capability", caps)

        @self.sio.on("heartbeat_ack")
        def on_heartbeat_ack(data):
            pass  # 静默处理

    def _heartbeat_loop(self):
        """心跳发送循环"""
        while self.sio.connected:
            time.sleep(30)
            try:
                self.sio.emit("agent_heartbeat", {
                    "agent_id": AGENT_ID,
                    "time": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def run(self):
        """启动 Agent 客户端"""
        caps = CommandExecutor.get_capabilities()
        print("=" * 60)
        print(f"  本地 Agent 客户端 (增强版)")
        print("=" * 60)
        print(f"  Agent ID:     {AGENT_ID}")
        print(f"  Agent 名称:   {AGENT_NAME}")
        print(f"  大脑地址:     {BRAIN_URL}")
        print(f"  主机名:       {socket.gethostname()}")
        print(f"  系统:         {sys.platform}")
        print(f"  支持指令:     {len(caps['commands'])} 种")
        print(f"  PyAutoGUI:    {'可用' if caps.get('pyautogui') else '未安装'}")
        print(f"  Pyperclip:    {'可用' if caps.get('pyperclip') else '未安装'}")
        print(f"  PSUtil:       {'可用' if caps.get('psutil') else '未安装'}")
        print("=" * 60)
        print("  指令列表:", ", ".join(caps['commands']))
        print("=" * 60)

        while True:
            try:
                print(f"\n[连接] 正在连接大脑 {BRAIN_URL} ...")
                self.sio.connect(BRAIN_URL)

                # 启动心跳线程
                import threading
                heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop, daemon=True
                )
                heartbeat_thread.start()

                print("[就绪] 等待指令...\n")
                self.sio.wait()

            except socketio.exceptions.ConnectionError as e:
                print(f"[重连] 连接失败: {e}，5秒后重试...")
                time.sleep(5)
            except KeyboardInterrupt:
                print("\n[退出] Agent 已停止")
                break
            except Exception as e:
                print(f"[错误] {e}，5秒后重试...")
                time.sleep(5)


def main():
    agent = AgentClient()
    agent.run()


if __name__ == "__main__":
    main()
