import string
import json
import platform
import sys
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
import os
import random
import hashlib
import uuid
import pymysql

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    url_for,
    session,
    request,
    send_from_directory,
    Response,
)

# 导入扫描核心类
from NetSecAssistant import NetSecAssistant
import network_scan
import socket

# 支付模块（已隐藏，待后续启用）
# from payment import payment_manager, init_payment, get_user_status, CREDIT_COSTS
def get_user_status(user_id=None):
    """临时桩函数，隐藏支付功能"""
    return {"plan": "free", "credits": 0, "is_premium": False, "expires_at": None}


# =========================
# 密码安全（PBKDF2-SHA512 + 随机盐，参考 authbase）
# =========================

def generate_salt(length=16):
    """生成随机盐（16字节）"""
    return os.urandom(length)


def hash_password(password, salt):
    """使用 PBKDF2-SHA512 算法加密密码，迭代 100,000 次"""
    return hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)


def make_password_hash(password):
    """生成密码哈希（使用 werkzeug）"""
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password)


def verify_password(password, pwd_hash):
    """验证密码（使用 werkzeug）"""
    try:
        from werkzeug.security import check_password_hash
        return check_password_hash(pwd_hash, password)
    except (ImportError, Exception):
        return False


# =========================
# 基础配置
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# URL 前缀（通过 Nginx 反向代理 /netsec/ 时使用）
APPLICATION_ROOT = os.getenv("NETSEC_APP_ROOT", "")

app = Flask(
    __name__,
    static_url_path=f"{APPLICATION_ROOT}/static" if APPLICATION_ROOT else "/static",
    static_folder="static",
    template_folder="templates",
)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")
app.permanent_session_lifetime = timedelta(hours=8)

# =========================
# 全局错误处理 + 日志
# =========================

import logging
import traceback as _traceback

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_errors.log")),
        logging.StreamHandler(),
    ],
)
app_logger = logging.getLogger("netsec_app")


@app.errorhandler(500)
def internal_error(e):
    """全局 500 错误处理器：记录错误日志并返回友好页面"""
    tb = _traceback.format_exc()
    app_logger.error(f"500 内部错误:\n{tb}")
    # 尝试回滚数据库（如果处于事务中）
    try:
        db = get_db_connection()
        db.rollback()
        db.close()
    except Exception:
        pass
    return render_template("500.html", error=str(e)) if os.path.exists(
        os.path.join(app.template_folder, "500.html")
    ) else (
        "<h1>500 - 服务器内部错误</h1>"
        "<p>抱歉，服务器遇到了意外错误。错误已记录，请稍后重试。</p>"
        "<p><a href='/netsec/'>返回首页</a></p>"
    ), 500


@app.errorhandler(Exception)
def handle_exception(e):
    """捕获所有未处理异常"""
    tb = _traceback.format_exc()
    app_logger.error(f"未捕获异常: {type(e).__name__}: {e}\n{tb}")
    # 尝试回滚数据库
    try:
        db = get_db_connection()
        db.rollback()
        db.close()
    except Exception:
        pass
    return render_template("500.html", error=str(e)) if os.path.exists(
        os.path.join(app.template_folder, "500.html")
    ) else (
        "<h1>500 - 服务器内部错误</h1>"
        "<p>抱歉，服务器遇到了意外错误。错误已记录，请稍后重试。</p>"
        "<p><a href='/netsec/'>返回首页</a></p>"
    ), 500


# SCRIPT_NAME 用于 url_for 生成带前缀的 URL
if APPLICATION_ROOT:
    app.config["APPLICATION_ROOT"] = APPLICATION_ROOT


class ScriptNameMiddleware:
    """设置 SCRIPT_NAME 使 url_for 生成带 /netsec 前缀的 URL。
    
    Nginx 配置 proxy_pass http://netsec_platform/; 已经剥离了 /netsec/ 前缀，
    所以 PATH_INFO 到达 Flask 时已经是 /login 而不是 /netsec/login。
    这里只设置 SCRIPT_NAME，不修改 PATH_INFO。
    """
    def __init__(self, wsgi_app, script_name=None):
        self.wsgi_app = wsgi_app
        self.script_name = script_name or APPLICATION_ROOT

    def __call__(self, environ, start_response):
        if self.script_name:
            environ["SCRIPT_NAME"] = self.script_name
        return self.wsgi_app(environ, start_response)


# 如果设置了 APPLICATION_ROOT，包装 app 使其正确处理子路径
if APPLICATION_ROOT:
    app.wsgi_app = ScriptNameMiddleware(app.wsgi_app, APPLICATION_ROOT)


# =========================
# 数据库配置
# =========================

DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_PORT = int(os.getenv("MYSQL_PORT", "3306"))
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")
DB_NAME = os.getenv("MYSQL_DB", "netsec_platform")

INIT_SQL_PATH = os.path.join(BASE_DIR, "sql", "mysql8_init.sql")

MAX_ATTEMPTS = 5
LOCK_MINUTES = 10
DB_READY = False


# =========================
# 漏洞标识 -> 路由函数名 映射
# =========================

VULN_ROUTE_MAP = {
    'brute_force': 'vuln_brute_force',
    'sqli_normal': 'vuln_sqli_normal',
    'sqli_blind': 'vuln_sqli_blind',
    'weak_session_id': 'vuln_weak_session',
    'command_injection': 'vuln_command_injection',
    'file_include': 'vuln_file_include',
    'file_upload': 'vuln_file_upload',
    'weak_captcha': 'vuln_weak_captcha',
    'xss_reflected': 'vuln_xss_reflected',
    'xss_stored': 'vuln_xss_stored',
    'xss_dom': 'vuln_xss_dom',
    'csrf': 'vuln_csrf',
    'csp_bypass': 'vuln_csp_bypass',
    'javascript_vuln': 'vuln_javascript',
}


# =========================
# 数据库连接
# =========================

def get_server_connection():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )


# =========================
# 初始化数据库
# =========================

def ensure_database_and_tables():
    if not os.path.exists(INIT_SQL_PATH):
        raise FileNotFoundError(f"数据库脚本不存在: {INIT_SQL_PATH}")

    admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin@123456")
    admin_pwd_hash = make_password_hash(admin_password)

    try:
        with open(INIT_SQL_PATH, "r", encoding="utf-8") as f:
            init_sql = f.read().format(
                DB_NAME=DB_NAME,
                ADMIN_PASSWORD_HASH=admin_pwd_hash,
                ADMIN_SALT=""
            )
    except (IOError, KeyError, ValueError) as e:
        raise RuntimeError(f"读取或解析 SQL 初始化脚本失败: {e}")

    statements = [stmt.strip() for stmt in init_sql.split(";") if stmt.strip()]
    server_conn = get_server_connection()
    try:
        with server_conn.cursor() as cursor:
            for statement in statements:
                try:
                    cursor.execute(statement)
                except pymysql.err.IntegrityError:
                    # 忽略重复插入等唯一键冲突，表已存在数据时正常跳过
                    pass
                except Exception as e:
                    app_logger.warning(f"执行 SQL 语句失败(已跳过): {str(statement)[:100]}... 错误: {e}")
        server_conn.commit()
    except Exception as e:
        server_conn.rollback()
        raise RuntimeError(f"数据库表初始化失败: {e}")
    finally:
        server_conn.close()


def migrate_users_table():
    """给旧版 users 表补上缺失的列（兼容平滑升级）"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 添加 password_salt 列（如果不存在）
            cur.execute("SHOW COLUMNS FROM users LIKE 'password_salt'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE users ADD COLUMN password_salt VARCHAR(64) NOT NULL DEFAULT ''")
                app_logger.info("已添加 users.password_salt 列")
            # 添加 role_key 列（如果不存在）
            cur.execute("SHOW COLUMNS FROM users LIKE 'role_key'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE users ADD COLUMN role_key VARCHAR(32) NOT NULL DEFAULT 'user' COMMENT '角色标识'")
                app_logger.info("已添加 users.role_key 列")
                # 将已存在的 admin 用户设为 admin 角色
                cur.execute("UPDATE users SET role_key='admin' WHERE username='admin' AND role_key='user'")
        conn.commit()
    except Exception as e:
        app_logger.warning(f"users 表迁移失败: {e}")
    finally:
        conn.close()


@app.before_request
def init_db_once():
    global DB_READY
    if DB_READY:
        return
    try:
        ensure_database_and_tables()
        migrate_users_table()
        DB_READY = True
    except Exception as e:
        app_logger.error(f"数据库初始化失败: {e}\n{_traceback.format_exc()}")
        # 不设置 DB_READY，让后续请求继续重试
        # 跳过静态文件请求的错误提示
        if not request.path.startswith(f"{APPLICATION_ROOT}/static") and request.path != f"{APPLICATION_ROOT}/api/health":
            return (
                "<h1>503 - 服务暂时不可用</h1>"
                "<p>数据库连接失败，请稍后重试或联系管理员。</p>"
                "<p><a href='javascript:location.reload()'>刷新页面</a></p>"
            ), 503


# =========================
# 登录校验装饰器
# =========================

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            flash("请先登录后再访问。", "error")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper


def admin_required(view_func):
    """管理员权限装饰器"""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            flash("请先登录后再访问。", "error")
            return redirect(url_for("login"))
        if session.get("role_key") != "admin":
            flash("需要管理员权限才能访问此页面。", "error")
            return redirect(url_for("index"))
        return view_func(*args, **kwargs)
    return wrapper


# =========================
# 审计日志辅助函数
# =========================

def record_login_history(username, login_type, ip_address):
    """记录登录/登出历史"""
    db = get_db_connection()
    try:
        user_agent = request.headers.get('User-Agent', '')
        browser = 'Unknown'
        os_name = 'Unknown'
        if 'Chrome' in user_agent:
            browser = 'Chrome'
        elif 'Firefox' in user_agent:
            browser = 'Firefox'
        elif 'Safari' in user_agent:
            browser = 'Safari'
        elif 'Edge' in user_agent:
            browser = 'Edge'
        if 'Windows' in user_agent:
            os_name = 'Windows'
        elif 'Mac OS' in user_agent:
            os_name = 'Mac OS'
        elif 'Linux' in user_agent:
            os_name = 'Linux'
        elif 'Android' in user_agent:
            os_name = 'Android'
        elif 'iOS' in user_agent:
            os_name = 'iOS'

        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO login_history (username, login_type, ip_address, browser, os, user_agent) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (username, login_type, ip_address, browser, os_name, user_agent[:500])
            )
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


def record_operation_log(username, operation_name, method=None, path=None,
                         params=None, result=1, execution_time=None):
    """记录操作日志"""
    db = get_db_connection()
    try:
        import json as _json
        params_str = _json.dumps(params, ensure_ascii=False, default=str) if params else None
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO operation_log (username, operation_name, method, path, params, result, execution_time, ip_address) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (username, operation_name, method, path, params_str, result, execution_time, get_client_ip())
            )
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


# =========================
# 登录安全
# =========================

def get_client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_locked(ip):
    try:
        db = get_db_connection()
    except Exception as e:
        app_logger.error(f"is_locked: 数据库连接失败: {e}")
        return False, 0
    try:
        with db.cursor() as cur:
            cur.execute("SELECT failed_count, lock_until FROM login_attempts WHERE ip_address=%s LIMIT 1", (ip,))
            info = cur.fetchone()
            if not info:
                return False, 0
            lock_until = info.get("lock_until")
            if lock_until and datetime.now() < lock_until:
                minutes = max(1, int((lock_until - datetime.now()).total_seconds() // 60) + 1)
                return True, minutes
            if lock_until and datetime.now() >= lock_until:
                cur.execute("DELETE FROM login_attempts WHERE ip_address=%s", (ip,))
                db.commit()
                return False, 0
            return False, 0
    except Exception as e:
        app_logger.error(f"is_locked: 查询失败: {e}")
        return False, 0
    finally:
        db.close()


def register_failed_attempt(ip):
    try:
        db = get_db_connection()
    except Exception as e:
        app_logger.error(f"register_failed_attempt: 数据库连接失败: {e}")
        return
    try:
        with db.cursor() as cur:
            cur.execute("SELECT failed_count FROM login_attempts WHERE ip_address=%s FOR UPDATE", (ip,))
            row = cur.fetchone()
            if row:
                failed_count = int(row["failed_count"]) + 1
                lock_until = datetime.now() + timedelta(minutes=LOCK_MINUTES) if failed_count >= MAX_ATTEMPTS else None
                cur.execute("UPDATE login_attempts SET failed_count=%s, lock_until=%s WHERE ip_address=%s",
                            (failed_count, lock_until, ip))
            else:
                cur.execute("INSERT INTO login_attempts (ip_address, failed_count, lock_until) VALUES (%s, %s, %s)",
                            (ip, 1, None))
        db.commit()
    except Exception as e:
        app_logger.error(f"register_failed_attempt: 操作失败: {e}")
    finally:
        db.close()


def clear_attempts(ip):
    try:
        db = get_db_connection()
    except Exception as e:
        app_logger.error(f"clear_attempts: 数据库连接失败: {e}")
        return
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM login_attempts WHERE ip_address=%s", (ip,))
        db.commit()
    except Exception as e:
        app_logger.error(f"clear_attempts: 操作失败: {e}")
    finally:
        db.close()


def build_text_captcha():
    code = "".join(random.choices("23456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=4))
    session["captcha_code"] = code
    return code


def render_login_page(locked, remaining_minutes):
    return render_template("login.html", locked=locked,
                           remaining_minutes=remaining_minutes,
                           captcha_code=build_text_captcha())


# =========================
# 通关检测辅助函数
# =========================

def record_vuln_attempt(vuln_id, passed=False):
    """记录漏洞尝试，如果成功则更新通关状态"""
    user_id = session.get("user_id")
    if not user_id:
        return

    try:
        db = get_db_connection()
    except Exception as e:
        app_logger.error(f"record_vuln_attempt: 数据库连接失败: {e}")
        return
    try:
        with db.cursor() as cur:
            # 查找已有记录
            cur.execute(
                "SELECT id, status, attempts FROM vulnerability_progress "
                "WHERE user_id=%s AND vuln_id=%s AND difficulty='low'",
                (user_id, vuln_id)
            )
            existing = cur.fetchone()

            if existing:
                new_attempts = (existing.get("attempts") or 0) + 1
                new_status = "passed" if passed else (
                    "in_progress" if existing.get("status") == "not_started" else existing.get("status")
                )
                passed_at = datetime.now() if passed and existing.get("status") != "passed" else (
                    existing.get("passed_at") if existing.get("status") == "passed" else None
                )
                cur.execute(
                    "UPDATE vulnerability_progress SET status=%s, attempts=%s, passed_at=%s "
                    "WHERE id=%s",
                    (new_status, new_attempts, passed_at, existing["id"])
                )
            else:
                cur.execute(
                    "INSERT INTO vulnerability_progress (user_id, vuln_id, difficulty, status, attempts, passed_at) "
                    "VALUES (%s, %s, 'low', %s, 1, %s)",
                    (user_id, vuln_id, "passed" if passed else "in_progress",
                     datetime.now() if passed else None)
                )
        db.commit()
    except Exception as e:
        app_logger.error(f"record_vuln_attempt: 操作失败(vuln={vuln_id}): {e}")
        db.rollback()
    finally:
        db.close()


def get_vuln_urls():
    """获取漏洞ID -> URL映射"""
    urls = {}
    for vuln_id, func_name in VULN_ROUTE_MAP.items():
        try:
            urls[vuln_id] = url_for(func_name)
        except Exception:
            pass
    return urls


def get_user_progress_map():
    """获取当前用户通关进度"""
    user_id = session.get("user_id")
    if not user_id:
        return {}
    try:
        db = get_db_connection()
    except Exception as e:
        app_logger.error(f"get_user_progress_map: 数据库连接失败: {e}")
        return {}
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT vuln_id, status, attempts, passed_at FROM vulnerability_progress WHERE user_id=%s",
                (user_id,)
            )
            return {p["vuln_id"]: p for p in cur.fetchall()}
    except Exception as e:
        app_logger.error(f"get_user_progress_map: 查询失败: {e}")
        return {}
    finally:
        db.close()


# =========================
# 基础路由
# =========================

@app.route("/")
def root():
    return redirect(url_for("login"))


# =========================
# 注册
# =========================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip() or username
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not password:
            flash("请输入用户名和密码。", "error")
            return render_template("register.html")
        if len(username) < 3 or len(username) > 64:
            flash("用户名的长度必须在 3~64 位之间。", "error")
            return render_template("register.html")
        if len(password) < 8:
            flash("密码长度不能小于 8 位。", "error")
            return render_template("register.html")
        # 密码强度校验
        if not any(c.isupper() for c in password):
            flash("密码必须包含至少一个大写字母。", "error")
            return render_template("register.html")
        if not any(c.islower() for c in password):
            flash("密码必须包含至少一个小写字母。", "error")
            return render_template("register.html")
        if not any(c.isdigit() for c in password):
            flash("密码必须包含至少一个数字。", "error")
            return render_template("register.html")
        if password != confirm_password:
            flash("两次输入的密码不一致！", "error")
            return render_template("register.html")

        db = get_db_connection()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (username,))
                if cur.fetchone():
                    flash("用户名已经存在，请更换后重试。", "error")
                    return render_template("register.html")
                pwd_hash = make_password_hash(password)
                cur.execute(
                    "INSERT INTO users (username, display_name, password_hash, role_key) "
                    "VALUES (%s, %s, %s, 'user')",
                    (username, display_name, pwd_hash)
                )
            db.commit()
        except Exception as e:
            app_logger.error(f"register: 数据库操作失败: {e}")
            db.rollback()
            flash("注册失败，服务器内部错误，请稍后重试。", "error")
            return render_template("register.html")
        finally:
            db.close()

        flash("注册成功，请登录。", "success")
        record_operation_log(username, "用户注册", "POST", "/register", result=1)
        return redirect(url_for("login"))

    return render_template("register.html")


# =========================
# 登录
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_client_ip()
    locked, remaining_minutes = is_locked(ip)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        captcha = request.form.get("captcha", "").strip().upper()
        remember = request.form.get("remember") == "on"

        if locked:
            flash(f"登录账号已经被临时锁定，请 {remaining_minutes} 分钟后重试。", "error")
            return render_login_page(locked=True, remaining_minutes=remaining_minutes)

        expected_captcha = session.get("captcha_code", "")
        if not captcha:
            flash("请输入验证码。", "error")
            return render_login_page(locked=False, remaining_minutes=0)
        if not expected_captcha or captcha != expected_captcha:
            register_failed_attempt(ip)
            locked, remaining_minutes = is_locked(ip)
            flash("验证码错误。", "error")
            return render_login_page(locked=locked, remaining_minutes=remaining_minutes)

        if not username or not password:
            flash("请输入用户名和密码。", "error")
            return render_login_page(locked=False, remaining_minutes=0)

        db = get_db_connection()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT id, username, display_name, password_hash, role_key, is_active "
                    "FROM users WHERE username=%s LIMIT 1",
                    (username,)
                )
                user = cur.fetchone()
        except Exception as e:
            app_logger.error(f"login: 用户查询失败: {e}")
            flash("服务器内部错误，请稍后重试。", "error")
            return render_login_page(locked=False, remaining_minutes=0)
        finally:
            db.close()

        if not user or not user.get("is_active"):
            register_failed_attempt(ip)
            locked, remaining_minutes = is_locked(ip)
            flash("账号或者密码错误。", "error")
            return render_login_page(locked=locked, remaining_minutes=remaining_minutes)

        pwd_ok = verify_password(password, user["password_hash"])

        if not pwd_ok:
            register_failed_attempt(ip)
            locked, remaining_minutes = is_locked(ip)
            flash("账号或者密码错误。", "error")
            record_operation_log(username, "登录失败", "POST", "/login", result=0)
            return render_login_page(locked=locked, remaining_minutes=remaining_minutes)

        # 登录成功
        clear_attempts(ip)
        session.pop("captcha_code", None)
        session.permanent = remember
        session["user_id"] = user["id"]
        session["user"] = user["username"]
        session["display_name"] = user["display_name"]
        session["role_key"] = user.get("role_key", "user")
        session["login_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 更新最后登录信息
        db2 = get_db_connection()
        try:
            with db2.cursor() as cur:
                cur.execute(
                    "UPDATE users SET last_login_at=NOW(), last_login_ip=%s WHERE id=%s",
                    (ip, user["id"])
                )
            db2.commit()
        except Exception as e:
            app_logger.error(f"login: 更新登录信息失败: {e}")
            db2.rollback()
        finally:
            db2.close()

        record_login_history(username, 1, ip)
        record_operation_log(username, "用户登录", "POST", "/login", result=1)
        return redirect(url_for("index"))

    return render_login_page(locked=locked, remaining_minutes=remaining_minutes)


# =========================
# 首页
# =========================

@app.route("/index")
@login_required
def index():
    user_id = session.get("user_id")
    user_status = get_user_status(user_id)
    return render_template(
        "index.html",
        display_name=session.get("display_name", "用户"),
        login_time=session.get("login_time", "-"),
        role_key=session.get("role_key", "user"),
        user_status=user_status,
    )


# =========================
# 安全靶场
# =========================

@app.route("/range")
@login_required
def range_page():
    return render_template("range.html")


# =========================
# 端口扫描
# =========================

@app.route("/scan/port", methods=["GET", "POST"])
@login_required
def port_scan_page():
    if request.method != "POST":
        user_id = session.get("user_id")
        status = get_user_status(user_id)
        return render_template("port_scan.html", user_status=status)

    # 积分/配额检查（已隐藏）
    # user_id = session.get("user_id")
    # usage = payment_manager.check_and_consume_usage(user_id, "port_scan")
    # if not usage["allowed"]:
    #     flash(usage["message"], "error")
    #     return redirect(url_for("pricing_page"))

    target = request.form.get("target", "").strip()
    ports = request.form.get("ports", "1-1024").strip()
    try:
        timeout = float(request.form.get("timeout", 1))
    except ValueError:
        timeout = 1
    try:
        workers = int(request.form.get("workers", 50))
    except ValueError:
        workers = 50

    if not target:
        flash("请输入扫描目标。", "error")
        return redirect(url_for("port_scan_page"))
    if not ports:
        ports = "1-1024"
    if timeout <= 0:
        timeout = 1
    workers = max(1, min(workers, 200))

    try:
        assistant = NetSecAssistant(timeout=timeout, workers=workers)
    except TypeError:
        assistant = NetSecAssistant()
        assistant.timeout = timeout
        assistant.workers = workers

    try:
        open_ports = assistant.run_port_scan(target, ports)
        if open_ports is None:
            open_ports = []
    except Exception as e:
        flash(f"端口扫描失败：{e}", "error")
        return redirect(url_for("port_scan_page"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO scan_tasks (user_id, username, task_type, target, params, status, finished_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                (session.get("user_id"), session.get("user"), "port_scan", target,
                 json.dumps({"ports": ports, "timeout": timeout, "workers": workers}, ensure_ascii=False), "done")
            )
            task_id = cur.lastrowid
            for port in open_ports:
                cur.execute(
                    "INSERT INTO port_scan_results (task_id, port, protocol, status) VALUES (%s, %s, %s, %s)",
                    (task_id, int(port), "tcp", "open")
                )
        db.commit()
    except Exception as e:
        db.rollback()
        flash(f"扫描结果保存失败：{e}", "error")
        return redirect(url_for("port_scan_page"))
    finally:
        db.close()

    return redirect(url_for("port_result", task_id=task_id))


@app.route("/scan/port/result/<int:task_id>")
@login_required
def port_result(task_id):
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM scan_tasks WHERE id=%s AND username=%s LIMIT 1",
                        (task_id, session.get("user")))
            task = cur.fetchone()
            if not task:
                flash("扫描任务不存在或无权限查看。", "error")
                return redirect(url_for("scan_history"))
            cur.execute("SELECT * FROM port_scan_results WHERE task_id=%s ORDER BY port ASC", (task_id,))
            results = cur.fetchall()
    finally:
        db.close()
    return render_template("port_result.html", task=task, results=results)


@app.route("/scan/history")
@login_required
def scan_history():
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM scan_tasks WHERE username=%s ORDER BY created_at DESC",
                        (session.get("user"),))
            tasks = cur.fetchall()
    finally:
        db.close()
    return render_template("scan_history.html", tasks=tasks)


# =========================
# 网络探测
# =========================

@app.route("/scan/network", methods=["GET", "POST"])
@login_required
def network_scan_page():
    if request.method != "POST":
        return render_template("network_scan.html", results=None, error=None)

    network = request.form.get("network", "").strip()
    try:
        timeout = float(request.form.get("timeout", 1))
    except ValueError:
        timeout = 1
    try:
        workers = int(request.form.get("workers", 100))
    except ValueError:
        workers = 100

    if not network:
        flash("请输入目标网段。", "error")
        return redirect(url_for("network_scan_page"))

    workers = max(1, min(workers, 500))

    try:
        live_hosts = network_scan.discover_hosts(network, timeout=timeout, workers=workers)
        if live_hosts is None:
            live_hosts = []
    except Exception as e:
        return render_template("network_scan.html", results=None, error=str(e))

    return render_template("network_scan.html", results=live_hosts, error=None)


# =========================
# WAF 检测
# =========================

@app.route("/scan/waf", methods=["GET", "POST"])
@login_required
def waf_detect_page():
    if request.method != "POST":
        return render_template("waf_detect.html", results=None, logs=None, error=None)

    url = request.form.get("url", "").strip()
    try:
        timeout = float(request.form.get("timeout", 5))
    except ValueError:
        timeout = 5

    if not url:
        flash("请输入目标 URL。", "error")
        return redirect(url_for("waf_detect_page"))

    if not url.startswith("http"):
        url = "http://" + url

    try:
        assistant = NetSecAssistant(timeout=timeout)
        # 清空之前日志
        assistant.results_log = []
        assistant.detect_waf(url)
        logs = "\n".join(assistant.results_log)

        # 解析检测结果
        detected = []
        for line in assistant.results_log:
            if "检测到WAF" in line:
                waf_names = line.split("检测到WAF:")[-1].strip()
                for name in waf_names.split(","):
                    detected.append({"name": name.strip(), "method": "响应特征分析"})
    except Exception as e:
        return render_template("waf_detect.html", results=None, logs=None, error=str(e))

    return render_template("waf_detect.html", results=detected if detected else [], logs=logs, error=None)


# =========================
# 服务指纹识别
# =========================

@app.route("/scan/fingerprint", methods=["GET", "POST"])
@login_required
def fingerprint_page():
    if request.method != "POST":
        return render_template("fingerprint.html", results=None, error=None)

    target = request.form.get("target", "").strip()
    ports_str = request.form.get("ports", "22,80,443,3306,8080").strip()
    try:
        timeout = float(request.form.get("timeout", 2))
    except ValueError:
        timeout = 2

    if not target:
        flash("请输入目标地址。", "error")
        return redirect(url_for("fingerprint_page"))

    try:
        assistant = NetSecAssistant(timeout=timeout)
        # 解析端口
        ports = assistant.parse_ports(ports_str)

        try:
            target_ip = socket.gethostbyname(target)
        except socket.gaierror:
            return render_template("fingerprint.html", results=None, error=f"无法解析主机: {target}")

        results = []
        for port in ports:
            is_open = assistant.scan_port(target_ip, port)
            if is_open:
                banner = assistant.get_banner(target_ip, port)
                # 简单服务类型判断
                service = "未知"
                if "Apache" in banner:
                    service = "Apache"
                elif "Nginx" in banner:
                    service = "Nginx"
                elif "SSH" in banner or "ssh" in banner.lower():
                    service = "SSH"
                elif "MySQL" in banner or "mysql" in banner.lower():
                    service = "MySQL"
                elif "FTP" in banner:
                    service = "FTP"
                elif "SMTP" in banner:
                    service = "SMTP"
                elif "Microsoft" in banner:
                    service = "IIS"
                results.append({
                    "port": port,
                    "status": "开放",
                    "service": service,
                    "banner": banner[:100]
                })
    except Exception as e:
        return render_template("fingerprint.html", results=None, error=str(e))

    return render_template("fingerprint.html", results=results, error=None)


# =========================
# Web 目录扫描
# =========================

@app.route("/scan/webdir", methods=["GET", "POST"])
@login_required
def web_dir_scan_page():
    if request.method != "POST":
        return render_template("web_dir_scan.html", results=None, error=None)

    url = request.form.get("url", "").strip()
    try:
        timeout = float(request.form.get("timeout", 3))
    except ValueError:
        timeout = 3
    try:
        workers = int(request.form.get("workers", 20))
    except ValueError:
        workers = 20

    if not url:
        flash("请输入目标 URL。", "error")
        return redirect(url_for("web_dir_scan_page"))

    if not url.startswith("http"):
        url = "http://" + url

    workers = max(1, min(workers, 100))

    try:
        # 使用 network_scan 中的目录扫描函数
        DEFAULT_DICT = ["admin", "login", "index.php", "backup", "db", "config", ".git", "robots.txt", "wp-admin"]
        results = []
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(network_scan.scan_dir, url, path, timeout): path for path in DEFAULT_DICT}
            for future in as_completed(future_map):
                result = future.result()
                if result:
                    path, code, size = result
                    results.append({"path": path, "code": code, "size": size})
        results.sort(key=lambda x: x["code"])
    except Exception as e:
        return render_template("web_dir_scan.html", results=None, error=str(e))

    return render_template("web_dir_scan.html", results=results, error=None)


# =========================
# 子域名枚举
# =========================

@app.route("/scan/subdomain", methods=["GET", "POST"])
@login_required
def subdomain_enum_page():
    if request.method != "POST":
        return render_template("subdomain_enum.html", results=None, error=None)

    domain = request.form.get("domain", "").strip()
    try:
        timeout = float(request.form.get("timeout", 2))
    except ValueError:
        timeout = 2
    try:
        workers = int(request.form.get("workers", 50))
    except ValueError:
        workers = 50

    if not domain:
        flash("请输入目标域名。", "error")
        return redirect(url_for("subdomain_enum_page"))

    # 清洗域名
    domain = domain.replace("http://", "").replace("https://", "").split("/")[0]
    workers = max(1, min(workers, 200))

    try:
        assistant = NetSecAssistant(timeout=timeout, workers=workers)
        valid_subs = assistant.run_subdomain_enum(domain)
        if valid_subs is None:
            valid_subs = []
    except Exception as e:
        return render_template("subdomain_enum.html", results=None, error=str(e))

    return render_template("subdomain_enum.html", results=valid_subs, error=None)


# =========================
# DVWA 相关路由
# =========================

@app.route("/dvwa/overview")
@login_required
def dvwa_overview():
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) as total FROM vulnerabilities WHERE is_active=1")
            total = cur.fetchone()['total']
            cur.execute(
                "SELECT COUNT(*) as completed FROM vulnerability_progress WHERE user_id=%s AND status='passed'",
                (session.get("user_id"),)
            )
            completed = cur.fetchone()['completed']
            # 按分类统计
            cur.execute("SELECT category, COUNT(*) as cnt FROM vulnerabilities WHERE is_active=1 GROUP BY category")
            cat_rows = cur.fetchall()
    finally:
        db.close()

    cat_icons = {'认证': ('bi-key-fill', 'primary'), '注入': ('bi-syringe-fill', 'success'),
                 'XSS': ('bi-search', 'warning'), '文件': ('bi-file-earmark-text-fill', 'info'),
                 '客户端': ('bi-window-stack', 'secondary')}
    categories = []
    for row in cat_rows:
        cat = row['category']
        icon, color = cat_icons.get(cat, ('bi-bug-fill', 'dark'))
        categories.append({'name': cat, 'count': row['cnt'], 'icon': icon, 'color': color})

    import flask
    stats = {
        'total': total, 'completed': completed,
        'remaining': total - completed,
        'progress': int(completed / total * 100) if total > 0 else 0
    }

    return render_template("dvwa_overview.html",
                           php_version="8.1.0",
                           server_info="Flask Development Server",
                           python_version=sys.version.split()[0],
                           flask_version=flask.__version__,
                           stats=stats, categories=categories)


@app.route("/dvwa/env")
@login_required
def dvwa_env():
    import flask
    db = get_db_connection()
    db_version = "MySQL 8.x"
    table_count = 0
    try:
        with db.cursor() as cur:
            cur.execute("SELECT VERSION() as v")
            row = cur.fetchone()
            if row:
                db_version = row['v']
            cur.execute("SELECT COUNT(*) as cnt FROM information_schema.tables WHERE table_schema=%s", (DB_NAME,))
            row = cur.fetchone()
            if row:
                table_count = row['cnt']
    except Exception:
        pass
    finally:
        db.close()

    return render_template("dvwa_env.html",
                           server_info="Flask Development Server",
                           server_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           python_version=sys.version.split()[0],
                           flask_version=flask.__version__,
                           db_name=DB_NAME,
                           db_version=db_version,
                           table_count=table_count,
                           os_info=f"{platform.system()} {platform.release()}")


@app.route("/dvwa/vulnerabilities")
@login_required
def dvwa_vulnerabilities():
    vulns = []
    try:
        db = get_db_connection()
    except Exception as e:
        app_logger.error(f"dvwa_vulnerabilities: 数据库连接失败: {e}")
        return render_template("dvwa_vulnerabilities.html", vulns=vulns, error="数据库连接失败")
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM vulnerabilities WHERE is_active=1 ORDER BY category, id")
            vulns = cur.fetchall()
            # 获取用户通关状态
            progress_map = get_user_progress_map()
            for v in vulns:
                v['url'] = get_vuln_urls().get(v['vuln_id'], '#')
                v['passed'] = progress_map.get(v['vuln_id'], {}).get('status') == 'passed'
    except Exception as e:
        app_logger.error(f"dvwa_vulnerabilities: 查询失败: {e}")
        vulns = []
    finally:
        db.close()
    return render_template("dvwa_vulnerabilities.html", vulns=vulns)


# =========================
# 通关检测 API
# =========================

@app.route("/api/vuln/check_pass", methods=["POST"])
@login_required
def api_vuln_check_pass():
    """通关检测API - 前端JS提交后自动调用"""
    data = request.get_json(silent=True) or {}
    vuln_id = data.get("vuln_id", "")
    if not vuln_id:
        return jsonify({"passed": False, "message": "缺少参数"})

    user_id = session.get("user_id")
    try:
        db = get_db_connection()
    except Exception as e:
        app_logger.error(f"api_vuln_check_pass: 数据库连接失败: {e}")
        return jsonify({"passed": False, "message": "服务器内部错误"}), 500
    try:
        with db.cursor() as cur:
            # 检查漏洞是否存在且启用
            cur.execute("SELECT id, name FROM vulnerabilities WHERE vuln_id=%s AND is_active=1", (vuln_id,))
            vuln = cur.fetchone()
            if not vuln:
                return jsonify({"passed": False, "message": "漏洞不存在"})

            # 检查用户是否已通关
            cur.execute(
                "SELECT status FROM vulnerability_progress WHERE user_id=%s AND vuln_id=%s AND difficulty='low'",
                (user_id, vuln_id)
            )
            progress = cur.fetchone()

            if progress and progress['status'] == 'passed':
                return jsonify({"passed": True, "message": f"「{vuln['name']}」已通关！"})

            # 标记为进行中
            if not progress:
                cur.execute(
                    "INSERT INTO vulnerability_progress (user_id, vuln_id, difficulty, status, attempts) "
                    "VALUES (%s, %s, 'low', 'in_progress', 1)",
                    (user_id, vuln_id)
                )
                db.commit()

            return jsonify({"passed": False, "message": "继续加油！"})
    except Exception as e:
        app_logger.error(f"api_vuln_check_pass: 操作失败(vuln={vuln_id}): {e}")
        db.rollback()
        return jsonify({"passed": False, "message": "检测失败，请重试"}), 500
    finally:
        db.close()


# =========================
# 漏洞练习路由 - 认证类
# =========================

@app.route("/vuln/brute_force", methods=["GET", "POST"])
@login_required
def vuln_brute_force():
    error = None
    success = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        captcha = request.form.get("captcha", "").strip()

        if username == "admin" and password == "password":
            success = username
            record_vuln_attempt("brute_force", passed=True)
        else:
            if captcha == "1234":
                error = "用户名或密码错误"
            else:
                error = "验证码错误"
            record_vuln_attempt("brute_force", passed=False)

    return render_template("vulnerabilities/brute_force.html", error=error, success=success)


@app.route("/vuln/weak_session", methods=["GET", "POST"])   # 修复：增加 methods
@login_required
def vuln_weak_session():
    import time

    session_id = session.get("weak_session_id", f"sess_{session.get('user_id', 1)}_{int(time.time())}")

    if request.method == "POST":
        new_session_id = request.form.get("session_id", "")
        if new_session_id:
            session["weak_session_id"] = new_session_id
            record_vuln_attempt("weak_session_id", passed=True)
            return render_template("vulnerabilities/weak_session.html",
                                  session_id=new_session_id, success=new_session_id)

    return render_template("vulnerabilities/weak_session.html", session_id=session_id)


@app.route("/vuln/weak_session/gen")
@login_required
def vuln_weak_session_gen():
    import time
    new_id = f"sess_{session.get('user_id', 1)}_{int(time.time())}"
    session["weak_session_id"] = new_id
    record_vuln_attempt("weak_session_id", passed=False)
    return jsonify({"session_id": new_id})


@app.route("/vuln/weak_captcha", methods=["GET", "POST"])
@login_required
def vuln_weak_captcha():
    captchas = ["1234", "5678", "0000", "9999", "abcd"]
    current_captcha = random.choice(captchas)
    session["weak_captcha"] = current_captcha

    error = None
    success = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        captcha = request.form.get("captcha", "").strip()

        if captcha == session.get("weak_captcha"):
            if username == "admin" and password == "admin":
                success = "登录成功（演示模式）"
                record_vuln_attempt("weak_captcha", passed=True)
            else:
                error = "用户名或密码错误"
                record_vuln_attempt("weak_captcha", passed=False)
        else:
            error = "验证码错误"
            record_vuln_attempt("weak_captcha", passed=False)

    return render_template("vulnerabilities/weak_captcha.html",
                           current_captcha=current_captcha, error=error, success=success)


@app.route("/vuln/csrf", methods=["GET", "POST"])
@login_required
def vuln_csrf():
    error = None
    success = None

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if new_password != confirm_password:
            error = "两次输入的密码不一致"
        elif len(new_password) < 6:
            error = "密码长度不能少于6位"
        else:
            success = "密码修改成功！（这是演示，实际密码并未修改）"
            record_vuln_attempt("csrf", passed=True)

    return render_template("vulnerabilities/csrf.html", error=error, success=success,
                           csrf_token=None, csrf_target_url=url_for("vuln_csrf", _external=True))


# =========================
# 漏洞练习路由 - 注入类
# =========================

@app.route("/vuln/sqli_normal", methods=["GET", "POST"])
@login_required
def vuln_sqli_normal():
    result = None
    error = None

    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        if user_id:
            db = get_db_connection()
            try:
                with db.cursor() as cur:
                    sql = f"SELECT id, username, display_name, is_active FROM users WHERE id={user_id}"
                    cur.execute(sql)
                    result = cur.fetchall()
                    record_vuln_attempt("sqli_normal", passed=bool(result))
            except Exception as e:
                error = f"查询错误: {str(e)}"
                record_vuln_attempt("sqli_normal", passed=False)
            finally:
                db.close()

    return render_template("vulnerabilities/sqli_normal.html", result=result, error=error)


@app.route("/vuln/sqli_blind", methods=["GET", "POST"])
@login_required
def vuln_sqli_blind():
    result = None
    not_found = False
    error = None

    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        if user_id:
            db = get_db_connection()
            try:
                with db.cursor() as cur:
                    sql = f"SELECT id, username FROM users WHERE id={user_id}"
                    cur.execute(sql)
                    user = cur.fetchone()
                    if user:
                        result = f"用户ID {user['id']} 用户名: {user['username']}"
                        record_vuln_attempt("sqli_blind", passed=True)
                    else:
                        not_found = True
                        record_vuln_attempt("sqli_blind", passed=False)
            except Exception as e:
                error = f"查询错误: {str(e)}"
                record_vuln_attempt("sqli_blind", passed=False)
            finally:
                db.close()

    return render_template("vulnerabilities/sqli_blind.html",
                           result=result, not_found=not_found, error=error)


@app.route("/vuln/command_injection", methods=["GET", "POST"])
@login_required
def vuln_command_injection():
    result = None
    error = None

    if request.method == "POST":
        target = request.form.get("target", "").strip()
        if target:
            try:
                import subprocess
                cmd = f"ping -n 2 {target}"
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                output, _ = proc.communicate(timeout=10)
                result = output.decode('gbk', errors='ignore')
                # 如果包含注入符号则认为通关
                injected = any(c in target for c in ['&', ';', '|', '&&', '||', '`'])
                record_vuln_attempt("command_injection", passed=injected)
            except subprocess.TimeoutExpired:
                error = "命令执行超时"
                record_vuln_attempt("command_injection", passed=False)
            except Exception as e:
                error = f"执行错误: {str(e)}"
                record_vuln_attempt("command_injection", passed=False)

    return render_template("vulnerabilities/command_injection.html", result=result, error=error)


# =========================
# 漏洞练习路由 - 文件类
# =========================

@app.route("/vuln/file_include", methods=["GET", "POST"])
@login_required
def vuln_file_include():
    content = None
    error = None

    if request.method == "POST":
        filename = request.form.get("file", "") or request.form.get("file_path", "")
        filename = filename.strip()

        if not filename:
            error = "请选择或输入文件路径"
        else:
            # 预置文件
            allowed_files = {
                "info.txt": "这是信息文件的内容。\n包含一些系统配置信息。\n版本: 1.0.0",
                "welcome.txt": "欢迎来到DVWA漏洞练习平台！\n这里有14个漏洞等待你来挑战。",
                "help.txt": "这是帮助文件。如需帮助请联系管理员。\n邮箱: admin@dvwa.local"
            }

            if filename in allowed_files:
                content = allowed_files[filename]
                record_vuln_attempt("file_include", passed=False)
            else:
                # 漏洞：路径遍历，真正读取文件
                safe_base = os.path.join(BASE_DIR, "uploads", "include_files")
                os.makedirs(safe_base, exist_ok=True)

                # 尝试路径遍历
                target_path = os.path.normpath(os.path.join(safe_base, filename))

                # 安全限制：只允许读取特定目录或特定系统文件
                # 漏洞：没有正确限制路径遍历
                try:
                    # 尝试直接读取（模拟LFI）
                    # Windows系统可读取的常见文件
                    if ".." in filename or "/" in filename or "\\" in filename:
                        # 路径遍历尝试 - 实际读取文件
                        real_path = os.path.normpath(filename)
                        if os.path.isabs(real_path):
                            target_path = real_path
                        else:
                            # 尝试从项目根目录往上遍历
                            target_path = os.path.normpath(os.path.join(BASE_DIR, filename))

                        if os.path.isfile(target_path):
                            try:
                                with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                record_vuln_attempt("file_include", passed=True)
                            except PermissionError:
                                error = f"权限不足，无法读取: {filename}"
                                record_vuln_attempt("file_include", passed=False)
                            except Exception as e:
                                error = f"读取错误: {str(e)}"
                                record_vuln_attempt("file_include", passed=False)
                        else:
                            error = f"文件不存在: {filename}"
                            record_vuln_attempt("file_include", passed=False)
                    else:
                        error = f"文件不存在: {filename}"
                        record_vuln_attempt("file_include", passed=False)
                except Exception as e:
                    error = f"错误: {str(e)}"
                    record_vuln_attempt("file_include", passed=False)

    return render_template("vulnerabilities/file_include.html", content=content, error=error)


@app.route("/vuln/file_upload", methods=["GET", "POST"])
@login_required
def vuln_file_upload():
    success = None
    error = None
    upload_dir = os.path.join(BASE_DIR, "uploads")
    try:
        os.makedirs(upload_dir, exist_ok=True)
    except OSError as e:
        app_logger.error(f"file_upload: 创建上传目录失败: {e}")
        error = f"服务器文件系统错误，无法创建上传目录。"
        return render_template("vulnerabilities/file_upload.html",
                              success=success, error=error, uploaded_files=[])

    if request.method == "POST":
        if 'file' not in request.files:
            error = "没有选择文件"
        else:
            file = request.files['file']
            if file.filename == '':
                error = "没有选择文件"
            else:
                try:
                    filename = file.filename
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    success = {
                        'filename': filename,
                        'path': filepath,
                        'size': os.path.getsize(filepath)
                    }
                    record_vuln_attempt("file_upload", passed=True)
                except Exception as e:
                    app_logger.error(f"file_upload: 文件保存失败: {e}")
                    error = f"文件上传失败: {str(e)}"

    # 获取已上传文件列表
    uploaded_files = []
    try:
        for f in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, f)
            if os.path.isfile(fpath):
                uploaded_files.append({
                'name': f,
                'size': f"{os.path.getsize(fpath)} 字节",
                'url': url_for('uploaded_file', filename=f)
            })
    except OSError as e:
        app_logger.error(f"file_upload: 读取文件列表失败: {e}")

    return render_template("vulnerabilities/file_upload.html",
                           success=success, error=error, uploaded_files=uploaded_files)


@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
    """提供已上传文件的访问"""
    upload_dir = os.path.join(BASE_DIR, "uploads")
    return send_from_directory(upload_dir, filename)


# =========================
# 漏洞练习路由 - XSS类
# =========================

@app.route("/vuln/xss_reflected", methods=["GET", "POST"])
@login_required
def vuln_xss_reflected():
    search_value = request.args.get("search", "")
    xss_result = None

    if search_value:
        xss_result = search_value
        # 如果包含脚本标签则通关
        has_script = '<script' in search_value.lower() or 'onerror' in search_value.lower() or 'onload' in search_value.lower()
        record_vuln_attempt("xss_reflected", passed=has_script)

    return render_template("vulnerabilities/xss_reflected.html",
                           search_value=search_value, xss_result=xss_result,
                           test_url=url_for("vuln_xss_reflected",
                                            search="<script>alert('XSS')</script>", _external=True))


@app.route("/vuln/xss_stored", methods=["GET", "POST"])
@login_required
def vuln_xss_stored():
    success = None
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT name, message, created_at FROM xss_messages ORDER BY created_at DESC LIMIT 20")
            messages = cur.fetchall()
    except Exception as e:
        # 表可能不存在，尝试创建
        app_logger.warning(f"xss_stored: 查询消息失败(尝试建表): {e}")
        with db.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS xss_messages (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(64) NOT NULL,
                    message TEXT NOT NULL,
                    user_id BIGINT UNSIGNED,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        db.commit()
        messages = []
    finally:
        db.close()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        message = request.form.get("message", "").strip()
        if name and message:
            db = get_db_connection()
            try:
                with db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO xss_messages (name, message, user_id) VALUES (%s, %s, %s)",
                        (name, message, session.get("user_id"))
                    )
                db.commit()
                success = "留言发布成功！"

                has_script = '<script' in message.lower() or 'onerror' in message.lower() or 'onload' in message.lower()
                record_vuln_attempt("xss_stored", passed=has_script)

                with db.cursor() as cur:
                    cur.execute("SELECT name, message, created_at FROM xss_messages ORDER BY created_at DESC LIMIT 20")
                    messages = cur.fetchall()
            except Exception as e:
                success = f"发生错误: {str(e)}"
            finally:
                db.close()

    return render_template("vulnerabilities/xss_stored.html", success=success, messages=messages)


@app.route("/vuln/xss_stored/clear", methods=["POST"])
@login_required
def vuln_xss_stored_clear():
    """清空存储型XSS留言"""
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM xss_messages")
        db.commit()
    finally:
        db.close()
    flash("所有留言已清空。", "success")
    return redirect(url_for("vuln_xss_stored"))


@app.route("/vuln/xss_dom", methods=["GET", "POST"])
@login_required
def vuln_xss_dom():
    # DOM XSS 的通关检测通过前端JS完成
    return render_template("vulnerabilities/xss_dom.html",
                           test_url=url_for("vuln_xss_dom",
                                            default="<script>alert('DOM XSS')</script>", _external=True))


# =========================
# 漏洞练习路由 - 客户端类
# =========================

@app.route("/vuln/csp_bypass", methods=["GET", "POST"])
@login_required
def vuln_csp_bypass():
    csp_policy = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'"
    # 通关检测通过前端JS完成
    return render_template("vulnerabilities/csp_bypass.html", csp_policy=csp_policy)


@app.route("/vuln/javascript", methods=["GET", "POST"])
@login_required
def vuln_javascript():
    url_token = request.args.get("token", "")
    # 通关检测通过前端JS完成
    return render_template("vulnerabilities/javascript.html", url_token=url_token)


# =========================
# 通关记录
# =========================

@app.route("/progress")
@login_required
def progress_page():
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM vulnerabilities WHERE is_active=1 ORDER BY category, id")
            vulnerabilities = cur.fetchall()

            cur.execute(
                "SELECT vuln_id, status, attempts, passed_at FROM vulnerability_progress WHERE user_id=%s",
                (session.get("user_id"),)
            )
            progress_list = cur.fetchall()
            progress_map = {p['vuln_id']: p for p in progress_list}

            total = len(vulnerabilities)
            completed = sum(1 for p in progress_list if p['status'] == 'passed')
            in_progress = sum(1 for p in progress_list if p['status'] == 'in_progress')

            category_stats = {}
            for vuln in vulnerabilities:
                cat = vuln['category']
                if cat not in category_stats:
                    category_stats[cat] = {'total': 0, 'completed': 0}
                category_stats[cat]['total'] += 1
                if progress_map.get(vuln['vuln_id'], {}).get('status') == 'passed':
                    category_stats[cat]['completed'] += 1
    finally:
        db.close()

    return render_template("progress.html",
                           vulnerabilities=vulnerabilities,
                           progress_map=progress_map,
                           stats={'total': total, 'completed': completed,
                                  'in_progress': in_progress, 'remaining': total - completed},
                           category_stats=category_stats,
                           vuln_urls=get_vuln_urls())


# =========================
# 题目管理 CRUD
# =========================

@app.route("/admin/challenges")
@login_required
@admin_required
def admin_challenges():
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM vulnerabilities ORDER BY category, id")
            vulnerabilities = cur.fetchall()

            category_stats = {}
            for vuln in vulnerabilities:
                cat = vuln['category']
                category_stats[cat] = category_stats.get(cat, 0) + 1
    finally:
        db.close()

    return render_template("admin_challenges.html",
                           vulnerabilities=vulnerabilities,
                           category_stats=category_stats,
                           vuln_urls=get_vuln_urls())


@app.route("/admin/challenges/add", methods=["POST"])
@login_required
@admin_required
def admin_challenges_add():
    """新增题目"""
    vuln_id = request.form.get("vuln_id", "").strip()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    difficulty = request.form.get("difficulty", "low").strip()
    description_zh = request.form.get("description_zh", "").strip()
    hint = request.form.get("hint", "").strip()

    if not vuln_id or not name:
        flash("漏洞标识和名称不能为空。", "error")
        return redirect(url_for("admin_challenges"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT id FROM vulnerabilities WHERE vuln_id=%s", (vuln_id,))
            if cur.fetchone():
                flash(f"漏洞标识 {vuln_id} 已存在。", "error")
                return redirect(url_for("admin_challenges"))
            cur.execute(
                "INSERT INTO vulnerabilities (vuln_id, name, category, difficulty, description_zh, hint) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (vuln_id, name, category, difficulty, description_zh or None, hint or None)
            )
        db.commit()
        flash(f"题目「{name}」添加成功！", "success")
    except Exception as e:
        db.rollback()
        flash(f"添加失败: {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("admin_challenges"))


@app.route("/admin/challenges/edit", methods=["POST"])
@login_required
@admin_required
def admin_challenges_edit():
    """编辑题目"""
    vuln_db_id = request.form.get("vuln_db_id", "").strip()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    difficulty = request.form.get("difficulty", "low").strip()
    is_active = int(request.form.get("is_active", 1))

    if not vuln_db_id or not name:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_challenges"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE vulnerabilities SET name=%s, category=%s, difficulty=%s, is_active=%s WHERE id=%s",
                (name, category, difficulty, is_active, vuln_db_id)
            )
        db.commit()
        flash(f"题目「{name}」更新成功！", "success")
    except Exception as e:
        db.rollback()
        flash(f"更新失败: {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("admin_challenges"))


@app.route("/admin/challenges/toggle", methods=["POST"])
@login_required
@admin_required
def admin_challenges_toggle():
    """切换题目启用/禁用"""
    vuln_db_id = request.form.get("vuln_db_id", "").strip()
    is_active = int(request.form.get("is_active", 1))

    if not vuln_db_id:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_challenges"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE vulnerabilities SET is_active=%s WHERE id=%s", (is_active, vuln_db_id))
        db.commit()
        flash("题目状态已更新！", "success")
    except Exception as e:
        db.rollback()
        flash(f"操作失败: {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("admin_challenges"))


@app.route("/admin/challenges/delete", methods=["POST"])
@login_required
@admin_required
def admin_challenges_delete():
    """删除题目"""
    vuln_db_id = request.form.get("vuln_db_id", "").strip()

    if not vuln_db_id:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_challenges"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT name FROM vulnerabilities WHERE id=%s", (vuln_db_id,))
            vuln = cur.fetchone()
            if vuln:
                cur.execute("DELETE FROM vulnerabilities WHERE id=%s", (vuln_db_id,))
                db.commit()
                flash(f"题目「{vuln['name']}」已删除！", "success")
            else:
                flash("题目不存在。", "error")
    except Exception as e:
        db.rollback()
        flash(f"删除失败: {str(e)}", "error")
    finally:
        db.close()

    return redirect(url_for("admin_challenges"))


# =========================
# 靶场分类页面
# =========================

@app.route("/lab/vulhub")
@login_required
def lab_vulhub():
    return render_template("lab_vulhub.html")

@app.route("/lab/metasploitable2")
@login_required
def lab_metasploitable2():
    return render_template("lab_metasploitable2.html")

@app.route("/lab/webgoat")
@login_required
def lab_webgoat():
    return render_template("lab_webgoat.html")

@app.route("/lab/juiceshop")
@login_required
def lab_juiceshop():
    return render_template("lab_juiceshop.html")

@app.route("/lab/htb")
@login_required
def lab_htb():
    return render_template("lab_htb.html")

@app.route("/lab/tryhackme")
@login_required
def lab_tryhackme():
    return render_template("lab_tryhackme.html")


# =========================
# 系统管理
# =========================

@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    search = request.args.get("search", "").strip()
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            # 统计
            cur.execute("SELECT COUNT(*) as total FROM users")
            total = cur.fetchone()['total']
            cur.execute("SELECT COUNT(*) as active FROM users WHERE is_active=1")
            active = cur.fetchone()['active']
            cur.execute("SELECT COUNT(*) as disabled FROM users WHERE is_active=0")
            disabled = cur.fetchone()['disabled']
            cur.execute("SELECT COUNT(*) as today FROM users WHERE DATE(created_at) = CURDATE()")
            today = cur.fetchone()['today']
            stats = {'total': total, 'active': active, 'disabled': disabled, 'today': today}

            # 用户列表
            if search:
                cur.execute(
                    "SELECT id, username, display_name, role_key, is_active, last_login_at, last_login_ip, created_at "
                    "FROM users WHERE username LIKE %s OR display_name LIKE %s ORDER BY id",
                    (f"%{search}%", f"%{search}%")
                )
            else:
                cur.execute(
                    "SELECT id, username, display_name, role_key, is_active, last_login_at, last_login_ip, created_at "
                    "FROM users ORDER BY id"
                )
            users = cur.fetchall()
    finally:
        db.close()
    return render_template("admin_users.html", users=users, stats=stats, search=search)


@app.route("/admin/users/add", methods=["POST"])
@login_required
@admin_required
def admin_user_add():
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip() or username
    password = request.form.get("password", "")
    role_key = request.form.get("role_key", "user").strip()

    if not username or not password:
        flash("用户名和密码不能为空。", "error")
        return redirect(url_for("admin_users"))
    if len(username) < 3 or len(username) > 64:
        flash("用户名长度必须在 3~64 位之间。", "error")
        return redirect(url_for("admin_users"))
    if len(password) < 8:
        flash("密码长度不能小于 8 位。", "error")
        return redirect(url_for("admin_users"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (username,))
            if cur.fetchone():
                flash(f"用户名 {username} 已存在。", "error")
                return redirect(url_for("admin_users"))
            pwd_hash = make_password_hash(password)
            cur.execute(
                "INSERT INTO users (username, display_name, password_hash, role_key) "
                "VALUES (%s, %s, %s, %s)",
                (username, display_name, pwd_hash, role_key)
            )
        db.commit()
        flash(f"用户「{display_name}」创建成功！", "success")
        record_operation_log(session.get("user"), f"创建用户: {username}", "POST", "/admin/users/add", result=1)
    except Exception as e:
        db.rollback()
        flash(f"创建失败: {str(e)}", "error")
        record_operation_log(session.get("user"), f"创建用户失败: {username}", "POST", "/admin/users/add", result=0)
    finally:
        db.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/edit", methods=["POST"])
@login_required
@admin_required
def admin_user_edit():
    user_id = request.form.get("user_id", "").strip()
    display_name = request.form.get("display_name", "").strip()
    role_key = request.form.get("role_key", "").strip()

    if not user_id or not display_name:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_users"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            updates = ["display_name=%s"]
            params = [display_name]
            if role_key:
                updates.append("role_key=%s")
                params.append(role_key)
            params.append(user_id)
            cur.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id=%s",
                params
            )
        db.commit()
        flash("用户信息更新成功！", "success")
        record_operation_log(session.get("user"), f"编辑用户: {user_id}", "POST", "/admin/users/edit", result=1)
    except Exception as e:
        db.rollback()
        flash(f"更新失败: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/toggle", methods=["POST"])
@login_required
@admin_required
def admin_user_toggle():
    user_id = request.form.get("user_id", "").strip()
    is_active = int(request.form.get("is_active", 1))

    if not user_id:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_users"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE id=%s", (user_id,))
            user = cur.fetchone()
            if user and user['username'] == 'admin':
                flash("不能禁用管理员账号！", "error")
                return redirect(url_for("admin_users"))
            cur.execute("UPDATE users SET is_active=%s WHERE id=%s", (is_active, user_id))
        db.commit()
        flash("用户状态已更新！", "success")
        record_operation_log(session.get("user"), f"切换用户状态: {user_id}", "POST", "/admin/users/toggle", result=1)
    except Exception as e:
        db.rollback()
        flash(f"操作失败: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/reset_password", methods=["POST"])
@login_required
@admin_required
def admin_user_reset_password():
    user_id = request.form.get("user_id", "").strip()
    default_password = os.getenv("DEFAULT_RESET_PASSWORD", "Reset@2026!")

    if not user_id:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_users"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            pwd_hash = make_password_hash(default_password)
            cur.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (pwd_hash, user_id)
            )
        db.commit()
        flash(f"密码已重置，请通知用户尽快修改。", "success")
        record_operation_log(session.get("user"), f"重置用户密码: {user_id}", "POST", "/admin/users/reset_password", result=1)
    except Exception as e:
        db.rollback()
        flash(f"重置失败: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/delete", methods=["POST"])
@login_required
@admin_required
def admin_user_delete():
    user_id = request.form.get("user_id", "").strip()

    if not user_id:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_users"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE id=%s", (user_id,))
            user = cur.fetchone()
            if user and user['username'] == 'admin':
                flash("不能删除管理员账号！", "error")
                return redirect(url_for("admin_users"))
            if user:
                deleted_username = user['username']
                cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
                db.commit()
                flash(f"用户「{deleted_username}」已删除！", "success")
                record_operation_log(session.get("user"), f"删除用户: {deleted_username}", "POST", "/admin/users/delete", result=1)
            else:
                flash("用户不存在。", "error")
    except Exception as e:
        db.rollback()
        flash(f"删除失败: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/roles")
@login_required
@admin_required
def admin_roles():
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT role_key, COUNT(*) as cnt FROM users GROUP BY role_key")
            role_stats = {row['role_key']: row['cnt'] for row in cur.fetchall()}
    finally:
        db.close()
    return render_template("admin_roles.html",
                           admin_count=role_stats.get('admin', 0),
                           user_count=role_stats.get('user', 0),
                           readonly_count=role_stats.get('readonly', 0))


@app.route("/admin/logs")
@login_required
@admin_required
def admin_logs():
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            # 登录安全统计
            cur.execute("SELECT COUNT(*) as cnt FROM login_attempts WHERE failed_count > 0")
            failed = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) as cnt FROM login_attempts WHERE failed_count = 0")
            success = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) as cnt FROM login_attempts WHERE lock_until IS NOT NULL AND lock_until > NOW()")
            locked = cur.fetchone()['cnt']
            login_stats = {'failed': failed, 'success': success, 'locked': locked}

            # 登录失败记录
            cur.execute("SELECT * FROM login_attempts ORDER BY updated_at DESC LIMIT 50")
            login_attempts = cur.fetchall()

            # 登录历史记录
            try:
                cur.execute("SELECT * FROM login_history ORDER BY created_at DESC LIMIT 50")
                login_history = cur.fetchall()
            except Exception:
                login_history = []

            # 操作日志
            try:
                cur.execute("SELECT COUNT(*) as total FROM operation_log")
                op_total = cur.fetchone()['total']
                cur.execute("SELECT * FROM operation_log ORDER BY created_at DESC LIMIT 100")
                operation_logs = cur.fetchall()
            except Exception:
                op_total = 0
                operation_logs = []

            # 扫描任务日志
            cur.execute("SELECT COUNT(*) as total FROM scan_tasks")
            scan_total = cur.fetchone()['total']
            cur.execute("SELECT * FROM scan_tasks ORDER BY created_at DESC LIMIT 50")
            scan_tasks = cur.fetchall()

            # 通关记录
            cur.execute("SELECT * FROM vulnerability_progress ORDER BY updated_at DESC LIMIT 50")
            progress_records = cur.fetchall()
    finally:
        db.close()

    from datetime import datetime as _dt
    now = _dt.now()

    return render_template("admin_logs.html",
                           login_stats=login_stats,
                           scan_stats={'total': scan_total},
                           login_attempts=login_attempts,
                           login_history=login_history,
                           operation_logs=operation_logs,
                           op_total=op_total,
                           scan_tasks=scan_tasks,
                           progress_records=progress_records,
                           now=now)


@app.route("/admin/logs/clear_ip", methods=["POST"])
@login_required
@admin_required
def admin_log_clear_ip():
    ip_address = request.form.get("ip_address", "").strip()
    if not ip_address:
        flash("参数不完整。", "error")
        return redirect(url_for("admin_logs"))

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM login_attempts WHERE ip_address=%s", (ip_address,))
        db.commit()
        flash(f"IP {ip_address} 的登录失败记录已清除，该 IP 已解锁。", "success")
    except Exception as e:
        db.rollback()
        flash(f"操作失败: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("admin_logs"))


# =========================
# 报告管理
# =========================

def _assess_risk_level(task_type, open_count):
    """根据扫描类型和发现数量评估风险等级"""
    if open_count == 0:
        return 'low'
    if task_type == 'port_scan':
        if open_count >= 10:
            return 'critical'
        elif open_count >= 5:
            return 'high'
        elif open_count >= 2:
            return 'medium'
        return 'low'
    elif task_type == 'waf_detect':
        return 'high' if open_count > 0 else 'low'
    elif task_type == 'webdir_scan':
        if open_count >= 8:
            return 'critical'
        elif open_count >= 4:
            return 'high'
        return 'medium' if open_count > 0 else 'low'
    elif task_type == 'fingerprint':
        return 'medium' if open_count > 0 else 'low'
    elif task_type == 'subdomain_enum':
        return 'medium' if open_count > 0 else 'low'
    elif task_type == 'network_scan':
        if open_count >= 20:
            return 'high'
        return 'medium' if open_count > 0 else 'low'
    return 'low' if open_count == 0 else 'medium'


def _generate_report_summary(task):
    """根据扫描任务生成报告摘要"""
    task_type = task.get('task_type', '')
    target = task.get('target', '')
    params = task.get('params', {})
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (json.JSONDecodeError, TypeError):
            params = {}

    if task_type == 'port_scan':
        ports = params.get('ports', '1-1024')
        return f"对目标 {target} 进行了端口范围 {ports} 的扫描。"
    elif task_type == 'network_scan':
        return f"对目标网段 {target} 进行了主机存活探测。"
    elif task_type == 'waf_detect':
        return f"对目标 {target} 进行了 WAF 防护检测。"
    elif task_type == 'fingerprint':
        return f"对目标 {target} 进行了服务指纹识别。"
    elif task_type == 'webdir_scan':
        return f"对目标 {target} 进行了 Web 目录扫描。"
    elif task_type == 'subdomain_enum':
        return f"对目标域名 {target} 进行了子域名枚举。"
    return f"对目标 {target} 执行了 {task_type} 扫描。"


def _generate_report_detail(task, results):
    """根据扫描任务和结果生成 HTML 格式的详细内容"""
    task_type = task.get('task_type', '')

    if task_type == 'port_scan' and results:
        rows = ""
        for r in results:
            rows += f"""<tr>
                <td>{r.get('port', '')}</td>
                <td>{r.get('protocol', 'tcp').upper()}</td>
                <td><span class="badge bg-success">开放</span></td>
                <td>{r.get('banner', '—')}</td>
            </tr>"""
        return f"""<table class="table table-bordered table-hover">
            <thead class="table-light"><tr>
                <th>端口</th><th>协议</th><th>状态</th><th>Banner</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    elif task_type == 'network_scan' and results:
        rows = ""
        for r in results:
            if isinstance(r, dict):
                rows += f"<tr><td>{r.get('host', r.get('ip', str(r)))}</td><td><span class='badge bg-success'>在线</span></td></tr>"
            else:
                rows += f"<tr><td>{r}</td><td><span class='badge bg-success'>在线</span></td></tr>"
        return f"""<table class="table table-bordered table-hover">
            <thead class="table-light"><tr><th>主机地址</th><th>状态</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    elif task_type == 'waf_detect' and results:
        rows = ""
        for r in results:
            if isinstance(r, dict):
                rows += f"<tr><td>{r.get('name', str(r))}</td><td>{r.get('method', '响应特征分析')}</td></tr>"
            else:
                rows += f"<tr><td>{r}</td><td>响应特征分析</td></tr>"
        return f"""<table class="table table-bordered table-hover">
            <thead class="table-light"><tr><th>WAF名称</th><th>检测方式</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    elif task_type == 'fingerprint' and results:
        rows = ""
        for r in results:
            if isinstance(r, dict):
                rows += f"<tr><td>{r.get('port', '')}</td><td>{r.get('status', '')}</td><td>{r.get('service', '')}</td><td>{r.get('banner', '')}</td></tr>"
            else:
                rows += f"<tr><td colspan='4'>{r}</td></tr>"
        return f"""<table class="table table-bordered table-hover">
            <thead class="table-light"><tr><th>端口</th><th>状态</th><th>服务</th><th>Banner</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    elif task_type == 'webdir_scan' and results:
        rows = ""
        for r in results:
            if isinstance(r, dict):
                code_class = 'bg-success' if r.get('code', 0) == 200 else 'bg-warning text-dark'
                rows += f"<tr><td>{r.get('path', '')}</td><td><span class='badge {code_class}'>{r.get('code', '')}</span></td><td>{r.get('size', '—')}</td></tr>"
            else:
                rows += f"<tr><td colspan='3'>{r}</td></tr>"
        return f"""<table class="table table-bordered table-hover">
            <thead class="table-light"><tr><th>路径</th><th>状态码</th><th>大小</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    elif task_type == 'subdomain_enum' and results:
        rows = ""
        for r in results:
            if isinstance(r, dict):
                rows += f"<tr><td>{r.get('domain', r.get('subdomain', str(r)))}</td><td><span class='badge bg-success'>有效</span></td></tr>"
            else:
                rows += f"<tr><td>{r}</td><td><span class='badge bg-success'>有效</span></td></tr>"
        return f"""<table class="table table-bordered table-hover">
            <thead class="table-light"><tr><th>子域名</th><th>状态</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    return "<p class='text-muted'>无详细扫描数据。</p>"


@app.route("/report/manage")
@login_required
def report_manage():
    """报告管理页面 - 查看所有扫描报告"""
    filter_type = request.args.get("task_type", "").strip()
    filter_risk = request.args.get("risk_level", "").strip()
    filter_keyword = request.args.get("keyword", "").strip()

    db = get_db_connection()
    try:
        with db.cursor() as cur:
            # 统计
            cur.execute("SELECT COUNT(*) as total FROM scan_reports WHERE user_id=%s", (session.get("user_id"),))
            total = cur.fetchone()['total']
            cur.execute("SELECT COUNT(*) as cnt FROM scan_reports WHERE user_id=%s AND risk_level='critical'", (session.get("user_id"),))
            critical = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) as cnt FROM scan_reports WHERE user_id=%s AND risk_level='high'", (session.get("user_id"),))
            high = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) as cnt FROM scan_reports WHERE user_id=%s AND risk_level='low'", (session.get("user_id"),))
            low = cur.fetchone()['cnt']
            stats = {'total': total, 'critical': critical, 'high': high, 'low': low}

            # 构建查询
            where = "WHERE user_id=%s"
            params = [session.get("user_id")]

            if filter_type:
                where += " AND task_type=%s"
                params.append(filter_type)
            if filter_risk:
                where += " AND risk_level=%s"
                params.append(filter_risk)
            if filter_keyword:
                where += " AND (title LIKE %s OR target LIKE %s)"
                params.extend([f"%{filter_keyword}%", f"%{filter_keyword}%"])

            cur.execute(f"SELECT * FROM scan_reports {where} ORDER BY created_at DESC", params)
            reports = cur.fetchall()
    finally:
        db.close()

    return render_template("report_manage.html",
                           reports=reports, stats=stats,
                           filter_type=filter_type,
                           filter_risk=filter_risk,
                           filter_keyword=filter_keyword)


@app.route("/report/detail/<int:report_id>")
@login_required
def report_detail(report_id):
    """查看报告详情"""
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM scan_reports WHERE id=%s AND user_id=%s LIMIT 1",
                        (report_id, session.get("user_id")))
            report = cur.fetchone()
            if not report:
                flash("报告不存在或无权限查看。", "error")
                return redirect(url_for("report_manage"))
    finally:
        db.close()

    return render_template("report_detail.html", report=report)


@app.route("/report/download/<int:report_id>")
@login_required
def report_download(report_id):
    """导出报告为文本文件"""
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM scan_reports WHERE id=%s AND user_id=%s LIMIT 1",
                        (report_id, session.get("user_id")))
            report = cur.fetchone()
            if not report:
                flash("报告不存在或无权限查看。", "error")
                return redirect(url_for("report_manage"))
    finally:
        db.close()

    # 生成纯文本报告
    risk_map = {'critical': '严重', 'high': '高危', 'medium': '中危', 'low': '低危'}
    type_map = {
        'port_scan': '端口扫描', 'network_scan': '网络探测', 'waf_detect': 'WAF检测',
        'fingerprint': '指纹识别', 'webdir_scan': '目录扫描', 'subdomain_enum': '子域名枚举'
    }

    lines = [
        "=" * 60,
        "  安全扫描报告",
        "=" * 60,
        "",
        f"报告ID:     {report['id']}",
        f"报告标题:   {report['title']}",
        f"扫描类型:   {type_map.get(report['task_type'], report['task_type'])}",
        f"扫描目标:   {report['target']}",
        f"风险等级:   {risk_map.get(report['risk_level'], report['risk_level'])}",
        f"发现数量:   {report['open_count']}",
        f"生成时间:   {report['created_at']}",
        f"生成用户:   {report['username']}",
        "",
        "-" * 60,
        "  报告摘要",
        "-" * 60,
        "",
        report.get('summary') or '无',
        "",
        "-" * 60,
        "  详细结果",
        "-" * 60,
        "",
    ]

    # 将 HTML 详细内容简单提取文本
    detail = report.get('detail') or ''
    if detail:
        import re
        text = re.sub(r'<[^>]+>', ' ', detail)
        text = re.sub(r'\s+', ' ', text).strip()
        lines.append(text)
    else:
        lines.append("无详细数据。")

    lines.extend([
        "",
        "-" * 60,
        "  安全建议",
        "-" * 60,
        "",
    ])

    if report['risk_level'] in ('critical', 'high'):
        lines.extend([
            "- 发现高风险漏洞，建议立即修复并加强安全防护。",
            "- 对暴露的服务端口进行访问控制，限制不必要的访问。",
            "- 定期进行安全扫描和漏洞评估。",
        ])
    elif report['risk_level'] == 'medium':
        lines.extend([
            "- 发现中危风险，建议在近期安排修复。",
            "- 关注服务版本更新，及时修补已知漏洞。",
        ])
    else:
        lines.extend([
            "- 当前扫描未发现明显安全风险。",
            "- 建议保持定期安全扫描的习惯。",
        ])
    lines.append("- 本报告仅用于授权范围内的安全测试参考。")

    lines.extend(["", "=" * 60, "  报告结束", "=" * 60])

    content = "\n".join(lines)
    filename = f"report_{report['id']}_{report['task_type']}.txt"

    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/report/delete/<int:report_id>", methods=["POST"])
@login_required
def report_delete(report_id):
    """删除报告"""
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT id, title FROM scan_reports WHERE id=%s AND user_id=%s LIMIT 1",
                        (report_id, session.get("user_id")))
            report = cur.fetchone()
            if not report:
                flash("报告不存在或无权限删除。", "error")
                return redirect(url_for("report_manage"))
            cur.execute("DELETE FROM scan_reports WHERE id=%s", (report_id,))
        db.commit()
        flash(f"报告「{report['title']}」已删除。", "success")
    except Exception as e:
        db.rollback()
        flash(f"删除失败: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("report_manage"))


@app.route("/report/generate/<int:task_id>", methods=["POST"])
@login_required
def report_generate(task_id):
    """从扫描历史任务生成报告"""
    db = get_db_connection()
    try:
        with db.cursor() as cur:
            # 获取扫描任务
            cur.execute("SELECT * FROM scan_tasks WHERE id=%s AND username=%s LIMIT 1",
                        (task_id, session.get("user")))
            task = cur.fetchone()
            if not task:
                flash("扫描任务不存在或无权限操作。", "error")
                return redirect(url_for("scan_history"))

            task_type = task.get('task_type', '')

            # 检查是否已生成过报告
            cur.execute(
                "SELECT id FROM scan_reports WHERE user_id=%s AND task_type=%s AND target=%s AND created_at >= %s LIMIT 1",
                (session.get("user_id"), task_type, task.get('target', ''), task.get('created_at', ''))
            )
            if cur.fetchone():
                flash("该任务已生成过报告，请勿重复生成。", "warning")
                return redirect(url_for("report_manage"))

            # 获取扫描结果
            results = []
            if task_type == 'port_scan':
                cur.execute("SELECT * FROM port_scan_results WHERE task_id=%s ORDER BY port ASC", (task_id,))
                results = cur.fetchall()

            open_count = len(results)

            # 生成报告内容
            title = f"{'端口扫描' if task_type == 'port_scan' else task_type}报告 - {task.get('target', '')}"
            summary = _generate_report_summary(task)
            detail = _generate_report_detail(task, results)
            risk_level = _assess_risk_level(task_type, open_count)

            # 保存报告
            cur.execute(
                "INSERT INTO scan_reports (user_id, username, title, task_type, target, summary, detail, risk_level, open_count) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (session.get("user_id"), session.get("user"), title, task_type,
                 task.get('target', ''), summary, detail, risk_level, open_count)
            )
        db.commit()
        flash("报告生成成功！", "success")
    except Exception as e:
        db.rollback()
        flash(f"报告生成失败: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("report_manage"))


# =========================
# 退出登录
# =========================

@app.route("/logout", methods=["GET", "POST"])
def logout():
    username = session.get("user", "")
    if username:
        record_login_history(username, 0, get_client_ip())
        record_operation_log(username, "用户登出", "POST", "/logout", result=1)
    session.clear()
    flash("已经安全退出系统。", "success")
    return redirect(url_for("login"))


# =========================
# 功能模块说明页
# =========================

@app.route("/modules")
@login_required
def modules_page():
    """功能模块说明页面"""
    return render_template("modules.html")


# =========================
# AI 网络安全攻防模块
# =========================

# AI 攻防系统提示词
AI_ATTACK_DEFENSE_PROMPT = """你是一个专业的 AI 网络安全攻防助手，运行在网络安全培训平台上。
你的任务是帮助用户在授权的靶场环境中进行自动化渗透测试和安全攻防演练。

## 核心能力
1. **自动化扫描**: 对目标主机/网段执行端口扫描、服务发现、漏洞检测
2. **漏洞利用**: 根据扫描结果自动生成和注入 payload，完成漏洞利用
3. **密码破解**: 使用字典/暴力破解尝试弱口令登录
4. **Web漏洞检测**: SQL注入、XSS、CSRF、命令注入、文件包含等
5. **安全建议**: 根据发现的问题给出修复方案

## 可用操作命令
当你需要执行实际操作时，使用以下格式输出：
- 端口扫描: [SCAN:port]目标IP:端口范围[/SCAN]
- 网络扫描: [SCAN:network]网段[/SCAN]
- 目录扫描: [SCAN:dir]目标URL[/SCAN]
- 子域名枚举: [SCAN:subdomain]域名[/SCAN]
- WAF检测: [SCAN:waf]目标URL[/SCAN]
- 指纹识别: [SCAN:fingerprint]目标:端口[/SCAN]
- 执行命令: [CMD:run_command]命令[/CMD]
- SQL注入测试: [ATTACK:sqli]目标URL[/ATTACK]
- XSS测试: [ATTACK:xss]目标URL[/ATTACK]
- 命令注入: [ATTACK:cmdi]目标:参数[/ATTACK]

## 规则
1. 一次只输出一个操作指令
2. 攻击仅限授权靶场环境
3. 结果出来后分析并给出下一步建议
4. 用中文简洁回复

当前时间: {current_time}
用户角色: 安全研究员"""

# AI 攻防会话历史
attack_sessions: dict = {}  # session_id -> [messages]

@app.route("/ai-attack")
@login_required
def ai_attack_page():
    """AI 网络安全攻防页面"""
    return render_template("ai_attack.html")


@app.route("/api/ai-attack/chat", methods=["POST"])
@login_required
def api_ai_attack_chat():
    """AI 攻防对话接口"""
    data = request.get_json()
    user_message = data.get("message", "").strip()
    session_id = data.get("session_id", f"attack_{session.get('user_id')}")
    target = data.get("target", "").strip()

    if not user_message:
        return jsonify({"success": False, "error": "缺少消息内容"})

    # 初始化会话
    if session_id not in attack_sessions:
        attack_sessions[session_id] = []

    history = attack_sessions[session_id]
    if len(history) > 30:
        history = history[-30:]

    messages = [
        {"role": "system", "content": AI_ATTACK_DEFENSE_PROMPT.format(
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )}
    ] + history + [{"role": "user", "content": user_message}]

    try:
        # 调用 AI 模型
        from model_router import ModelRouter
        router = ModelRouter(mode="cloud_first")
        result = router.chat(messages=messages, temperature=0.7, max_tokens=4096)

        reply = result.get("content", "")
        model_used = result.get("model", "unknown")

        # 保存历史
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": reply})
        attack_sessions[session_id] = history

        # 解析操作指令
        operations = _parse_attack_commands(reply)

        return jsonify({
            "success": True,
            "reply": _clean_attack_tags(reply),
            "model": model_used,
            "operations": operations,
        })

    except Exception as e:
        # 回退：无 AI 时的本地分析
        fallback_reply = _fallback_attack_analysis(user_message, target)
        return jsonify({
            "success": True,
            "reply": fallback_reply,
            "model": "local_fallback",
            "operations": [],
            "fallback": True,
        })


@app.route("/api/ai-attack/execute", methods=["POST"])
@login_required
def api_ai_attack_execute():
    """执行 AI 推荐的攻防操作"""
    data = request.get_json()
    op_type = data.get("type", "")
    op_params = data.get("params", "")

    if not op_type:
        return jsonify({"success": False, "error": "缺少操作类型"})

    try:
        result = _execute_attack_operation(op_type, op_params)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


def _parse_attack_commands(reply: str) -> list:
    """从 AI 回复中解析攻防操作指令"""
    import re
    ops = []

    # 扫描指令
    for match in re.finditer(r"\[SCAN:(\w+)\](.*?)\[/SCAN\]", reply):
        ops.append({"type": f"scan_{match.group(1)}", "params": match.group(2).strip()})

    # 攻击指令
    for match in re.finditer(r"\[ATTACK:(\w+)\](.*?)\[/ATTACK\]", reply):
        ops.append({"type": f"attack_{match.group(1)}", "params": match.group(2).strip()})

    # 命令执行
    for match in re.finditer(r"\[CMD:(\w+)\](.*?)\[/CMD\]", reply):
        ops.append({"type": f"cmd_{match.group(1)}", "params": match.group(2).strip()})

    return ops


def _clean_attack_tags(reply: str) -> str:
    """清除攻防标签，返回干净文本"""
    import re
    reply = re.sub(r"\[SCAN:\w+\].*?\[/SCAN\]", "", reply, flags=re.DOTALL)
    reply = re.sub(r"\[ATTACK:\w+\].*?\[/ATTACK\]", "", reply, flags=re.DOTALL)
    reply = re.sub(r"\[CMD:\w+\].*?\[/CMD\]", "", reply, flags=re.DOTALL)
    return reply.strip()


def _execute_attack_operation(op_type: str, params: str) -> str:
    """执行攻防操作"""
    if op_type == "scan_port":
        target_parts = params.split(":")
        target = target_parts[0].strip()
        ports = target_parts[1].strip() if len(target_parts) > 1 else "1-1024"
        try:
            assistant = NetSecAssistant(timeout=2, workers=50)
            open_ports = assistant.run_port_scan(target, ports) or []
            return f"端口扫描完成，发现 {len(open_ports)} 个开放端口: {', '.join(map(str, open_ports))}"
        except Exception as e:
            return f"端口扫描失败: {e}"

    elif op_type == "scan_dir":
        url = params.strip()
        if not url.startswith("http"):
            url = "http://" + url
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            DEFAULT_DICT = ["admin", "login", "index.php", "backup", "db", "config", ".git", "robots.txt",
                           "wp-admin", "shell.php", "upload", "api", "test", "dev", "console", "phpinfo.php"]
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_map = {executor.submit(network_scan.scan_dir, url, path, 3): path for path in DEFAULT_DICT}
                for future in as_completed(future_map):
                    r = future.result()
                    if r:
                        path, code, size = r
                        results.append(f"  [{code}] {path} ({size}字节)")
            if results:
                return "目录扫描结果:\n" + "\n".join(results)
            return "未发现常见目录"
        except Exception as e:
            return f"目录扫描失败: {e}"

    elif op_type == "scan_waf":
        url = params.strip()
        if not url.startswith("http"):
            url = "http://" + url
        try:
            assistant = NetSecAssistant(timeout=5)
            assistant.results_log = []
            assistant.detect_waf(url)
            logs = assistant.results_log
            if logs:
                return "WAF检测结果:\n" + "\n".join(logs)
            return "未检测到WAF"
        except Exception as e:
            return f"WAF检测失败: {e}"

    elif op_type == "scan_subdomain":
        domain = params.strip().replace("http://", "").replace("https://", "").split("/")[0]
        try:
            assistant = NetSecAssistant(timeout=2, workers=50)
            subs = assistant.run_subdomain_enum(domain) or []
            if subs:
                return f"子域名枚举完成，发现 {len(subs)} 个子域名:\n" + "\n".join(subs[:20])
            return "未发现子域名"
        except Exception as e:
            return f"子域名枚举失败: {e}"

    elif op_type == "scan_fingerprint":
        parts = params.strip().split(":")
        target = parts[0].strip()
        ports_str = parts[1].strip() if len(parts) > 1 else "22,80,443,3306,8080"
        try:
            assistant = NetSecAssistant(timeout=2)
            ports = assistant.parse_ports(ports_str)
            try:
                target_ip = socket.gethostbyname(target)
            except socket.gaierror:
                return f"无法解析主机: {target}"
            results = []
            for port in ports:
                if assistant.scan_port(target_ip, port):
                    banner = assistant.get_banner(target_ip, port)
                    results.append(f"  端口 {port}: {banner[:80] if banner else '开放(无banner)'}")
            if results:
                return f"指纹识别结果 ({target}):\n" + "\n".join(results)
            return f"目标 {target} 所有端口均关闭"
        except Exception as e:
            return f"指纹识别失败: {e}"

    elif op_type == "cmd_run_command":
        cmd = params.strip()
        try:
            import subprocess
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            output = result.stdout.strip() or result.stderr.strip()
            return output[:2000] if output else "命令执行完毕（无输出）"
        except subprocess.TimeoutExpired:
            return "命令执行超时（15秒）"
        except Exception as e:
            return f"命令执行失败: {e}"

    elif op_type == "attack_sqli":
        url = params.strip()
        return f"SQL注入测试建议:\n1. 尝试在参数后添加单引号测试报错: {url}'\n2. 尝试经典注入: {url} OR 1=1--\n3. 使用 UNION SELECT 测试列数\n4. 尝试盲注: AND SLEEP(5)--\n请在DVWA SQL注入练习页面中实践"

    elif op_type == "attack_xss":
        url = params.strip()
        return f"XSS测试建议:\n1. 反射型: 在搜索框输入 <script>alert(1)</script>\n2. 存储型: 在留言板发布包含脚本的内容\n3. DOM型: 检查URL hash参数\n请在DVWA XSS练习页面中实践"

    elif op_type == "attack_cmdi":
        parts = params.strip().split(":")
        target = parts[0] if parts else params
        return f"命令注入测试建议:\n1. 尝试在ping目标后追加: {target} && whoami\n2. 尝试管道符: {target} | dir\n3. 尝试分号: {target}; ls\n请在DVWA命令注入练习页面中实践"

    return f"未知操作类型: {op_type}"


def _fallback_attack_analysis(message: str, target: str = "") -> str:
    """本地回退分析（无需 AI API）"""
    msg_lower = message.lower()

    if any(kw in msg_lower for kw in ["扫描", "scan", "端口", "port"]):
        target = target or "127.0.0.1"
        return f"我将对目标 {target} 执行端口扫描。常见端口范围 1-1024。\n\n你可以前往「扫描工具 → 端口扫描」手动执行，或告诉我具体的目标和端口范围。"

    if any(kw in msg_lower for kw in ["sql", "注入", "sqli"]):
        return "SQL注入攻击步骤:\n1. 在DVWA SQL注入页面输入 1' 测试报错\n2. 使用 1 OR 1=1-- 绕过认证\n3. 使用 UNION SELECT 获取数据库信息\n4. 使用 information_schema 枚举表名和列名\n\n前往 DVWA 漏洞练习 → SQL注入 开始练习"

    if any(kw in msg_lower for kw in ["xss", "跨站"]):
        return "XSS攻击步骤:\n1. 反射型: 在URL参数中注入 <script>alert(1)</script>\n2. 存储型: 留言板发布包含脚本的内容\n3. DOM型: 利用前端JS代码漏洞\n\n前往 DVWA 漏洞练习 → XSS 开始练习"

    if any(kw in msg_lower for kw in ["命令", "注入", "command", "cmd"]):
        return "命令注入攻击:\n1. 在ping功能中注入 && 或 | 分隔符\n2. 尝试: 127.0.0.1 && whoami\n3. 尝试: 127.0.0.1; dir\n\n前往 DVWA 漏洞练习 → 命令注入 开始练习"

    if any(kw in msg_lower for kw in ["文件", "包含", "include", "file"]):
        return "文件包含漏洞:\n1. 本地文件包含(LFI): 使用 ../ 遍历目录\n2. 尝试读取 /etc/passwd 或 C:\\Windows\\win.ini\n3. 远程文件包含(RFI): 包含远程恶意脚本\n\n前往 DVWA 漏洞练习 → 文件包含 开始练习"

    if any(kw in msg_lower for kw in ["爆破", "暴力", "密码", "brute"]):
        return "暴力破解攻击:\n1. 使用常见弱密码字典: admin/123456/password\n2. 对登录表单进行自动化尝试\n3. 注意验证码绕过和速率限制\n\n前往 DVWA 漏洞练习 → 暴力破解 开始练习"

    if any(kw in msg_lower for kw in ["csrf", "跨站请求"]):
        return "CSRF攻击:\n1. 构造恶意HTML页面\n2. 诱导受害者点击链接\n3. 利用已登录的会话执行未授权操作\n\n前往 DVWA 漏洞练习 → CSRF 开始练习"

    return f"我是AI网络安全攻防助手。你可以:\n• 告诉我你想练习的漏洞类型（SQL注入/XSS/命令注入/文件包含/CSRF等）\n• 描述一个攻击场景，我会给出步骤建议\n• 让我对目标执行自动化扫描（需要指定目标IP/域名）\n\n当前可用靶场: DVWA漏洞练习(14个漏洞)、端口扫描、WAF检测、指纹识别等"


@app.route("/api/ai-attack/agent-status")
@login_required
def api_agent_status():
    """检测云端大脑 Agent 连接状态"""
    import urllib.request
    import urllib.error
    brain_url = os.environ.get("BRAIN_URL", "http://127.0.0.1:5000")
    agents = []
    brain_online = False
    try:
        req = urllib.request.Request(f"{brain_url}/api/agents", method="GET")
        req.add_header("User-Agent", "NetSec-Platform/1.0")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            agents = data.get("agents", [])
            brain_online = True
    except Exception:
        pass
    return jsonify({
        "agents": agents,
        "count": len(agents),
        "brain_online": brain_online,
        "brain_url": brain_url,
    })


@app.route("/api/health")
def api_health():
    """平台健康检查"""
    return jsonify({
        "status": "ok",
        "time": datetime.now().isoformat(),
        "platform": "NetSec",
        "db_ready": DB_READY,
        "ai_module": True,
    })


# =========================
# 支付/会员系统（已隐藏，待后续启用）
# =========================

# def init_payment_module():
#     """初始化支付模块（注入数据库连接器）"""
#     pm = init_payment(lambda: get_db_connection())
#     payment_manager._db_connector = lambda: get_db_connection()
#     return pm


# @app.route("/pricing")
# def pricing_page():
#     """定价页面（已隐藏）"""
#     return render_template("pricing.html")


# @app.route("/premium")
# @login_required
# def premium_page():
#     """会员中心（已隐藏）"""
#     return redirect(url_for("modules_page"))


# =========================
# 启动项目
# =========================

if __name__ == "__main__":
    host = os.getenv("NETSEC_HOST", "0.0.0.0")
    port = int(os.getenv("NETSEC_PORT", "5100"))
    debug = os.getenv("NETSEC_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
