-- 创建业务数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS `{DB_NAME}`
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

-- 切换到业务数据库
USE `{DB_NAME}`;

-- 用户表：存储登录账户信息
CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 登录失败记录表：按 IP 统计失败次数和锁定时间
CREATE TABLE IF NOT EXISTS login_attempts (
    ip_address VARCHAR(45) PRIMARY KEY,
    failed_count INT NOT NULL DEFAULT 0,
    lock_until DATETIME NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 扫描任务表：记录每一次扫描任务
CREATE TABLE IF NOT EXISTS scan_tasks (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NULL,
    username VARCHAR(64) NOT NULL,
    task_type VARCHAR(32) NOT NULL,
    target VARCHAR(255) NOT NULL,
    params JSON NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'done',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,

    INDEX idx_user_id(user_id),
    INDEX idx_username(username),
    INDEX idx_task_type(task_type),
    INDEX idx_status(status),
    INDEX idx_created_at(created_at),

    CONSTRAINT fk_scan_tasks_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 端口扫描结果表：保存端口扫描发现的开放端口
CREATE TABLE IF NOT EXISTS port_scan_results (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    task_id BIGINT UNSIGNED NOT NULL,
    port INT NOT NULL,
    protocol VARCHAR(10) NOT NULL DEFAULT 'tcp',
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    banner TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_task_id(task_id),
    INDEX idx_port(port),

    CONSTRAINT fk_port_scan_task
        FOREIGN KEY (task_id) REFERENCES scan_tasks(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始化默认管理员账号（仅当 admin 不存在时插入）
INSERT INTO users (username, display_name, password_hash, is_active)
SELECT 'admin', '系统管理员', '{ADMIN_PASSWORD_HASH}', 1
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM users WHERE username = 'admin'
);

-- 漏洞题目表：存储所有漏洞练习题目
CREATE TABLE IF NOT EXISTS vulnerabilities (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    vuln_id VARCHAR(64) NOT NULL UNIQUE COMMENT '漏洞标识符',
    name VARCHAR(128) NOT NULL COMMENT '漏洞名称',
    category VARCHAR(64) NOT NULL COMMENT '漏洞分类',
    difficulty ENUM('low', 'medium', 'high') NOT NULL DEFAULT 'low' COMMENT '难度等级',
    description TEXT NULL COMMENT '漏洞描述',
    description_zh TEXT NULL COMMENT '中文描述',
    hint TEXT NULL COMMENT '解题提示',
    is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_category(category),
    INDEX idx_difficulty(difficulty),
    INDEX idx_is_active(is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='漏洞题目表';

-- 通关记录表（中文表名可能有问题，使用英文表名）
CREATE TABLE IF NOT EXISTS `通关记录` (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    vuln_id VARCHAR(64) NOT NULL COMMENT '漏洞标识符',
    difficulty ENUM('low', 'medium', 'high') NOT NULL,
    status ENUM('not_started', 'in_progress', 'passed') NOT NULL DEFAULT 'not_started',
    attempts INT NOT NULL DEFAULT 0 COMMENT '尝试次数',
    passed_at DATETIME NULL COMMENT '通关时间',
    notes TEXT NULL COMMENT '通关笔记',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id(user_id),
    INDEX idx_vuln_id(vuln_id),
    INDEX idx_status(status),
    CONSTRAINT fk_progress_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通关记录表';

-- 漏洞通关记录表（中文表名可能有问题，使用英文）
CREATE TABLE IF NOT EXISTS vulnerability_progress (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    vuln_id VARCHAR(64) NOT NULL COMMENT '漏洞标识符',
    difficulty ENUM('low', 'medium', 'high') NOT NULL,
    status ENUM('not_started', 'in_progress', 'passed') NOT NULL DEFAULT 'not_started',
    attempts INT NOT NULL DEFAULT 0 COMMENT '尝试次数',
    passed_at DATETIME NULL COMMENT '通关时间',
    notes TEXT NULL COMMENT '通关笔记',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_vuln_diff (user_id, vuln_id, difficulty),
    INDEX idx_user_id(user_id),
    INDEX idx_vuln_id(vuln_id),
    INDEX idx_status(status),
    CONSTRAINT fk_vuln_progress_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='漏洞通关记录表';

-- 题目管理表：存储题目配置和难度设置
CREATE TABLE IF NOT EXISTS challenge_config (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    vuln_id VARCHAR(64) NOT NULL,
    difficulty ENUM('low', 'medium', 'high') NOT NULL,
    config_key VARCHAR(64) NOT NULL,
    config_value TEXT NULL,
    description VARCHAR(255) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_vuln_difficulty_key (vuln_id, difficulty, config_key),
    INDEX idx_vuln_id(vuln_id),
    INDEX idx_difficulty(difficulty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='题目配置表';

-- 扫描报告表：存储用户生成的扫描报告
CREATE TABLE IF NOT EXISTS scan_reports (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    username VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL COMMENT '报告标题',
    task_type VARCHAR(32) NOT NULL COMMENT '扫描类型',
    target VARCHAR(255) NOT NULL COMMENT '扫描目标',
    summary TEXT NULL COMMENT '报告摘要',
    detail TEXT NULL COMMENT '报告详细内容',
    risk_level ENUM('low', 'medium', 'high', 'critical') NOT NULL DEFAULT 'low' COMMENT '风险等级',
    open_count INT NOT NULL DEFAULT 0 COMMENT '发现数量',
    file_path VARCHAR(512) NULL COMMENT '导出文件路径',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id(user_id),
    INDEX idx_task_type(task_type),
    INDEX idx_risk_level(risk_level),
    INDEX idx_created_at(created_at),
    CONSTRAINT fk_report_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='扫描报告表';

-- 插入默认的漏洞题目数据（INSERT IGNORE 避免重复插入导致唯一键冲突）
INSERT IGNORE INTO vulnerabilities (vuln_id, name, category, difficulty, description_zh, hint) VALUES
-- 漏洞组1
('brute_force', '暴力破解', '认证', 'low', '通过暴力枚举尝试登录凭证', '可以使用常见的用户名密码字典进行尝试'),
('sqli_normal', '普通SQL注入', '注入', 'low', '在输入框中注入SQL语句获取数据库信息', '尝试使用单引号或OR 1=1绕过'),
('sqli_blind', 'SQL盲注', '注入', 'low', '无法直接看到数据库响应，通过条件判断推断信息', '通过页面响应差异判断条件真假'),
('weak_session_id', '弱会话ID', '认证', 'low', '会话ID可预测，可被伪造', '观察会话ID的生成规律'),

-- 漏洞组2
('command_injection', '命令注入', '注入', 'low', '在输入中注入系统命令', '使用分号或管道符连接命令'),
('file_include', '文件包含', '文件', 'low', '未过滤的用户输入被作为文件路径包含', '尝试包含系统文件或远程文件'),
('file_upload', '文件上传', '文件', 'low', '未验证上传文件类型和内容', '上传webshell或绕过文件类型检查'),
('weak_captcha', '不安全验证码', '认证', 'low', '验证码可被绕过或识别', '验证码逻辑存在漏洞'),

-- 漏洞组3
('xss_reflected', '反射型XSS', 'XSS', 'low', '恶意脚本通过URL参数反射到页面', '在URL参数中注入<script>标签'),
('xss_stored', '存储型XSS', 'XSS', 'low', '恶意脚本被存储在数据库中', '在留言板等位置注入持久化脚本'),
('xss_dom', 'DOM型XSS', 'XSS', 'low', '通过DOM操作注入恶意代码', '利用JavaScript的DOM操作'),
('csrf', 'CSRF跨站请求伪造', '认证', 'low', '诱导用户点击触发非预期请求', '构造恶意链接或页面'),

-- 漏洞组4
('csp_bypass', 'CSP绕过', '客户端', 'low', '内容安全策略配置不当可被绕过', '寻找CSP配置的薄弱环节'),
('javascript_vuln', 'JavaScript漏洞', '客户端', 'low', '前端JavaScript代码存在安全缺陷', '分析前端JS代码逻辑');
