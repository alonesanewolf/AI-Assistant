"""
定时任务调度器 - 基于 schedule 库的轻量级任务管理
支持添加、查看、删除定时任务，在后台线程中运行
支持任务持久化存储（JSON 文件）
"""

import json
import os
import threading
import time
import schedule
from datetime import datetime
from typing import Callable, Optional

TASKS_FILE = "scheduled_tasks.json"


class TaskScheduler:
    """定时任务调度器（支持持久化）"""

    def __init__(self, persist: bool = True):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tasks: dict = {}  # task_id -> task_info
        self._task_counter = 0
        self._persist = persist
        self._one_time_tasks: dict = {}  # 一次性任务
        # 加载持久化任务
        self._load_tasks()

    def _run_loop(self) -> None:
        """调度循环（在后台线程中运行）"""
        while self._running:
            schedule.run_pending()
            # 检查一次性任务
            now = datetime.now()
            to_remove = []
            for task_id, task in self._one_time_tasks.items():
                if now >= task["run_at"]:
                    try:
                        task["func"](*task.get("args", ()), **task.get("kwargs", {}))
                    except Exception as e:
                        print(f"[Scheduler] 一次性任务 {task['name']} 执行失败: {e}")
                    to_remove.append(task_id)
            for tid in to_remove:
                del self._one_time_tasks[tid]
            time.sleep(1)

    def start(self) -> None:
        """启动调度器（后台线程）"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    # ========== 持久化 ==========

    def _save_tasks(self) -> None:
        """保存任务信息到文件（仅保存可序列化的元数据）"""
        if not self._persist:
            return
        data = []
        for task_id, task in self._tasks.items():
            data.append({
                "id": task_id,
                "name": task["name"],
                "type": task["type"],
                "seconds": task.get("seconds"),
                "time": task.get("time"),
                "created_at": task["created_at"],
            })
        try:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Scheduler] 保存任务失败: {e}")

    def _load_tasks(self) -> None:
        """从文件加载任务信息（任务函数需要重新注册）"""
        if not os.path.exists(TASKS_FILE):
            return
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                if item["id"] > self._task_counter:
                    self._task_counter = item["id"]
            print(f"[Scheduler] 从文件加载了 {len(data)} 个任务定义")
        except Exception as e:
            print(f"[Scheduler] 加载任务文件失败: {e}")

    # ========== 添加任务 ==========

    def add_interval_task(
        self,
        name: str,
        func: Callable,
        seconds: int,
        *args,
        **kwargs,
    ) -> int:
        """添加间隔执行的任务"""
        self._task_counter += 1
        task_id = self._task_counter

        job = schedule.every(seconds).seconds.do(func, *args, **kwargs)

        self._tasks[task_id] = {
            "id": task_id,
            "name": name,
            "type": "interval",
            "seconds": seconds,
            "job": job,
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "created_at": datetime.now().isoformat(),
        }
        self._save_tasks()
        return task_id

    def add_daily_task(
        self,
        name: str,
        func: Callable,
        time_str: str,
        *args,
        **kwargs,
    ) -> int:
        """
        添加每日定时任务
        time_str: 格式 "HH:MM"，如 "09:00"
        """
        self._task_counter += 1
        task_id = self._task_counter

        job = schedule.every().day.at(time_str).do(func, *args, **kwargs)

        self._tasks[task_id] = {
            "id": task_id,
            "name": name,
            "type": "daily",
            "time": time_str,
            "job": job,
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "created_at": datetime.now().isoformat(),
        }
        self._save_tasks()
        return task_id

    def add_one_time_task(
        self,
        name: str,
        func: Callable,
        run_at: datetime,
        *args,
        **kwargs,
    ) -> int:
        """添加一次性定时任务（指定时间执行一次）"""
        self._task_counter += 1
        task_id = self._task_counter
        self._one_time_tasks[task_id] = {
            "id": task_id,
            "name": name,
            "type": "one_time",
            "run_at": run_at,
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "created_at": datetime.now().isoformat(),
        }
        return task_id

    # ========== 管理任务 ==========

    def remove_task(self, task_id: int) -> str:
        """移除指定任务"""
        if task_id in self._tasks:
            task = self._tasks.pop(task_id)
            schedule.cancel_job(task["job"])
            self._save_tasks()
            return f"任务 '{task['name']}' 已移除"
        if task_id in self._one_time_tasks:
            task = self._one_time_tasks.pop(task_id)
            return f"一次性任务 '{task['name']}' 已移除"
        return f"任务 ID {task_id} 不存在"

    def list_tasks(self) -> str:
        """列出所有任务"""
        all_tasks = list(self._tasks.values()) + list(self._one_time_tasks.values())
        if not all_tasks:
            return "当前没有定时任务"

        lines = ["[定时任务列表]", "=" * 50]
        for task in all_tasks:
            if task["type"] == "interval":
                schedule_desc = f"每 {task['seconds']} 秒"
            elif task["type"] == "daily":
                schedule_desc = f"每天 {task['time']}"
            else:
                schedule_desc = f"一次性 ({task['run_at'].strftime('%m-%d %H:%M')})"
            lines.append(f"  [{task['id']}] {task['name']} - {schedule_desc}")

        return "\n".join(lines)

    def get_tasks_list(self) -> list:
        """返回任务列表（供 API 使用）"""
        tasks = []
        for task in self._tasks.values():
            tasks.append({
                "id": task["id"],
                "name": task["name"],
                "type": task["type"],
                "seconds": task.get("seconds"),
                "time": task.get("time"),
                "created_at": task["created_at"],
            })
        for task in self._one_time_tasks.values():
            tasks.append({
                "id": task["id"],
                "name": task["name"],
                "type": "one_time",
                "run_at": task["run_at"].isoformat(),
                "created_at": task["created_at"],
            })
        return tasks

    def clear_all(self) -> None:
        """清除所有任务"""
        schedule.clear()
        self._tasks.clear()
        self._one_time_tasks.clear()
        self._save_tasks()

    @property
    def task_count(self) -> int:
        return len(self._tasks) + len(self._one_time_tasks)

    @property
    def is_running(self) -> bool:
        return self._running
