"""
DeepSeek AI 助手 - 带记忆功能的命令行对话程序
支持命令：quit 退出、memory 查看历史、clear 清除记忆
"""

import json
import os
import sys
from datetime import datetime
from openai import OpenAI

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    MEMORY_FILE,
    MAX_MEMORY_TURNS,
    API_TIMEOUT,
)


class DeepSeekAssistant:
    """DeepSeek AI 助手，支持对话记忆和本地持久化"""

    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=API_TIMEOUT,
        )
        self.model = DEEPSEEK_MODEL
        self.memory_file = MEMORY_FILE
        self.max_turns = MAX_MEMORY_TURNS
        self.conversation_history = []
        self._load_memory()

    # ==================== 记忆管理 ====================

    def _load_memory(self) -> None:
        """从本地 JSON 文件加载对话历史"""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.conversation_history = data.get("messages", [])
                print(f"[记忆] 已加载 {len(self.conversation_history)} 条历史消息")
            except (json.JSONDecodeError, KeyError):
                print("[记忆] 历史文件损坏，将使用空记忆")
                self.conversation_history = []
        else:
            print("[记忆] 未找到历史文件，将创建新记忆")

    def _save_memory(self) -> None:
        """将对话历史保存到本地 JSON 文件"""
        data = {
            "messages": self.conversation_history,
            "last_updated": datetime.now().isoformat(),
            "total_messages": len(self.conversation_history),
        }
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear_memory(self) -> None:
        """清除对话记忆"""
        self.conversation_history = []
        if os.path.exists(self.memory_file):
            os.remove(self.memory_file)
        print("[记忆] 对话记忆已清除")

    def show_memory(self) -> None:
        """显示对话历史"""
        if not self.conversation_history:
            print("[记忆] 当前没有对话历史")
            return

        print(f"\n{'='*60}")
        print(f"  对话历史（共 {len(self.conversation_history)} 条消息）")
        print(f"{'='*60}")
        for i, msg in enumerate(self.conversation_history, 1):
            role = "你" if msg["role"] == "user" else "DeepSeek"
            content = msg["content"]
            # 截断过长的内容
            display = content[:100] + "..." if len(content) > 100 else content
            print(f"  [{i}] {role}: {display}")
        print(f"{'='*60}\n")

    # ==================== API 调用 ====================

    def test_connection(self) -> bool:
        """测试 API 连接是否正常"""
        print("[连接测试] 正在测试 DeepSeek API 连接...")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "你好，请回复'连接成功'"}],
                max_tokens=20,
            )
            reply = response.choices[0].message.content
            print(f"[连接测试] API 响应: {reply}")
            print("[连接测试] ✓ DeepSeek API 连接正常")
            return True
        except Exception as e:
            print(f"[连接测试] ✗ API 连接失败: {e}")
            return False

    def chat(self, user_input: str) -> str:
        """发送消息并获取回复"""
        # 将用户消息加入历史
        self.conversation_history.append({"role": "user", "content": user_input})

        # 只取最近的 N 轮对话（一轮 = 一次问答，即 2 条消息）
        recent_messages = self.conversation_history[-(self.max_turns * 2):]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=recent_messages,
            )
            reply = response.choices[0].message.content

            # 将助手回复加入历史
            self.conversation_history.append({"role": "assistant", "content": reply})

            # 保存到文件
            self._save_memory()

            return reply

        except Exception as e:
            # 出错时移除刚才添加的用户消息
            self.conversation_history.pop()
            raise e

    # ==================== 主循环 ====================

    def run(self) -> None:
        """启动交互式对话循环"""
        print("\n" + "=" * 60)
        print("  🤖 DeepSeek AI 助手")
        print("=" * 60)
        print("  命令:")
        print("    quit   - 退出程序")
        print("    memory - 查看对话历史")
        print("    clear  - 清除对话记忆")
        print("    直接输入文字即可与 AI 对话")
        print("=" * 60)

        # 启动时测试连接
        if not self.test_connection():
            print("\n[错误] API 连接失败，程序退出。请检查 API Key 和网络。")
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

            # 处理命令
            if user_input.lower() == "quit":
                print("再见！")
                break

            if user_input.lower() == "memory":
                self.show_memory()
                continue

            if user_input.lower() == "clear":
                self.clear_memory()
                continue

            # 正常对话
            try:
                print("DeepSeek: ", end="", flush=True)
                reply = self.chat(user_input)
                print(reply)
                print()  # 空行分隔
            except Exception as e:
                print(f"\n[错误] 请求失败: {e}")
                print()


def main():
    assistant = DeepSeekAssistant()
    assistant.run()


if __name__ == "__main__":
    main()
