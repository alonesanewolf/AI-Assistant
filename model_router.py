"""
模型路由器 (Model Router)
=========================
支持多个 AI 模型后端，智能分流：
  - Ollama 本地模型（优先处理简单任务，快速响应）
  - DeepSeek API（云端，处理复杂任务）
  - 支持本地优先/云端优先/仅本地/仅云端 四种模式

任务分流策略:
  - 本地操作（截图/文件/系统）→ Ollama 本地模型
  - 复杂推理/长文/搜索 → DeepSeek 云端
  - 简单闲聊 → Ollama 本地模型（快速省钱）

用法:
    router = ModelRouter()
    router.set_mode("local_first")  # 本地优先
    reply = router.chat(messages=[...])
"""

import os
import sys
import time
from typing import Optional

# ==================== 配置 ====================

# DeepSeek（从环境变量读取，不要硬编码 Key）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# Ollama 本地模型
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2:7b")  # 当前电脑安装: qwen2:7b, qwen2.5:7b

# 备用 API（其他 OpenAI 兼容接口）
FALLBACK_API_KEY = os.environ.get("FALLBACK_API_KEY", "")
FALLBACK_BASE_URL = os.environ.get("FALLBACK_BASE_URL", "")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "gpt-3.5-turbo")

# ==================== 任务类型定义 ====================

# 适合本地 Ollama 处理的简单任务关键词
LOCAL_TASK_KEYWORDS = [
    # 电脑操作相关 → 本地模型足够
    "截图", "屏幕", "打开", "文件", "文件夹", "目录", "创建",
    "系统", "进程", "内存", "音量", "锁屏", "关机", "程序",
    "记事本", "计算器", "浏览器", "桌面", "任务管理器",
    "剪贴板", "复制", "粘贴", "输入", "按键", "鼠标",
    # 简单任务
    "几点", "时间", "日期", "今天", "天气",
    "你好", "谢谢", "再见", "帮助",
    # 记忆操作
    "记住", "回忆", "忘记",
]

# 适合云端 DeepSeek 的复杂任务关键词
CLOUD_TASK_KEYWORDS = [
    # 复杂推理/编程
    "代码", "编程", "写一个", "实现", "算法", "调试", "bug",
    "分析", "解释", "原理", "优化", "重构",
    # 长文/翻译
    "翻译", "总结", "概括", "撰写", "文章", "报告",
    # 搜索/知识
    "搜索", "查找", "最新", "什么是", "如何",
    # 创意
    "写诗", "故事", "歌词", "创意", "想法",
]


class ModelRouter:
    """
    智能模型路由器
    - 四种模式: local_first(本地优先), cloud_first(云端优先), local_only, cloud_only
    - 自动任务分流：简单/本地操作 → Ollama，复杂推理 → DeepSeek
    - 支持动态切换和模型列表查询
    """

    MODES = ["local_first", "cloud_first", "local_only", "cloud_only"]

    def __init__(self, mode: str = "local_first"):
        self._clients = {}
        self._available = {}  # 模型可用状态缓存
        self._last_check = {}  # 上次检查时间
        self._check_interval = 60  # 60秒内不重复检查
        self._mode = mode if mode in self.MODES else "local_first"
        self._local_models = []  # 缓存本地模型列表

    # ==================== 模式管理 ====================

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str):
        """设置路由模式: local_first / cloud_first / local_only / cloud_only"""
        if mode in self.MODES:
            self._mode = mode
            print(f"[Router] 模式切换: {mode}")
        else:
            print(f"[Router] 未知模式: {mode}，保持 {self._mode}")

    # ==================== 任务分类 ====================

    def _classify_task(self, user_message: str) -> str:
        """
        分析用户消息，返回推荐模型: "local" 或 "cloud"
        """
        msg_lower = user_message.lower()

        # 先检查云端关键词
        for kw in CLOUD_TASK_KEYWORDS:
            if kw in msg_lower:
                return "cloud"

        # 再检查本地关键词
        for kw in LOCAL_TASK_KEYWORDS:
            if kw in msg_lower:
                return "local"

        # 消息长度判断：短消息本地，长消息云端
        if len(user_message) > 200:
            return "cloud"

        # 默认本地
        return "local"

    # ==================== 客户端管理 ====================

    def _get_client(self, model_key: str):
        """获取或创建模型客户端"""
        if model_key not in self._clients:
            from openai import OpenAI

            if model_key == "deepseek":
                self._clients[model_key] = OpenAI(
                    api_key=DEEPSEEK_API_KEY,
                    base_url=DEEPSEEK_BASE_URL,
                    timeout=30,
                )
            elif model_key == "ollama":
                self._clients[model_key] = OpenAI(
                    api_key="ollama",  # Ollama 不需要真实 key
                    base_url=OLLAMA_BASE_URL,
                    timeout=120,  # 本地模型可能较慢
                )
            elif model_key == "fallback":
                self._clients[model_key] = OpenAI(
                    api_key=FALLBACK_API_KEY,
                    base_url=FALLBACK_BASE_URL,
                    timeout=30,
                )
        return self._clients[model_key]

    def check_available(self, model_key: str) -> bool:
        """检查模型是否可用（带缓存）"""
        now = time.time()
        if model_key in self._available:
            if now - self._last_check.get(model_key, 0) < self._check_interval:
                return self._available[model_key]

        try:
            client = self._get_client(model_key)
            client.models.list()  # 快速检查
            self._available[model_key] = True
        except Exception:
            self._available[model_key] = False

        self._last_check[model_key] = now
        return self._available[model_key]

    def get_ollama_model(self) -> str:
        """获取当前使用的 Ollama 模型名"""
        return OLLAMA_MODEL

    def set_ollama_model(self, model_name: str):
        """动态切换 Ollama 模型"""
        global OLLAMA_MODEL
        OLLAMA_MODEL = model_name
        print(f"[Router] Ollama 模型切换: {model_name}")

    # ==================== 核心对话 ====================

    def chat(
        self,
        messages: list,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        task_hint: Optional[str] = None,  # "local" / "cloud" / None=自动判断
    ) -> dict:
        """
        调用 AI 模型

        参数:
            messages: OpenAI 格式的消息列表
            model: 指定模型 (None=按策略自动选择, "deepseek-chat", "ollama", 具体模型名)
            temperature: 温度
            max_tokens: 最大 token 数
            task_hint: 任务类型提示 ("local"/"cloud"/None=自动判断)

        返回:
            {"content": str, "model": str, "source": str, "success": bool, "error": str|None}
        """
        # 如果指定了具体模型，直接使用
        if model:
            if "deepseek" in model:
                key, actual_model = "deepseek", DEEPSEEK_MODEL
            elif model.startswith("ollama:"):
                key, actual_model = "ollama", model.split(":", 1)[1]
            elif model in ("ollama", "local"):
                key, actual_model = "ollama", OLLAMA_MODEL
            elif model == "fallback":
                key, actual_model = "fallback", FALLBACK_MODEL
                if not FALLBACK_API_KEY:
                    return {"content": "", "model": "", "source": "", "success": False, "error": "备用API未配置"}
            else:
                key, actual_model = "deepseek", DEEPSEEK_MODEL

            return self._try_chat(key, actual_model, messages, temperature, max_tokens)

        # ========== 自动路由策略 ==========

        # 获取用户最后一条消息用于任务分类
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        # 任务分类
        task_type = task_hint or self._classify_task(last_user_msg)

        # 根据模式决定候选列表
        if self._mode == "local_only":
            candidates = [("ollama", OLLAMA_MODEL)]
        elif self._mode == "cloud_only":
            candidates = [("deepseek", DEEPSEEK_MODEL)]
        elif self._mode == "local_first":
            # 本地优先：复杂任务仍走云端
            if task_type == "cloud":
                candidates = [("deepseek", DEEPSEEK_MODEL), ("ollama", OLLAMA_MODEL)]
            else:
                candidates = [("ollama", OLLAMA_MODEL), ("deepseek", DEEPSEEK_MODEL)]
        else:  # cloud_first
            candidates = [("deepseek", DEEPSEEK_MODEL), ("ollama", OLLAMA_MODEL)]

        # 尝试所有候选
        for key, actual_model in candidates:
            result = self._try_chat(key, actual_model, messages, temperature, max_tokens)
            if result["success"]:
                return result

        return {
            "content": "[所有模型均不可用，请检查网络连接和 Ollama 是否运行]",
            "model": "none",
            "source": "none",
            "success": False,
            "error": "所有模型后端均调用失败",
        }

    def _try_chat(self, key: str, actual_model: str, messages: list,
                  temperature: float, max_tokens: int) -> dict:
        """尝试调用单个模型"""
        try:
            client = self._get_client(key)
            response = client.chat.completions.create(
                model=actual_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            self._available[key] = True
            self._last_check[key] = time.time()

            source_map = {"deepseek": "云端", "ollama": "本地", "fallback": "备用"}
            return {
                "content": content,
                "model": actual_model,
                "source": source_map.get(key, key),
                "success": True,
                "error": None,
            }
        except Exception as e:
            self._available[key] = False
            self._last_check[key] = time.time()
            print(f"[Router] 模型 {actual_model} 调用失败: {type(e).__name__}: {e}")
            return {
                "content": "",
                "model": actual_model,
                "source": "",
                "success": False,
                "error": str(e),
            }

    # ==================== 状态查询 ====================

    def get_status(self) -> dict:
        """获取所有模型的状态"""
        status = {
            "deepseek": {
                "model": DEEPSEEK_MODEL,
                "available": self.check_available("deepseek"),
                "type": "云端",
            },
            "ollama": {
                "model": OLLAMA_MODEL,
                "available": self.check_available("ollama"),
                "type": "本地",
                "url": OLLAMA_BASE_URL,
            },
        }
        if FALLBACK_API_KEY:
            status["fallback"] = {
                "model": FALLBACK_MODEL,
                "available": self.check_available("fallback"),
                "type": "备用云端",
            }
        return status

    def get_full_status(self) -> dict:
        """获取完整状态（含路由模式）"""
        status = self.get_status()
        status["router_mode"] = self._mode
        status["local_models"] = self.list_local_models()
        return status

    def list_local_models(self) -> list:
        """列出 Ollama 中已安装的模型"""
        try:
            import requests
            resp = requests.get(
                OLLAMA_BASE_URL.replace("/v1", "/api/tags"),
                timeout=5,
            )
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                self._local_models = models
                return models
        except Exception:
            pass
        return self._local_models


# ==================== 测试 ====================

if __name__ == "__main__":
    router = ModelRouter(mode="local_first")

    print("=== 路由模式 ===")
    print(f"  当前模式: {router.mode}")
    print(f"  可用模式: {', '.join(ModelRouter.MODES)}")

    print("\n=== 模型状态 ===")
    status = router.get_full_status()
    for name, info in status.items():
        if name in ("router_mode", "local_models"):
            continue
        icon = "OK" if info["available"] else "FAIL"
        print(f"  [{icon}] {name}: {info['model']} ({info['type']})")

    print(f"\n=== 本地 Ollama 模型 ({len(status['local_models'])} 个) ===")
    if status["local_models"]:
        for m in status["local_models"]:
            current = " (当前使用)" if m == OLLAMA_MODEL else ""
            print(f"  - {m}{current}")
    else:
        print("  未检测到本地模型（Ollama 未运行或未安装）")

    print("\n=== 任务分类测试 ===")
    tests = [
        "帮我截个图",
        "写一个 Python 排序算法",
        "你好啊",
        "打开记事本",
        "搜索最新 AI 新闻",
    ]
    for t in tests:
        cls = router._classify_task(t)
        print(f"  [{cls:5}] {t}")

    print("\n=== 测试对话 (本地优先) ===")
    result = router.chat(
        messages=[{"role": "user", "content": "用一句话介绍你自己"}]
    )
    print(f"  来源: {result.get('source', '?')}")
    print(f"  模型: {result['model']}")
    print(f"  成功: {result['success']}")
    print(f"  回复: {result['content'][:100]}...")
