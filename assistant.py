"""
AI 智能助手 - 主程序
整合双模型路由、记忆、电脑操作、网页搜索、定时任务等功能
支持 DeepSeek（云端）+ Ollama（本地）双模型自动切换
"""

import sys
import io
import re
from datetime import datetime
from typing import Optional

# 修复 Windows GBK 编码问题，强制使用 UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config import MAX_MEMORY_TURNS
from memory import MemoryStore
from actions import ComputerActions
from search import WebSearch
from scheduler import TaskScheduler
from model_router import ModelRouter

# ==================== 系统提示词 ====================

SYSTEM_PROMPT = """你是一个智能电脑助手，拥有以下能力：

1. **电脑操作** - 当用户要求执行操作时，用以下格式回复：
   - 打开网页: [ACTION:open_url]https://example.com[/ACTION]
   - 打开程序: [ACTION:open_program]notepad[/ACTION]
   - 创建文件: [ACTION:create_file]路径|文件内容[/ACTION]
   - 读取文件: [ACTION:read_file]文件路径[/ACTION]
   - 列出文件: [ACTION:list_files]目录路径[/ACTION]
   - 截图: [ACTION:screenshot]保存路径(可选)[/ACTION]
   - 执行命令: [ACTION:run_command]命令[/ACTION]
   - 发送通知: [ACTION:notify]标题|消息内容[/ACTION]
   - 系统信息: [ACTION:sysinfo][/ACTION]

2. **网页搜索** - 当用户要求搜索时，用以下格式回复：
   - 搜索: [ACTION:search]搜索关键词[/ACTION]
   - 抓取网页: [ACTION:fetch]网页URL[/ACTION]

3. **定时任务** - 当用户要求定时执行时，用以下格式回复：
   - 添加间隔任务: [ACTION:schedule_interval]任务名称|秒数|要执行的操作[/ACTION]
   - 添加每日任务: [ACTION:schedule_daily]任务名称|HH:MM|要执行的操作[/ACTION]
   - 查看任务: [ACTION:schedule_list][/ACTION]
   - 删除任务: [ACTION:schedule_remove]任务ID[/ACTION]

4. **记忆管理** - 当用户要求记住某事时：
   - 记住: [ACTION:remember]键名|值内容[/ACTION]
   - 回忆: [ACTION:recall]键名[/ACTION]
   - 忘记: [ACTION:forget]键名[/ACTION]

当用户要求执行上述操作时，请直接使用对应的 ACTION 格式，不要额外解释。
如果只是普通对话，正常回复即可。

当前时间: {current_time}"""


# ==================== 主助手类 ====================

class Assistant:
    """智能助手主类"""

    def __init__(self):
        # 模型路由器（支持 DeepSeek + Ollama 双模型）
        self.router = ModelRouter()
        self.max_turns = MAX_MEMORY_TURNS

        # 功能模块
        self.memory = MemoryStore()
        self.actions = ComputerActions()
        self.scheduler = TaskScheduler()

        # 搜索模块（带 AI 摘要能力）
        self.search = WebSearch(ai_summarizer=self._ai_summarize_search)

        # 启动调度器
        self.scheduler.start()

    # ==================== AI 对话 ====================

    def test_connection(self) -> bool:
        """测试 AI 模型连接"""
        print("[连接测试] 正在测试 AI 模型连接...")
        try:
            messages = [{"role": "user", "content": "请回复'连接成功'"}]
            reply = self.router.chat(messages, temperature=0.1)
            print(f"[连接测试] 响应: {reply[:100]}")
            print(f"[连接测试] ✓ 模型连接正常")
            return True
        except Exception as e:
            print(f"[连接测试] ✗ 连接失败: {e}")
            return False

    def chat(self, user_input: str) -> str:
        """发送消息并获取 AI 回复"""
        # 保存用户消息到数据库
        self.memory.add_message("user", user_input)

        # 构建消息列表
        messages = [{
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
        }]

        # 加载最近的历史对话
        history = self.memory.get_recent_messages(self.max_turns * 2)
        messages.extend(history)

        # 通过模型路由器调用
        reply = self.router.chat(messages)

        # 保存 AI 回复到数据库
        self.memory.add_message("assistant", reply)

        return reply

    def _ai_summarize_search(self, query: str, items: list) -> str:
        """用 AI 对搜索结果做智能摘要"""
        if not items:
            return ""

        # 构建搜索上下文
        context_parts = []
        for i, item in enumerate(items[:3], 1):
            context_parts.append(
                f"{i}. 标题: {item['title']}\n"
                f"   摘要: {item['snippet']}\n"
                f"   链接: {item['link']}"
            )
        context = "\n\n".join(context_parts)

        prompt = (
            f"用户搜索了: \"{query}\"\n\n"
            f"以下是搜索结果:\n{context}\n\n"
            f"请用 2-3 句话简洁地总结这些搜索结果的核心内容，"
            f"并告诉用户最有用的信息是什么。用中文回复。"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            summary = self.router.chat(messages, temperature=0.3)
            return f"📊 搜索结果摘要:\n{summary}"
        except Exception:
            return ""

    # ==================== Action 解析与执行 ====================

    def _parse_actions(self, text: str) -> list:
        """从 AI 回复中解析出所有 ACTION 指令"""
        pattern = r"\[ACTION:(\w+)\](.*?)\[/ACTION\]"
        return re.findall(pattern, text, re.DOTALL)

    def _execute_action(self, action_type: str, params: str) -> str:
        """执行单个操作"""
        params = params.strip()

        # ---- 电脑操作 ----
        if action_type == "open_url":
            return self.actions.open_url(params)

        elif action_type == "open_program":
            return self.actions.open_program(params)

        elif action_type == "create_file":
            parts = params.split("|", 1)
            file_path = parts[0].strip()
            content = parts[1] if len(parts) > 1 else ""
            return self.actions.create_file(file_path, content)

        elif action_type == "read_file":
            return self.actions.read_file(params)

        elif action_type == "list_files":
            directory = params if params else "."
            return self.actions.list_files(directory)

        elif action_type == "screenshot":
            save_path = params if params else None
            return self.actions.take_screenshot(save_path)

        elif action_type == "run_command":
            return self.actions.run_command(params)

        elif action_type == "notify":
            parts = params.split("|", 1)
            title = parts[0].strip()
            message = parts[1].strip() if len(parts) > 1 else ""
            return self.actions.send_notification(title, message)

        elif action_type == "sysinfo":
            return self.actions.get_system_info()

        # ---- 搜索操作 ----
        elif action_type == "search":
            return self.search.search_and_summarize(params)

        elif action_type == "fetch":
            return self.search.fetch_webpage(params)

        # ---- 定时任务 ----
        elif action_type == "schedule_interval":
            parts = params.split("|", 2)
            if len(parts) < 2:
                return "参数不足: schedule_interval 需要 名称|秒数|操作"
            name = parts[0].strip()
            seconds = int(parts[1].strip())
            action_desc = parts[2].strip() if len(parts) > 2 else "无具体操作"

            def make_callback(task_name, desc):
                def callback():
                    print(f"\n[定时任务] {task_name}: {desc}")
                    actions = self._parse_actions(desc)
                    if actions:
                        for at, ap in actions:
                            result = self._execute_action(at, ap)
                            print(f"  结果: {result}")
                return callback

            task_id = self.scheduler.add_interval_task(
                name, make_callback(name, action_desc), seconds
            )
            return f"定时任务已添加: [{task_id}] {name} (每 {seconds} 秒)"

        elif action_type == "schedule_daily":
            parts = params.split("|", 2)
            if len(parts) < 2:
                return "参数不足: schedule_daily 需要 名称|HH:MM|操作"
            name = parts[0].strip()
            time_str = parts[1].strip()
            action_desc = parts[2].strip() if len(parts) > 2 else "无具体操作"

            def make_callback(task_name, desc):
                def callback():
                    print(f"\n[定时任务] {task_name}: {desc}")
                    actions = self._parse_actions(desc)
                    if actions:
                        for at, ap in actions:
                            result = self._execute_action(at, ap)
                            print(f"  结果: {result}")
                return callback

            task_id = self.scheduler.add_daily_task(
                name, make_callback(name, action_desc), time_str
            )
            return f"定时任务已添加: [{task_id}] {name} (每天 {time_str})"

        elif action_type == "schedule_list":
            return self.scheduler.list_tasks()

        elif action_type == "schedule_remove":
            task_id = int(params)
            return self.scheduler.remove_task(task_id)

        # ---- 记忆操作 ----
        elif action_type == "remember":
            parts = params.split("|", 1)
            if len(parts) < 2:
                return "参数不足: remember 需要 键名|值"
            key, value = parts[0].strip(), parts[1].strip()
            self.memory.set_memory(key, value)
            return f"已记住: {key}"

        elif action_type == "recall":
            key = params.strip()
            value = self.memory.get_memory(key)
            return f"{key}: {value}" if value else f"未找到记忆: {key}"

        elif action_type == "forget":
            key = params.strip()
            if self.memory.delete_memory(key):
                return f"已忘记: {key}"
            return f"未找到记忆: {key}"

        else:
            return f"未知操作类型: {action_type}"

    def process_reply(self, reply: str) -> str:
        """处理 AI 回复，执行其中的操作指令"""
        actions = self._parse_actions(reply)

        if not actions:
            return reply

        # 清理回复中的 ACTION 标签
        clean_reply = re.sub(
            r"\[ACTION:\w+\].*?\[/ACTION\]", "", reply, flags=re.DOTALL
        ).strip()

        # 执行所有操作
        results = []
        for action_type, params in actions:
            result = self._execute_action(action_type, params)
            results.append(f"  [{action_type}] {result}")

        # 拼接回复
        parts = []
        if clean_reply:
            parts.append(clean_reply)
        if results:
            parts.append("\n[执行结果]")
            parts.extend(results)

        return "\n".join(parts) if parts else "操作已执行"

    # ==================== 命令处理 ====================

    def handle_command(self, cmd: str) -> Optional[str]:
        """处理内置命令，返回结果字符串；非命令返回 None"""
        cmd = cmd.lower().strip()

        if cmd in ("quit", "exit", "退出"):
            return "QUIT"

        if cmd in ("memory", "history", "记忆", "历史"):
            msgs = self.memory.get_recent_messages(20)
            if not msgs:
                return "当前没有对话历史"
            lines = [f"\n{'='*60}", "  对话历史（最近 20 条）", f"{'='*60}"]
            for i, msg in enumerate(msgs, 1):
                role = "你" if msg["role"] == "user" else "AI"
                content = msg["content"][:80] + "..." if len(msg["content"]) > 80 else msg["content"]
                lines.append(f"  [{i}] {role}: {content}")
            lines.append(f"{'='*60}")
            return "\n".join(lines)

        if cmd in ("clear", "清除", "清空"):
            self.memory.clear_all()
            return "对话记忆已清除"

        if cmd in ("tasks", "任务", "定时任务"):
            return self.scheduler.list_tasks()

        if cmd in ("memories", "记忆库"):
            items = self.memory.list_memories()
            if not items:
                return "记忆库为空"
            lines = ["记忆库:"]
            for item in items:
                lines.append(f"  [{item['category']}] {item['key']}: {item['value']}")
            return "\n".join(lines)

        if cmd in ("status", "状态"):
            summary = self.memory.get_memory_summary()
            return (
                f"[系统状态]\n"
                f"  对话消息: {summary['conversation_count']} 条\n"
                f"  记忆条目: {summary['memory_count']} 条\n"
                f"  定时任务: {self.scheduler.task_count} 个\n"
                f"  数据库: {summary['db_size_kb']} KB"
            )

        if cmd in ("help", "帮助", "?"):
            return (
                "[可用命令]\n"
                "  quit/退出  - 退出程序\n"
                "  memory/历史 - 查看对话历史\n"
                "  clear/清除  - 清除对话记忆\n"
                "  memories/记忆库 - 查看键值记忆\n"
                "  tasks/任务  - 查看定时任务\n"
                "  status/状态 - 查看系统状态\n"
                "  help/帮助   - 显示此帮助\n\n"
                "[智能操作示例]\n"
                "  \"帮我打开百度\" -> 自动打开网页\n"
                "  \"搜索Python教程\" -> 自动搜索\n"
                "  \"记住我的名字是张三\" -> 存入记忆\n"
                "  \"帮我截图\" -> 自动截图保存\n"
                "  \"每天早上9点提醒我开会\" -> 定时任务"
            )

        return None  # 不是命令，是普通对话

    # ==================== 主循环 ====================

    def run(self) -> None:
        """启动交互式对话循环"""
        print("\n" + "=" * 60)
        print("  DeepSeek AI 智能助手")
        print("=" * 60)
        print("  输入 help 查看所有命令和功能")
        print("=" * 60)

        # 测试连接
        if not self.test_connection():
            print("\n[错误] API 连接失败，程序退出。")
            self.scheduler.stop()
            sys.exit(1)

        print("\n开始对话吧！（输入 quit 退出）\n")

        while True:
            try:
                user_input = input("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            if not user_input:
                continue

            # 检查内置命令
            cmd_result = self.handle_command(user_input)
            if cmd_result is not None:
                if cmd_result == "QUIT":
                    print("再见！")
                    break
                print(cmd_result)
                print()
                continue

            # AI 对话
            try:
                print("AI: ", end="", flush=True)
                reply = self.chat(user_input)
                # 处理回复中的操作指令
                processed = self.process_reply(reply)
                print(processed)
                print()
            except Exception as e:
                print(f"\n[错误] 请求失败: {e}")
                print()

        # 清理
        self.scheduler.stop()


def main():
    assistant = Assistant()
    assistant.run()


if __name__ == "__main__":
    main()
