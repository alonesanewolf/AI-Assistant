"""
永久记忆模块 - 基于 SQLite 的对话记忆存储
支持增删改查、按时间检索、记忆摘要等功能
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional


DB_FILE = "assistant_memory.db"


class MemoryStore:
    """SQLite 记忆存储"""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # 支持并发读写
        return conn

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    # ========== 对话记录 ==========

    def add_message(self, role: str, content: str) -> int:
        """添加一条对话消息"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (role, content) VALUES (?, ?)",
                (role, content),
            )
            conn.commit()
            return cursor.lastrowid

    def get_recent_messages(self, limit: int = 20) -> list:
        """获取最近的对话消息"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        # 反转回时间顺序
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_conversations(self) -> None:
        """清除所有对话记录"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM conversations")
            conn.commit()

    def get_conversation_count(self) -> int:
        """获取对话消息总数"""
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM conversations").fetchone()
            return row["cnt"]

    # ========== 键值记忆 ==========

    def set_memory(self, key: str, value: str, category: str = "general") -> None:
        """存储一条键值记忆（记住用户偏好等）"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO memory_items (key, value, category, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value, category))
            conn.commit()

    def get_memory(self, key: str) -> Optional[str]:
        """获取一条记忆"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM memory_items WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def delete_memory(self, key: str) -> bool:
        """删除一条记忆"""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM memory_items WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def list_memories(self, category: Optional[str] = None) -> list:
        """列出所有记忆"""
        with self._get_conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT key, value, category, updated_at FROM memory_items WHERE category = ? ORDER BY updated_at DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, category, updated_at FROM memory_items ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def search_memories(self, query: str) -> list:
        """模糊搜索记忆"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value, category FROM memory_items WHERE key LIKE ? OR value LIKE ?",
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
        return [dict(r) for r in rows]

    def search_conversations(self, query: str, limit: int = 20) -> list:
        """搜索对话历史"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM conversations "
                "WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def export_conversations(self, format: str = "json") -> str:
        """导出对话历史为 JSON 或 Markdown"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM conversations ORDER BY created_at"
            ).fetchall()

        messages = [{"role": r["role"], "content": r["content"], "time": r["created_at"]} for r in rows]

        if format == "json":
            return json.dumps(messages, ensure_ascii=False, indent=2)

        # Markdown 格式
        lines = ["# AI 助手对话记录\n", f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for i, msg in enumerate(messages):
            role = "用户" if msg["role"] == "user" else "AI"
            lines.append(f"## {role} ({msg['time']})\n\n{msg['content']}\n\n---\n")
        return "\n".join(lines)

    def get_statistics(self) -> dict:
        """获取对话统计信息"""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM conversations").fetchone()["cnt"]
            user_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM conversations WHERE role='user'"
            ).fetchone()["cnt"]
            ai_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM conversations WHERE role='assistant'"
            ).fetchone()["cnt"]
            # 按日期统计
            daily = conn.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as cnt
                FROM conversations
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                LIMIT 30
            """).fetchall()
            # 平均消息长度
            avg_len = conn.execute(
                "SELECT AVG(LENGTH(content)) as avg_len FROM conversations"
            ).fetchone()["avg_len"]

        return {
            "total_messages": total,
            "user_messages": user_count,
            "ai_messages": ai_count,
            "avg_message_length": round(avg_len or 0, 1),
            "daily_stats": [{"date": r["date"], "count": r["cnt"]} for r in daily],
        }

    def get_memory_summary(self) -> dict:
        """获取记忆概览"""
        return {
            "conversation_count": self.get_conversation_count(),
            "memory_count": len(self.list_memories()),
            "db_size_kb": round(os.path.getsize(self.db_path) / 1024, 2) if os.path.exists(self.db_path) else 0,
        }

    def clear_all(self) -> None:
        """清除所有数据"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM conversations")
            conn.execute("DELETE FROM memory_items")
            conn.commit()
