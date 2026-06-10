"""
支付模块 - 会员订阅 / 积分系统 / 订单管理
==========================================
功能:
  1. 会员订阅 (Free / Pro / Enterprise)
  2. 积分系统 (API 调用 / 扫描次数消耗)
  3. 订单管理 (创建 / 查询 / 回调)
  4. 支付网关抽象层 (微信支付 / 支付宝 / ClawPay)
  5. 优惠码系统

用法:
    from payment import PaymentManager
    pm = PaymentManager()
    order = pm.create_order(user_id, plan_id, payment_method="wechat")
"""

import os
import json
import uuid
import hashlib
import time
import threading
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, asdict

import pymysql
from flask import current_app


# ==================== 数据模型 ====================

@dataclass
class Plan:
    """会员订阅方案"""
    plan_id: str          # free / pro_monthly / pro_yearly / enterprise
    name: str             # 方案名称
    tier: str             # free / pro / enterprise
    price_cents: int      # 价格（分）
    interval: str         # month / year / once
    credits_monthly: int  # 每月赠送积分
    scan_limit_daily: int # 每日扫描次数限制
    api_limit_daily: int  # 每日 API 调用限制
    features: list        # 功能列表
    highlighted: bool     # 是否推荐
    badge: str            # 徽章文字


@dataclass
class Order:
    """订单"""
    order_id: str
    user_id: int
    plan_id: str
    amount_cents: int
    status: str           # pending / paid / expired / cancelled / refunded
    payment_method: str   # wechat / alipay / clawpay / mock
    coupon_code: str
    created_at: str
    paid_at: str
    expire_at: str


@dataclass
class Subscription:
    """用户订阅"""
    user_id: int
    plan_id: str
    tier: str
    status: str           # active / expired / cancelled
    started_at: str
    expire_at: str
    auto_renew: bool


# ==================== 会员方案定义 ====================

PLANS = {
    "free": Plan(
        plan_id="free",
        name="免费版",
        tier="free",
        price_cents=0,
        interval="once",
        credits_monthly=100,
        scan_limit_daily=5,
        api_limit_daily=50,
        features=[
            "基础漏洞练习 (5个)",
            "每日5次端口扫描",
            "每日50次 API 调用",
            "社区支持",
        ],
        highlighted=False,
        badge="入门",
    ),
    "pro_monthly": Plan(
        plan_id="pro_monthly",
        name="Pro 月付",
        tier="pro",
        price_cents=2990,  # ¥29.90
        interval="month",
        credits_monthly=1000,
        scan_limit_daily=50,
        api_limit_daily=500,
        features=[
            "全部漏洞练习 (>15个)",
            "每日50次端口扫描",
            "每日500次 API 调用",
            "AI 智能分析报告",
            "扫描历史记录",
            "优先客服支持",
        ],
        highlighted=True,
        badge="推荐",
    ),
    "pro_yearly": Plan(
        plan_id="pro_yearly",
        name="Pro 年付",
        tier="pro",
        price_cents=19900,  # ¥199.00
        interval="year",
        credits_monthly=1500,
        scan_limit_daily=100,
        api_limit_daily=1000,
        features=[
            "Pro 月付全部功能",
            "每日100次端口扫描",
            "每日1000次 API 调用",
            "高级报告导出 (PDF/HTML)",
            "自定义扫描规则",
            "专属 Lab 环境",
        ],
        highlighted=False,
        badge="超值",
    ),
    "enterprise": Plan(
        plan_id="enterprise",
        name="企业版",
        tier="enterprise",
        price_cents=99900,  # ¥999.00
        interval="year",
        credits_monthly=10000,
        scan_limit_daily=9999,
        api_limit_daily=99999,
        features=[
            "全部功能无限制",
            "独立专属服务器",
            "定制化漏洞靶场",
            "团队管理 (最多50人)",
            "API 接口集成",
            "私有化部署支持",
            "7x24 专属技术支持",
            "培训课程与认证",
        ],
        highlighted=False,
        badge="企业",
    ),
}

# 积分充值套餐
CREDIT_PACKAGES = [
    {"id": "credits_100", "name": "100 积分", "credits": 100, "price_cents": 1000, "desc": "¥10.00"},
    {"id": "credits_500", "name": "500 积分", "credits": 500, "price_cents": 3990, "desc": "¥39.90", "badge": "热销"},
    {"id": "credits_2000", "name": "2000 积分", "credits": 2000, "price_cents": 12900, "desc": "¥129.00", "badge": "超值"},
    {"id": "credits_5000", "name": "5000 积分", "credits": 5000, "price_cents": 29900, "desc": "¥299.00"},
]

# 积分消耗规则
CREDIT_COSTS = {
    "port_scan": 10,       # 端口扫描: 10 积分
    "web_dir_scan": 15,    # 目录扫描: 15 积分  
    "subdomain_scan": 8,   # 子域名扫描: 8 积分
    "vuln_scan": 20,       # 漏洞扫描: 20 积分
    "waf_detect": 5,       # WAF 检测: 5 积分
    "fingerprint": 5,      # 指纹识别: 5 积分
    "ai_analysis": 30,     # AI 分析: 30 积分
    "report_export": 50,   # 报告导出: 50 积分
}


# ==================== 数据库初始化 ====================

PAYMENT_TABLES_SQL = """
-- 会员方案表
CREATE TABLE IF NOT EXISTS `payment_plans` (
    `plan_id` VARCHAR(50) PRIMARY KEY,
    `name` VARCHAR(100) NOT NULL,
    `tier` VARCHAR(20) NOT NULL DEFAULT 'free',
    `price_cents` INT NOT NULL DEFAULT 0,
    `interval` VARCHAR(20) NOT NULL DEFAULT 'month',
    `credits_monthly` INT NOT NULL DEFAULT 0,
    `scan_limit_daily` INT NOT NULL DEFAULT 5,
    `api_limit_daily` INT NOT NULL DEFAULT 50,
    `features` JSON DEFAULT NULL,
    `is_active` TINYINT NOT NULL DEFAULT 1,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户订阅表
CREATE TABLE IF NOT EXISTS `user_subscriptions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `plan_id` VARCHAR(50) NOT NULL DEFAULT 'free',
    `tier` VARCHAR(20) NOT NULL DEFAULT 'free',
    `status` VARCHAR(20) NOT NULL DEFAULT 'active',
    `started_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `expire_at` DATETIME DEFAULT NULL,
    `auto_renew` TINYINT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY `idx_user_id` (`user_id`),
    KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户积分表
CREATE TABLE IF NOT EXISTS `user_credits` (
    `user_id` INT PRIMARY KEY,
    `balance` INT NOT NULL DEFAULT 100,
    `total_earned` INT NOT NULL DEFAULT 0,
    `total_spent` INT NOT NULL DEFAULT 0,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 积分流水表
CREATE TABLE IF NOT EXISTS `credit_transactions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `amount` INT NOT NULL,
    `type` VARCHAR(20) NOT NULL COMMENT 'earn/spend/admin',
    `reason` VARCHAR(200) NOT NULL DEFAULT '',
    `order_id` VARCHAR(50) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_user_id` (`user_id`),
    KEY `idx_order_id` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 订单表
CREATE TABLE IF NOT EXISTS `payment_orders` (
    `order_id` VARCHAR(50) PRIMARY KEY,
    `user_id` INT NOT NULL,
    `plan_id` VARCHAR(50) NOT NULL,
    `amount_cents` INT NOT NULL DEFAULT 0,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
    `payment_method` VARCHAR(20) NOT NULL DEFAULT 'wechat',
    `coupon_code` VARCHAR(50) DEFAULT NULL,
    `transaction_id` VARCHAR(100) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `paid_at` DATETIME DEFAULT NULL,
    `expire_at` DATETIME DEFAULT NULL,
    KEY `idx_user_id` (`user_id`),
    KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 优惠码表
CREATE TABLE IF NOT EXISTS `coupon_codes` (
    `code` VARCHAR(50) PRIMARY KEY,
    `discount_percent` INT NOT NULL DEFAULT 0,
    `discount_cents` INT NOT NULL DEFAULT 0,
    `max_uses` INT NOT NULL DEFAULT 100,
    `used_count` INT NOT NULL DEFAULT 0,
    `valid_from` DATETIME DEFAULT NULL,
    `valid_until` DATETIME DEFAULT NULL,
    `plans_applicable` JSON DEFAULT NULL,
    `is_active` TINYINT NOT NULL DEFAULT 1,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户使用统计表
CREATE TABLE IF NOT EXISTS `user_usage_stats` (
    `user_id` INT NOT NULL,
    `date` DATE NOT NULL,
    `scan_count` INT NOT NULL DEFAULT 0,
    `api_count` INT NOT NULL DEFAULT 0,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始化默认方案数据
INSERT IGNORE INTO `payment_plans` (`plan_id`, `name`, `tier`, `price_cents`, `interval`, 
    `credits_monthly`, `scan_limit_daily`, `api_limit_daily`, `features`, `is_active`) VALUES
('free', '免费版', 'free', 0, 'once', 100, 5, 50, 
    '["基础漏洞练习 (5个)", "每日5次端口扫描", "每日50次 API 调用", "社区支持"]', 1),
('pro_monthly', 'Pro 月付', 'pro', 2990, 'month', 1000, 50, 500,
    '["全部漏洞练习 (>15个)", "每日50次端口扫描", "每日500次 API 调用", "AI 智能分析报告", "扫描历史记录", "优先客服支持"]', 1),
('pro_yearly', 'Pro 年付', 'pro', 19900, 'year', 1500, 100, 1000,
    '["Pro 月付全部功能", "每日100次端口扫描", "每日1000次 API 调用", "高级报告导出", "自定义扫描规则", "专属 Lab 环境"]', 1),
('enterprise', '企业版', 'enterprise', 99900, 'year', 10000, 9999, 99999,
    '["全部功能无限制", "独立专属服务器", "定制化漏洞靶场", "团队管理", "API 集成", "私有化部署", "7x24技术支持", "培训认证"]', 1);
"""


# ==================== 支付管理器 ====================

class PaymentManager:
    """支付管理器 - 单例模式"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_connector=None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_connector=None):
        if self._initialized:
            return
        self._db_connector = db_connector
        self._initialized = True
        self._credit_rewards = threading.Thread(target=self._monthly_credit_reward_loop, daemon=True)

    @property
    def db(self):
        """获取数据库连接 (需要外部注入)"""
        if self._db_connector:
            return self._db_connector()
        raise RuntimeError("PaymentManager 未注入数据库连接器")

    # ==================== 初始化 ====================

    def init_tables(self, db_conn):
        """初始化支付相关表"""
        cursor = db_conn.cursor()
        statements = [s.strip() for s in PAYMENT_TABLES_SQL.split(";") if s.strip()]
        for stmt in statements:
            try:
                cursor.execute(stmt)
            except Exception as e:
                print(f"[Payment] 表初始化跳过: {e}")
        db_conn.commit()
        cursor.close()
        print("[Payment] 支付表初始化完成")

    # ==================== 方案管理 ====================

    def get_all_plans(self) -> list:
        """获取所有激活的方案"""
        return [asdict(p) for p in PLANS.values()]

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """获取指定方案"""
        return PLANS.get(plan_id)

    def get_credit_packages(self) -> list:
        """获取积分充值套餐"""
        return CREDIT_PACKAGES

    # ==================== 用户订阅 ====================

    def get_user_subscription(self, user_id: int) -> Optional[dict]:
        """获取用户当前订阅"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM user_subscriptions WHERE user_id=%s AND status='active' ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            # 检查是否过期
            if row.get("expire_at") and row["expire_at"] < datetime.now():
                self._expire_subscription(user_id, row["id"])
                return self.get_user_subscription(user_id)
            return row
        return None

    def get_user_tier(self, user_id: int) -> str:
        """获取用户等级"""
        sub = self.get_user_subscription(user_id)
        return sub["tier"] if sub else "free"

    def create_or_upgrade_subscription(self, user_id: int, plan_id: str, 
                                        duration_days: int = 30, auto_renew: bool = False) -> bool:
        """创建或升级订阅"""
        plan = PLANS.get(plan_id)
        if not plan:
            return False

        db = self.db
        cursor = db.cursor()

        # 标记旧订阅为过期
        cursor.execute(
            "UPDATE user_subscriptions SET status='expired' WHERE user_id=%s AND status='active'",
            (user_id,)
        )

        # 计算到期时间
        expire_at = datetime.now() + timedelta(days=duration_days)

        # 创建新订阅
        cursor.execute(
            """INSERT INTO user_subscriptions (user_id, plan_id, tier, status, started_at, expire_at, auto_renew)
               VALUES (%s, %s, %s, 'active', NOW(), %s, %s)""",
            (user_id, plan_id, plan.tier, expire_at, 1 if auto_renew else 0)
        )
        db.commit()
        cursor.close()

        # 发放月度积分
        self.grant_credits(user_id, plan.credits_monthly, 
                          f"订阅 {plan.name} 赠送积分")

        print(f"[Payment] 用户 {user_id} 订阅 {plan.name}，到期 {expire_at}")
        return True

    def _expire_subscription(self, user_id: int, sub_id: int):
        """将订阅标记为过期"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "UPDATE user_subscriptions SET status='expired' WHERE id=%s AND user_id=%s",
            (sub_id, user_id)
        )
        db.commit()
        cursor.close()

    def check_subscription_expiry(self):
        """批量检查并处理过期订阅"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "UPDATE user_subscriptions SET status='expired' "
            "WHERE status='active' AND expire_at IS NOT NULL AND expire_at < NOW()"
        )
        affected = cursor.rowcount
        db.commit()
        cursor.close()
        if affected:
            print(f"[Payment] {affected} 个订阅已自动过期")

    # ==================== 积分管理 ====================

    def get_credits(self, user_id: int) -> int:
        """获取用户积分余额"""
        db = self.db
        cursor = db.cursor()
        cursor.execute("SELECT balance FROM user_credits WHERE user_id=%s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        return row["balance"] if row else 0

    def ensure_credits_account(self, user_id: int) -> None:
        """确保用户有积分账户"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "INSERT IGNORE INTO user_credits (user_id, balance) VALUES (%s, 100)",
            (user_id,)
        )
        db.commit()
        cursor.close()

    def grant_credits(self, user_id: int, amount: int, reason: str = "",
                       order_id: str = None) -> bool:
        """发放积分"""
        if amount <= 0:
            return False
        db = self.db
        cursor = db.cursor()
        self.ensure_credits_account(user_id)
        cursor.execute(
            "UPDATE user_credits SET balance=balance+%s, total_earned=total_earned+%s WHERE user_id=%s",
            (amount, amount, user_id)
        )
        cursor.execute(
            "INSERT INTO credit_transactions (user_id, amount, type, reason, order_id) VALUES (%s, %s, 'earn', %s, %s)",
            (user_id, amount, reason, order_id)
        )
        db.commit()
        cursor.close()
        return True

    def spend_credits(self, user_id: int, amount: int, reason: str = "") -> bool:
        """消耗积分"""
        if amount <= 0:
            return True  # 免费操作
        db = self.db
        cursor = db.cursor()
        self.ensure_credits_account(user_id)
        cursor.execute("SELECT balance FROM user_credits WHERE user_id=%s", (user_id,))
        row = cursor.fetchone()
        if not row or row["balance"] < amount:
            cursor.close()
            return False

        cursor.execute(
            "UPDATE user_credits SET balance=balance-%s, total_spent=total_spent+%s WHERE user_id=%s AND balance>=%s",
            (amount, amount, user_id, amount)
        )
        if cursor.rowcount == 0:
            cursor.close()
            return False

        cursor.execute(
            "INSERT INTO credit_transactions (user_id, amount, type, reason) VALUES (%s, %s, 'spend', %s)",
            (user_id, -amount, reason)
        )
        db.commit()
        cursor.close()
        return True

    def get_credit_history(self, user_id: int, limit: int = 20) -> list:
        """获取积分流水"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM credit_transactions WHERE user_id=%s ORDER BY id DESC LIMIT %s",
            (user_id, limit)
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def _monthly_credit_reward_loop(self):
        """每月自动发放订阅积分（简化版：每天检查）"""
        while True:
            time.sleep(86400)  # 每天检查一次
            try:
                db = self.db
                cursor = db.cursor()
                # 查找今天需要发放积分的 Pro/Enterprise 订阅
                today = datetime.now().day
                if today == 1:  # 每月1号发放
                    cursor.execute(
                        "SELECT us.user_id, us.plan_id, pp.credits_monthly "
                        "FROM user_subscriptions us "
                        "JOIN payment_plans pp ON us.plan_id=pp.plan_id "
                        "WHERE us.status='active' AND pp.credits_monthly > 0"
                    )
                    for row in cursor.fetchall():
                        self.grant_credits(
                            row["user_id"], row["credits_monthly"],
                            f"月度积分发放 ({row['plan_id']})"
                        )
                    print(f"[Payment] 月度积分已发放")
                cursor.close()
            except Exception as e:
                print(f"[Payment] 月度积分发放失败: {e}")

    # ==================== 使用限制检查 ====================

    def check_and_consume_usage(self, user_id: int, operation_type: str) -> dict:
        """
        检查用户是否有权限执行操作，并消耗积分/配额。
        返回 {"allowed": bool, "message": str, "credits_cost": int}
        """
        tier = self.get_user_tier(user_id)
        today = datetime.now().strftime("%Y-%m-%d")

        db = self.db
        cursor = db.cursor()

        # 获取今日使用量
        cursor.execute(
            "SELECT scan_count, api_count FROM user_usage_stats WHERE user_id=%s AND date=%s",
            (user_id, today)
        )
        row = cursor.fetchone()
        today_scans = row["scan_count"] if row else 0
        today_apis = row["api_count"] if row else 0

        plan = PLANS.get(f"{tier}_monthly") or PLANS.get(tier) or PLANS["free"]
        if tier in ("pro", "enterprise"):
            sub = self.get_user_subscription(user_id)
            if sub:
                plan = PLANS.get(sub["plan_id"], PLANS["free"])

        credits_cost = CREDIT_COSTS.get(operation_type, 10)

        # 检查配额
        if operation_type in ("port_scan", "web_dir_scan", "subdomain_scan", "vuln_scan"):
            if today_scans >= plan.scan_limit_daily:
                cursor.close()
                return {"allowed": False, "message": f"今日扫描次数已用完 ({today_scans}/{plan.scan_limit_daily})，请升级会员", "credits_cost": credits_cost}

        if today_apis >= plan.api_limit_daily:
            cursor.close()
            return {"allowed": False, "message": f"今日 API 调用次数已用完 ({today_apis}/{plan.api_limit_daily})，请升级会员", "credits_cost": credits_cost}

        # 消耗积分 (free 用户需要积分)
        if tier == "free":
            ok = self.spend_credits(user_id, credits_cost, f"操作: {operation_type}")
            if not ok:
                cursor.close()
                return {"allowed": False, "message": f"积分不足 (需要 {credits_cost} 积分)，请充值", "credits_cost": credits_cost}

        # 更新使用量
        if operation_type in ("port_scan", "web_dir_scan", "subdomain_scan", "vuln_scan"):
            cursor.execute(
                "INSERT INTO user_usage_stats (user_id, date, scan_count, api_count) VALUES (%s, %s, 1, 1) "
                "ON DUPLICATE KEY UPDATE scan_count=scan_count+1",
                (user_id, today)
            )
        else:
            cursor.execute(
                "INSERT INTO user_usage_stats (user_id, date, scan_count, api_count) VALUES (%s, %s, 0, 1) "
                "ON DUPLICATE KEY UPDATE api_count=api_count+1",
                (user_id, today)
            )
        db.commit()
        cursor.close()

        return {"allowed": True, "message": "操作已授权", "credits_cost": credits_cost if tier == "free" else 0}

    # ==================== 订单管理 ====================

    def create_order(self, user_id: int, plan_id: str, payment_method: str = "wechat",
                      coupon_code: str = "") -> Optional[Order]:
        """创建支付订单"""
        plan = PLANS.get(plan_id)
        if not plan:
            # 检查是否是积分套餐
            pkg = next((p for p in CREDIT_PACKAGES if p["id"] == plan_id), None)
            if not pkg:
                return None
            amount = pkg["price_cents"]
        else:
            amount = plan.price_cents

        # 应用优惠码
        discount = 0
        if coupon_code:
            discount = self._validate_coupon(coupon_code, plan_id)
            if discount > 0:
                amount = max(0, amount - discount)

        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        expire_at = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

        db = self.db
        cursor = db.cursor()
        cursor.execute(
            """INSERT INTO payment_orders (order_id, user_id, plan_id, amount_cents, status, 
               payment_method, coupon_code, expire_at)
               VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s)""",
            (order_id, user_id, plan_id, amount, payment_method, coupon_code or None, expire_at)
        )
        db.commit()
        cursor.close()

        print(f"[Payment] 订单创建: {order_id}, 金额: {amount/100:.2f} 元")
        return Order(
            order_id=order_id, user_id=user_id, plan_id=plan_id,
            amount_cents=amount, status="pending", payment_method=payment_method,
            coupon_code=coupon_code, created_at=datetime.now().isoformat(),
            paid_at="", expire_at=expire_at,
        )

    def get_order(self, order_id: str) -> Optional[dict]:
        """查询订单"""
        db = self.db
        cursor = db.cursor()
        cursor.execute("SELECT * FROM payment_orders WHERE order_id=%s", (order_id,))
        row = cursor.fetchone()
        cursor.close()
        return row

    def get_user_orders(self, user_id: int, limit: int = 20) -> list:
        """查询用户订单列表"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM payment_orders WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit)
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def complete_order(self, order_id: str, transaction_id: str = "") -> dict:
        """完成订单支付（模拟支付成功）"""
        db = self.db
        cursor = db.cursor()

        cursor.execute("SELECT * FROM payment_orders WHERE order_id=%s", (order_id,))
        order = cursor.fetchone()
        if not order:
            cursor.close()
            return {"success": False, "message": "订单不存在"}

        if order["status"] != "pending":
            cursor.close()
            return {"success": False, "message": f"订单状态异常: {order['status']}"}

        # 更新订单状态
        cursor.execute(
            "UPDATE payment_orders SET status='paid', paid_at=NOW(), transaction_id=%s WHERE order_id=%s",
            (transaction_id, order_id)
        )
        db.commit()

        # 处理订阅或积分
        plan_id = order["plan_id"]
        user_id = order["user_id"]

        if plan_id.startswith("credits_"):
            # 积分充值
            pkg = next((p for p in CREDIT_PACKAGES if p["id"] == plan_id), None)
            if pkg:
                self.grant_credits(user_id, pkg["credits"], 
                                  f"购买积分包: {pkg['name']}", order_id)
        else:
            # 订阅激活
            plan = PLANS.get(plan_id)
            if plan:
                if plan.interval == "year":
                    days = 365
                elif plan.interval == "month":
                    days = 30
                else:
                    days = 99999  # 永久
                self.create_or_upgrade_subscription(user_id, plan_id, days)

        cursor.close()
        print(f"[Payment] 订单完成: {order_id}, 金额: {order['amount_cents']/100:.2f} 元")
        return {"success": True, "message": "支付成功", "order_id": order_id}

    def cancel_order(self, order_id: str) -> dict:
        """取消订单"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "UPDATE payment_orders SET status='cancelled' WHERE order_id=%s AND status='pending'",
            (order_id,)
        )
        affected = cursor.rowcount
        db.commit()
        cursor.close()
        if affected:
            return {"success": True, "message": "订单已取消"}
        return {"success": False, "message": "订单不存在或无法取消"}

    def get_order_stats(self) -> dict:
        """获取支付统计"""
        db = self.db
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) as total, SUM(amount_cents) as revenue FROM payment_orders WHERE status='paid'")
        row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) as pending FROM payment_orders WHERE status='pending'")
        pending = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) as active FROM user_subscriptions WHERE status='active'")
        active = cursor.fetchone()
        cursor.close()
        return {
            "total_orders": row["total"] or 0,
            "total_revenue_cents": row["revenue"] or 0,
            "pending_orders": pending["pending"] or 0,
            "active_subscriptions": active["active"] or 0,
        }

    # ==================== 优惠码 ====================

    def _validate_coupon(self, code: str, plan_id: str = "") -> int:
        """验证优惠码，返回折扣金额（分）"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM coupon_codes WHERE code=%s AND is_active=1", (code,)
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return 0
        # 检查有效期
        now = datetime.now()
        if row.get("valid_from") and now < row["valid_from"]:
            return 0
        if row.get("valid_until") and now > row["valid_until"]:
            return 0
        # 检查使用次数
        if row["used_count"] >= row["max_uses"]:
            return 0
        # 检查适用方案
        plans = json.loads(row.get("plans_applicable") or "[]")
        if plans and plan_id not in plans:
            return 0
        return row.get("discount_cents", 0)

    def consume_coupon(self, code: str) -> bool:
        """消费优惠码"""
        db = self.db
        cursor = db.cursor()
        cursor.execute(
            "UPDATE coupon_codes SET used_count=used_count+1 WHERE code=%s AND used_count<max_uses",
            (code,)
        )
        ok = cursor.rowcount > 0
        db.commit()
        cursor.close()
        return ok

    def create_coupon(self, code: str, discount_percent: int = 0, discount_cents: int = 0,
                       max_uses: int = 100, valid_days: int = 30, plans: list = None) -> bool:
        """创建优惠码"""
        db = self.db
        cursor = db.cursor()
        valid_until = (datetime.now() + timedelta(days=valid_days)).strftime("%Y-%m-%d %H:%M:%S")
        plans_json = json.dumps(plans) if plans else None
        try:
            cursor.execute(
                """INSERT INTO coupon_codes (code, discount_percent, discount_cents, max_uses, 
                   valid_from, valid_until, plans_applicable)
                   VALUES (%s, %s, %s, %s, NOW(), %s, %s)""",
                (code, discount_percent, discount_cents, max_uses, valid_until, plans_json)
            )
            db.commit()
            cursor.close()
            return True
        except Exception:
            cursor.close()
            return False


# ==================== 便捷函数（与 NetSec Flask 集成） ====================

# 全局单例（需在 run.py 中注入 db）
payment_manager = PaymentManager()


def init_payment(db_connector_func):
    """在 Flask app 中初始化支付模块"""
    pm = PaymentManager(db_connector_func)
    # 注入数据库连接器后初始化表
    db = db_connector_func()
    pm.init_tables(db)
    db.close()
    return pm


def get_user_status(user_id: int) -> dict:
    """获取用户会员状态（供前端展示）"""
    pm = payment_manager
    sub = pm.get_user_subscription(user_id)
    credits = pm.get_credits(user_id)
    tier = sub["tier"] if sub else "free"
    plan = PLANS.get(sub["plan_id"], PLANS["free"]) if sub else PLANS["free"]

    return {
        "user_id": user_id,
        "tier": tier,
        "tier_name": {"free": "免费用户", "pro": "Pro 会员", "enterprise": "企业会员"}.get(tier, "免费用户"),
        "plan_name": plan.name if sub else "免费版",
        "credits": credits,
        "expire_at": str(sub["expire_at"]) if sub and sub.get("expire_at") else None,
        "is_pro": tier in ("pro", "enterprise"),
        "is_enterprise": tier == "enterprise",
        "scan_limit_daily": plan.scan_limit_daily,
        "api_limit_daily": plan.api_limit_daily,
    }
