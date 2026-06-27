"""
电脑操作模块 - 打开网页、程序、创建文件、截图等功能
"""

import os
import webbrowser
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class ComputerActions:
    """电脑操作集合"""

    # ========== 打开网页 ==========

    @staticmethod
    def open_url(url: str) -> str:
        """在默认浏览器中打开网页"""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return f"已在浏览器中打开: {url}"
        except Exception as e:
            return f"打开网页失败: {e}"

    # ========== 打开程序 ==========

    @staticmethod
    def open_program(program_name: str) -> str:
        """打开系统程序（如 notepad, calc, mspaint 等）"""
        try:
            if sys.platform == "win32":
                # Windows: 尝试直接运行
                subprocess.Popen(program_name, shell=True)
            else:
                subprocess.Popen([program_name])
            return f"已启动程序: {program_name}"
        except FileNotFoundError:
            return f"找不到程序: {program_name}，请确认程序名称正确"
        except Exception as e:
            return f"启动程序失败: {e}"

    @staticmethod
    def open_file_with_default(file_path: str) -> str:
        """用系统默认程序打开文件"""
        path = Path(file_path)
        if not path.exists():
            return f"文件不存在: {file_path}"
        try:
            os.startfile(str(path.absolute())) if sys.platform == "win32" else webbrowser.open(str(path.absolute()))
            return f"已打开文件: {file_path}"
        except Exception as e:
            return f"打开文件失败: {e}"

    # ========== 文件操作 ==========

    @staticmethod
    def create_file(file_path: str, content: str = "") -> str:
        """创建文件并写入内容"""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"文件已创建: {file_path}"
        except Exception as e:
            return f"创建文件失败: {e}"

    @staticmethod
    def read_file(file_path: str) -> str:
        """读取文件内容"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"文件不存在: {file_path}"
        except Exception as e:
            return f"读取文件失败: {e}"

    @staticmethod
    def list_files(directory: str = ".") -> str:
        """列出目录中的文件"""
        try:
            path = Path(directory)
            if not path.exists():
                return f"目录不存在: {directory}"
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            lines = []
            for item in items:
                prefix = "[DIR]" if item.is_dir() else "[FILE]"
                lines.append(f"  {prefix}  {item.name}")
            return "\n".join(lines) if lines else "目录为空"
        except Exception as e:
            return f"列出文件失败: {e}"

    # ========== 截图 ==========

    @staticmethod
    def take_screenshot(save_path: Optional[str] = None) -> str:
        """截取全屏并保存"""
        try:
            import pyautogui
            if save_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = f"screenshot_{timestamp}.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(save_path)
            return f"截图已保存: {save_path}"
        except ImportError:
            return "截图功能需要安装 pyautogui 包: pip install pyautogui"
        except Exception as e:
            return f"截图失败: {e}"

    # ========== 系统信息 ==========

    @staticmethod
    def get_system_info() -> str:
        """获取基本系统信息"""
        import platform
        info = [
            f"操作系统: {platform.system()} {platform.release()}",
            f"处理器: {platform.processor()}",
            f"Python 版本: {sys.version.split()[0]}",
            f"当前目录: {os.getcwd()}",
        ]
        return "\n".join(info)

    # ========== 执行命令 ==========

    @staticmethod
    def run_command(command: str) -> str:
        """执行系统命令并返回输出（含安全校验）"""
        # 安全检查：拒绝危险命令
        dangerous_patterns = [
            r"\brm\s+-rf\b", r"\bdel\s+/[fFsS]", r"\bformat\s+[c-zC-Z]:",
            r"\bshutdown\b", r"\brestart\b", r"\bdrop\s+database\b",
            r"\bdrop\s+table\b", r"\btruncate\s+table\b", r">\s*/dev/",
            r"\bdd\s+if=", r"\bchmod\s+777\b",
        ]
        import re as _re_inner
        cmd_lower = command.lower().strip()
        for pattern in dangerous_patterns:
            if _re_inner.search(pattern, cmd_lower):
                return f"[安全拦截] 拒绝执行危险命令: {command[:80]}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout.strip() or result.stderr.strip()
            return output if output else "命令执行完毕（无输出）"
        except subprocess.TimeoutExpired:
            return "命令执行超时（30秒）"
        except Exception as e:
            return f"执行命令失败: {e}"

    # ========== 桌面通知 ==========

    @staticmethod
    def send_notification(title: str, message: str) -> str:
        """发送桌面通知"""
        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                timeout=5,
            )
            return f"通知已发送: {title}"
        except ImportError:
            return "通知功能需要安装 plyer 包: pip install plyer"
        except Exception as e:
            return f"发送通知失败: {e}"

    # ========== 剪贴板操作 ==========

    @staticmethod
    def clipboard_read() -> str:
        """读取剪贴板内容"""
        try:
            import pyperclip
            content = pyperclip.paste()
            if content:
                return f"剪贴板内容 ({len(content)} 字符):\n{content[:500]}"
            return "剪贴板为空"
        except ImportError:
            return "需要安装 pyperclip: pip install pyperclip"
        except Exception as e:
            return f"读取剪贴板失败: {e}"

    @staticmethod
    def clipboard_write(text: str) -> str:
        """写入内容到剪贴板"""
        try:
            import pyperclip
            pyperclip.copy(text)
            return f"已写入剪贴板 ({len(text)} 字符)"
        except ImportError:
            try:
                import subprocess
                subprocess.run(["clip"], input=text, text=True, shell=True)
                return f"已写入剪贴板"
            except Exception as e:
                return f"写入剪贴板失败: {e}"
        except Exception as e:
            return f"写入剪贴板失败: {e}"

    # ========== 音量控制 ==========

    @staticmethod
    def volume_control(action: str) -> str:
        """音量控制: up/down/mute/status"""
        action = action.strip().lower()
        try:
            if sys.platform == "win32":
                import ctypes
                VK_VOLUME_UP = 0xAF
                VK_VOLUME_DOWN = 0xAE
                VK_VOLUME_MUTE = 0xAD

                if action == "up":
                    ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0x0002, 0)
                    return "音量已增大"
                elif action == "down":
                    ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0x0002, 0)
                    return "音量已减小"
                elif action == "mute":
                    ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0x0002, 0)
                    return "已切换静音"
                elif action == "status":
                    return "Windows 音量状态（无法精确读取，请使用 up/down/mute 控制）"
                else:
                    return f"不支持的音量操作: {action}，支持: up / down / mute / status"
            else:
                import subprocess
                if action == "up":
                    subprocess.run(["amixer", "set", "Master", "5%+"], capture_output=True)
                elif action == "down":
                    subprocess.run(["amixer", "set", "Master", "5%-"], capture_output=True)
                elif action == "mute":
                    subprocess.run(["amixer", "set", "Master", "toggle"], capture_output=True)
                return f"音量操作: {action}"
        except Exception as e:
            return f"音量控制失败: {e}"

    # ========== 锁屏 ==========

    @staticmethod
    def lock_screen() -> str:
        """锁定屏幕"""
        try:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return "屏幕已锁定"
            elif sys.platform == "darwin":
                subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
                return "屏幕已锁定"
            else:
                subprocess.run(["xdg-screensaver", "lock"], capture_output=True)
                return "屏幕已锁定"
        except Exception as e:
            return f"锁定失败: {e}"

    # ========== 进程管理 ==========

    @staticmethod
    def get_processes(filter_name: str = "") -> str:
        """获取进程列表，支持关键词过滤"""
        try:
            if sys.platform == "win32":
                cmd = ["tasklist", "/FO", "CSV", "/NH"]
            else:
                cmd = ["ps", "aux"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            lines = result.stdout.strip().split("\n")
            if filter_name:
                lines = [l for l in lines if filter_name.lower() in l.lower()]
            if len(lines) > 25:
                output = "\n".join(lines[:25])
                output += f"\n... (共 {len(lines)} 个进程，已截断前25条)"
                return output
            return "\n".join(lines) if lines else "无匹配进程"
        except Exception as e:
            return f"获取进程失败: {e}"

    @staticmethod
    def kill_process(process_name: str) -> str:
        """终止进程"""
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", process_name],
                    capture_output=True, text=True, timeout=10,
                )
            else:
                result = subprocess.run(
                    ["pkill", "-f", process_name],
                    capture_output=True, text=True, timeout=10,
                )
            if result.returncode == 0:
                return f"已终止进程: {process_name}"
            return f"未找到进程或终止失败: {process_name}"
        except Exception as e:
            return f"终止进程失败: {e}"

    # ========== 按键模拟 ==========

    @staticmethod
    def press_keys(keys: str) -> str:
        """模拟按键组合: ctrl+c / alt+tab / win+d 等"""
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
            return "需要安装 pyautogui: pip install pyautogui"
        except Exception as e:
            return f"输入失败: {e}"

    # ========== 获取时间 ==========

    @staticmethod
    def get_time() -> str:
        """获取当前日期时间"""
        from datetime import datetime
        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        return f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} {weekdays[now.weekday()]}"
