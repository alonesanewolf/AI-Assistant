"""
审计日志模块 - 记录所有操作和事件
====================================
功能:
  1. 结构化 JSON 日志（append-only，自动轮转）
  2. 可选 SQLite 持久化
  3. 日志查询与统计 API

日志类型:
  - command_sent    指令已发送
  - command_result  指令执行结果
  - agent_online    Agent 上线
  - agent_offline   Agent 下线
  - ai_chat         AI 对话
  - system          系统事件
  - security        安全事件（拦截/拒绝）
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ==================== 配置 ====================

# 优先使用 config.py 的默认值，环境变量直接覆盖
try:
    from config import AUDIT_DIR as _cfg_audit_dir, AUDIT_MAX_SIZE_MB as _cfg_max_size, AUDIT_SQLITE as _cfg_sqlite
except ImportError:
    _cfg_audit_dir = "audit_logs"
    _cfg_max_size = 50
    _cfg_sqlite = "audit.db"

AUDIT_DIR = Path(os.environ.get("AUDIT_DIR", _cfg_audit_dir))
AUDIT_FILE = AUDIT_DIR / "audit.jsonl"
AUDIT_DB = AUDIT_DIR / "audit.db"
MAX_LOG_SIZE_MB = int(os.environ.get("AUDIT_MAX_SIZE_MB", str(_cfg_max_size)))
ENABLE_SQLITE = os.environ.get("AUDIT_SQLITE", "true").lower() == "true"

_lock = threading.Lock()
_db_conn: Optional[sqlite3.Connection] = None


def _ensure_dir():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _ensure_dir()
        _db_conn = sqlite3.connect(str(AUDIT_DB), check_same_thread=False, timeout=10)
        _db_conn.execute("PRAGMA journal_mode=WAL")  # 支持多线程并发
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_id TEXT DEFAULT '',
                source TEXT DEFAULT '',
                command TEXT DEFAULT '',
                params TEXT DEFAULT '',
                result TEXT DEFAULT '',
                success INTEGER DEFAULT 1,
                agent_id TEXT DEFAULT '',
                task_id TEXT DEFAULT '',
                extra TEXT DEFAULT '{}'
            )
        """)
        _db_conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(timestamp)")
        _db_conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_logs(event_type)")
        _db_conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_logs(task_id)")
        _db_conn.commit()
    return _db_conn


def _rotate_if_needed():
    """日志文件超过大小限制时轮转（保留最近 3 个备份）"""
    if not AUDIT_FILE.exists():
        return
    size_mb = AUDIT_FILE.stat().st_size / (1024 * 1024)
    if size_mb < MAX_LOG_SIZE_MB:
        return
    for i in range(2, 0, -1):
        old = AUDIT_DIR / f"audit.{i}.jsonl"
        new = AUDIT_DIR / f"audit.{i + 1}.jsonl"
        if old.exists():
            if new.exists():
                new.unlink()
            old.rename(new)
    backup = AUDIT_DIR / "audit.1.jsonl"
    if backup.exists():
        backup.unlink()
    AUDIT_FILE.rename(backup)


def log_event(
    event_type: str,
    user_id: str = "",
    source: str = "",
    command: str = "",
    params: str = "",
    result: str = "",
    success: bool = True,
    agent_id: str = "",
    task_id: str = "",
    **extra,
) -> dict:
    """记录一条审计事件。返回记录的 dict"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "user_id": user_id,
        "source": source,
        "command": command,
        "params": params,
        "result": result[:500] if result else "",  # 截断长结果
        "success": 1 if success else 0,
        "agent_id": agent_id,
        "task_id": task_id,
        "extra": json.dumps(extra, ensure_ascii=False) if extra else "{}",
    }

    # 写入 JSONL 文件
    with _lock:
        _ensure_dir()
        _rotate_if_needed()
        try:
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[Audit] JSONL 写入失败: {e}")

        # 写入 SQLite
        if ENABLE_SQLITE:
            try:
                db = _get_db()
                db.execute(
                    """INSERT INTO audit_logs 
                       (timestamp, event_type, user_id, source, command, params, 
                        result, success, agent_id, task_id, extra)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry["timestamp"], entry["event_type"], entry["user_id"],
                        entry["source"], entry["command"], entry["params"],
                        entry["result"], entry["success"], entry["agent_id"],
                        entry["task_id"], entry["extra"],
                    ),
                )
                db.commit()
            except Exception as e:
                print(f"[Audit] SQLite 写入失败: {e}")

    return entry


# ==================== 便捷函数 ====================

def log_command_sent(task_id: str, command: str, params: str, source: str,
                     session_id: str = "", agent_id: str = ""):
    return log_event("command_sent", command=command, params=params,
                     task_id=task_id, source=source, user_id=session_id,
                     agent_id=agent_id)


def log_command_result(task_id: str, command: str, result: str, success: bool,
                       agent_id: str = "", session_id: str = ""):
    return log_event("command_result", command=command, result=result,
                     task_id=task_id, success=success, agent_id=agent_id,
                     user_id=session_id)


def log_agent_event(event_type: str, agent_id: str, agent_name: str = "",
                    hostname: str = "", **extra):
    return log_event(event_type, agent_id=agent_id, extra={"name": agent_name,
                     "hostname": hostname, **extra})


def log_ai_chat(session_id: str, source: str, user_message: str,
                reply: str, model: str = ""):
    return log_event("ai_chat", user_id=session_id, source=source,
                     params=user_message[:200], result=reply[:200],
                     extra={"model": model} if model else {})


def log_security(action: str, detail: str, agent_id: str = "", source: str = ""):
    return log_event("security", command=action, result=detail,
                     agent_id=agent_id, source=source, success=False)


def log_system(msg: str, **extra):
    return log_event("system", result=msg, extra=extra)


# ==================== 查询接口 ====================

def query_logs(
    event_type: str = "",
    limit: int = 100,
    offset: int = 0,
    task_id: str = "",
    hours: int = 24,
) -> list:
    """查询审计日志"""
    if not ENABLE_SQLITE:
        return _query_jsonl(event_type, limit, offset, task_id, hours)

    try:
        db = _get_db()
        conditions = ["timestamp >= datetime('now', ? || ' hours')"]
        params = [str(-hours)]

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)

        where = " AND ".join(conditions)
        rows = db.execute(
            f"SELECT * FROM audit_logs WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        columns = ["id", "timestamp", "event_type", "user_id", "source",
                   "command", "params", "result", "success", "agent_id",
                   "task_id", "extra"]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"[Audit] 查询失败: {e}")
        return []


def _query_jsonl(event_type: str, limit: int, offset: int,
                 task_id: str, hours: int) -> list:
    """从 JSONL 文件查询（SQLite 不可用时的回退方案）"""
    if not AUDIT_FILE.exists():
        return []
    cutoff = time.time() - hours * 3600
    results = []
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                if ts < cutoff:
                    continue
                if event_type and entry.get("event_type") != event_type:
                    continue
                if task_id and entry.get("task_id") != task_id:
                    continue
                results.append(entry)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    results.reverse()
    return results[offset:offset + limit]


def get_stats(hours: int = 24) -> dict:
    """获取审计统计信息"""
    if not ENABLE_SQLITE:
        return {"error": "SQLite audit disabled", "hours": hours}

    try:
        db = _get_db()
        total = db.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE timestamp >= datetime('now', ? || ' hours')",
            [str(-hours)],
        ).fetchone()[0]

        type_counts = {}
        for row in db.execute(
            "SELECT event_type, COUNT(*) FROM audit_logs "
            "WHERE timestamp >= datetime('now', ? || ' hours') "
            "GROUP BY event_type",
            [str(-hours)],
        ):
            type_counts[row[0]] = row[1]

        success_rate = db.execute(
            "SELECT ROUND(100.0 * SUM(success) / COUNT(*), 1) FROM audit_logs "
            "WHERE timestamp >= datetime('now', ? || ' hours')",
            [str(-hours)],
        ).fetchone()[0] or 0

        return {
            "hours": hours,
            "total_events": total,
            "by_type": type_counts,
            "success_rate": success_rate,
        }
    except Exception as e:
        return {"error": str(e), "hours": hours}
