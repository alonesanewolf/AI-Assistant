"""
配置自动备份脚本
==================
用于定期备份 .env、日志和关键配置文件。
保留最近 7 天的备份，自动清理过期文件。

用法:
    python backup_config.py              # 手动触发备份
    python backup_config.py --schedule   # 启动定时备份（每小时）
"""

import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ==================== 配置 ====================

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "backups"))
RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "7"))
INTERVAL_HOURS = int(os.environ.get("BACKUP_INTERVAL_HOURS", "1"))

FILES_TO_BACKUP = [
    ".env",
    "config.py",
    "requirements.txt",
    "brain.py",
    "agent_client.py",
    "model_router.py",
    "memory.py",
    "scheduler.py",
    "actions.py",
    "audit.py",
    "assistant.py",
    "local_assistant.py",
    "search.py",
    "qq_bot.py",
    "qq_wechat_hub.py",
    "wechat_bot.py",
    "wechat_assistant.py",
    "telegram_bot.py",
    "telegram_bot_standalone.py",
    "backup_config.py",
]

DIRS_TO_BACKUP = [
    "logs",
    "deploy",
]


def create_backup() -> Path:
    """创建一次备份，返回备份目录路径"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = BACKUP_DIR / f"backup_{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)

    project_root = Path(__file__).parent

    # 备份单个文件
    for filename in FILES_TO_BACKUP:
        src = project_root / filename
        if src.exists():
            dst = backup_root / filename
            shutil.copy2(src, dst)
            print(f"  [FILE] {filename}")

    # 备份目录
    for dirname in DIRS_TO_BACKUP:
        src = project_root / dirname
        if src.exists():
            dst = backup_root / dirname
            shutil.copytree(src, dst, dirs_exist_ok=True)
            file_count = sum(1 for _ in dst.rglob("*") if _.is_file())
            print(f"  [DIR]  {dirname}/ ({file_count} 个文件)")

    # 写入备份元信息
    meta_file = backup_root / "backup_meta.txt"
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(f"备份时间: {datetime.now().isoformat()}\n")
        f.write(f"主机名: {os.environ.get('COMPUTERNAME', 'unknown')}\n")
        f.write(f"路径: {project_root}\n")

    return backup_root


def cleanup_old_backups():
    """清理超过保留天数的旧备份"""
    if not BACKUP_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    deleted = 0

    for item in BACKUP_DIR.iterdir():
        if item.is_dir() and item.name.startswith("backup_"):
            try:
                date_str = item.name.replace("backup_", "")
                backup_time = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
                if backup_time < cutoff:
                    shutil.rmtree(item)
                    deleted += 1
                    print(f"  [清理] {item.name}")
            except (ValueError, OSError):
                pass

    if deleted:
        print(f"  共清理 {deleted} 个过期备份")


def schedule_backups():
    """定时备份模式"""
    print(f"[备份调度器] 启动，间隔 {INTERVAL_HOURS} 小时，保留 {RETENTION_DAYS} 天")
    while True:
        try:
            print(f"\n{'=' * 50}")
            print(f"[备份] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'=' * 50}")

            backup_path = create_backup()
            print(f"  备份完成: {backup_path}")

            cleanup_old_backups()

        except Exception as e:
            print(f"[备份] 异常: {e}", file=sys.stderr)

        time.sleep(INTERVAL_HOURS * 3600)


def main():
    parser = argparse.ArgumentParser(description="配置自动备份工具")
    parser.add_argument("--schedule", action="store_true", help="启动定时备份模式")
    args = parser.parse_args()

    print(f"备份目录: {BACKUP_DIR.absolute()}")
    print(f"保留天数: {RETENTION_DAYS}")

    if args.schedule:
        schedule_backups()
    else:
        print(f"\n{'=' * 50}")
        print(f"[备份] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 50}")
        backup_path = create_backup()
        print(f"\n备份完成: {backup_path}")
        cleanup_old_backups()


if __name__ == "__main__":
    main()
