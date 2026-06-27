"""共享配置 — 从 .env 文件和环境变量读取，不含敏感硬编码。

所有模块应通过此文件获取配置，而非直接 os.environ.get()，
以保证配置的集中管理和默认值一致性。
"""

import os
from pathlib import Path


def _load_dotenv() -> None:
    """加载 .env 文件中的配置到 os.environ（不覆盖已有环境变量）"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default).lower()).lower() in ("true", "1", "yes")


# ==================== AI 模型 ====================

DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat")
API_TIMEOUT = _env_int("API_TIMEOUT", 60)

# Ollama 本地模型
OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2:7b")

# 智能路由模式: local_first / cloud_first / local_only / cloud_only
ROUTER_MODE = _env("ROUTER_MODE", "local_first")

# 备用 API
FALLBACK_API_KEY = _env("FALLBACK_API_KEY")
FALLBACK_BASE_URL = _env("FALLBACK_BASE_URL")
FALLBACK_MODEL = _env("FALLBACK_MODEL", "gpt-3.5-turbo")

# ==================== 记忆 ====================

MAX_MEMORY_TURNS = _env_int("MAX_MEMORY_TURNS", 20)

# ==================== Brain 服务 ====================

BRAIN_HOST = _env("HOST", "0.0.0.0")
BRAIN_PORT = _env_int("BRAIN_PORT", 5000)

# Agent 客户端用
BRAIN_URL = _env("BRAIN_URL", "http://localhost:5000")
AGENT_NAME = _env("AGENT_NAME", "")

# ==================== Redis ====================

REDIS_HOST = _env("REDIS_HOST", "localhost")
REDIS_PORT = _env_int("REDIS_PORT", 6379)
REDIS_DB = _env_int("REDIS_DB", 0)

# ==================== QQ Bot ====================

QQ_BOT_ENABLED = _env_bool("QQ_BOT_ENABLED")
QQ_WS_URL = _env("QQ_WS_URL", "ws://localhost:3001")

# ==================== 微信 ====================

WECHAT_ENABLED = _env_bool("WECHAT_ENABLED")
WECOM_BOT_KEY = _env("WECOM_BOT_KEY")
WECOM_WEBHOOK = _env("WECOM_WEBHOOK")  # 企业微信群机器人 Webhook URL

# 企业微信（wechat_assistant.py 用）
WECOM_CORP_ID = _env("WECOM_CORP_ID")
WECOM_AGENT_SECRET = _env("WECOM_AGENT_SECRET")
WECOM_TOKEN = _env("WECOM_TOKEN")
WECOM_ENCODING_AES_KEY = _env("WECOM_ENCODING_AES_KEY")

# ==================== Telegram ====================

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN)

# ==================== 审计 ====================

AUDIT_DIR = _env("AUDIT_DIR", "audit_logs")
AUDIT_MAX_SIZE_MB = _env_int("AUDIT_MAX_SIZE_MB", 10)
AUDIT_SQLITE = _env("AUDIT_SQLITE", "audit.db")

# ==================== 备份 ====================

BACKUP_DIR = _env("BACKUP_DIR", "backups")
BACKUP_RETENTION_DAYS = _env_int("BACKUP_RETENTION_DAYS", 30)
BACKUP_INTERVAL_HOURS = _env_int("BACKUP_INTERVAL_HOURS", 24)

# ==================== QQ/WeChat Hub ====================

ONEBOT_HTTP_API = _env("ONEBOT_HTTP_API", "")
HUB_PORT = _env_int("HUB_PORT", 5055)

# ==================== 速率限制 ====================

RATE_LIMIT_PER_MINUTE = _env_int("RATE_LIMIT_PER_MINUTE", 30)
RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", True)
