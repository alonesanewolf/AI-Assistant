"""
网络安全扫描三级体系：低 / 中 / 高
=================================
低 (LOW)    : 基础端口扫描（常见端口）+ 基本信息收集
中 (MEDIUM) : 端口扫描(1-1024) + WAF检测 + 指纹识别 + 子域名枚举
高 (HIGH)   : 全端口扫描(1-65535) + WAF + 指纹 + 子域名 + Web目录扫描 + AI漏洞评估
"""

import socket
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, Callable

from NetSecAssistant import NetSecAssistant
import network_scan
from vuln_exploit_db import ExploitDB


# =========================
# 扫描等级定义
# =========================

SCAN_LEVELS = {
    "low": {
        "name": "低等级扫描",
        "description": "基础端口扫描 + 基本信息收集",
        "icon": "🟢",
        "ports": "22,80,443,3306,3389,8080,8443",
        "timeout": 1.0,
        "workers": 50,
        "enable_port_scan": True,
        "enable_waf": False,
        "enable_fingerprint": False,
        "enable_subdomain": False,
        "enable_web_dir": False,
        "enable_vuln_assessment": False,
        "estimated_time": "5-15 秒",
    },
    "medium": {
        "name": "中等级扫描",
        "description": "端口扫描(1-1024) + WAF检测 + 指纹识别 + 子域名枚举",
        "icon": "🟡",
        "ports": "1-1024",
        "timeout": 1.5,
        "workers": 100,
        "enable_port_scan": True,
        "enable_waf": True,
        "enable_fingerprint": True,
        "enable_subdomain": True,
        "enable_web_dir": False,
        "enable_vuln_assessment": False,
        "estimated_time": "30-60 秒",
    },
    "high": {
        "name": "高等级扫描",
        "description": "全端口扫描 + WAF + 指纹 + 子域名 + Web目录扫描 + 漏洞评估",
        "icon": "🔴",
        "ports": "1-65535",
        "timeout": 1.0,
        "workers": 200,
        "enable_port_scan": True,
        "enable_waf": True,
        "enable_fingerprint": True,
        "enable_subdomain": True,
        "enable_web_dir": True,
        "enable_vuln_assessment": True,
        "estimated_time": "3-8 分钟",
    },
}

# 常见端口与服务映射
COMMON_PORTS_SERVICE = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
    445: "SMB", 993: "IMAPS", 995: "POP3S", 1433: "MSSQL",
    1521: "Oracle", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    5900: "VNC", 6379: "Redis", 8080: "HTTP-Proxy", 8443: "HTTPS-Alt",
    9090: "Web-Console", 27017: "MongoDB",
}

# 端口风险评估
PORT_RISK_MAP = {
    21: ("中", "FTP明文传输，可能被嗅探"),
    22: ("低", "SSH安全传输，需注意弱密码"),
    23: ("高", "Telnet明文传输，强烈建议禁用"),
    25: ("中", "SMTP可能被用于垃圾邮件"),
    53: ("中", "DNS可能遭受放大攻击"),
    110: ("高", "POP3明文传输"),
    143: ("高", "IMAP明文传输"),
    445: ("高", "SMB曾受永恒之蓝攻击"),
    1433: ("中", "MSSQL需限制访问来源"),
    1521: ("中", "Oracle需限制访问来源"),
    3306: ("中", "MySQL需限制访问来源"),
    3389: ("高", "RDP暴露外网风险极高"),
    5432: ("中", "PostgreSQL需限制访问来源"),
    5900: ("高", "VNC未加密远程控制"),
    6379: ("高", "Redis未授权访问风险"),
    27017: ("高", "MongoDB未授权访问风险"),
}


# =========================
# 扫描任务管理器
# =========================

class SecurityScanTask:
    """单次安全扫描任务"""

    def __init__(self, task_id: str, target: str, level: str):
        self.task_id = task_id
        self.target = target
        self.level = level
        self.config = SCAN_LEVELS.get(level, SCAN_LEVELS["low"])
        self.status = "pending"  # pending / running / completed / failed
        self.progress = 0  # 0-100
        self.current_step = ""
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.result: dict = {}
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def update_progress(self, percent: int, step: str = ""):
        with self._lock:
            self.progress = min(percent, 100)
            if step:
                self.current_step = step

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "task_id": self.task_id,
                "target": self.target,
                "level": self.level,
                "level_name": self.config["name"],
                "status": self.status,
                "progress": self.progress,
                "current_step": self.current_step,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "estimated_time": self.config["estimated_time"],
                "error": self.error,
            }

    def to_result_dict(self) -> dict:
        with self._lock:
            return {
                "task_id": self.task_id,
                "target": self.target,
                "level": self.level,
                "level_name": self.config["name"],
                "status": self.status,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "duration_seconds": (self.end_time - self.start_time).total_seconds() if self.start_time and self.end_time else 0,
                "result": self.result,
                "error": self.error,
            }


# =========================
# 扫描引擎
# =========================

class SecurityScanEngine:
    """三级安全扫描引擎"""

    def __init__(self, task: SecurityScanTask, progress_callback: Callable = None):
        self.task = task
        self.target = task.target
        self.config = task.config
        self.progress_callback = progress_callback
        self.assistant = NetSecAssistant(
            timeout=self.config["timeout"],
            workers=self.config["workers"]
        )

    def _report_progress(self, percent: int, step: str):
        self.task.update_progress(percent, step)
        if self.progress_callback:
            try:
                self.progress_callback(self.task.to_dict())
            except Exception:
                pass

    def _resolve_target(self) -> Optional[str]:
        """解析目标 IP"""
        try:
            return socket.gethostbyname(self.target)
        except socket.gaierror:
            return None

    def _step_port_scan(self, target_ip: str) -> dict:
        """执行端口扫描"""
        self._report_progress(5, "正在解析目标...")

        ports = self.assistant.parse_ports(self.config["ports"])
        total_ports = len(ports)
        open_ports = []
        services = []

        self._report_progress(10, f"端口扫描中 ({total_ports} 个端口)...")

        with ThreadPoolExecutor(max_workers=self.config["workers"]) as executor:
            future_to_port = {
                executor.submit(self.assistant.scan_port, target_ip, port): port
                for port in ports
            }
            completed = 0
            for future in as_completed(future_to_port):
                port = future_to_port[future]
                completed += 1
                try:
                    result = future.result()
                    if result is not None:
                        open_ports.append(result)
                        service_name = COMMON_PORTS_SERVICE.get(result, "未知")
                        risk = PORT_RISK_MAP.get(result, ("低", ""))
                        services.append({
                            "port": result,
                            "service": service_name,
                            "risk_level": risk[0],
                            "risk_note": risk[1],
                        })
                except Exception:
                    pass

                # 每完成 5% 更新进度
                if completed % max(1, total_ports // 20) == 0:
                    pct = 10 + int(completed / total_ports * 30)
                    self._report_progress(pct, f"端口扫描: {completed}/{total_ports}")

        open_ports.sort()
        services.sort(key=lambda x: x["port"])

        risk_summary = {"高": 0, "中": 0, "低": 0}
        for s in services:
            risk_summary[s["risk_level"]] = risk_summary.get(s["risk_level"], 0) + 1

        return {
            "total_scanned": total_ports,
            "open_ports": open_ports,
            "open_count": len(open_ports),
            "services": services,
            "risk_summary": risk_summary,
        }

    def _step_waf_detect(self, target_url: str) -> dict:
        """WAF 检测"""
        self._report_progress(42, "检测 WAF 防火墙...")

        # 保存原日志，获取新日志
        self.assistant.results_log = []
        try:
            self.assistant.detect_waf(target_url)
        except Exception:
            pass
        logs = list(self.assistant.results_log)

        waf_detected = []
        for line in logs:
            if "检测到WAF" in line or "检测到WAF" in line:
                waf_detected.append(line.strip())
            elif "未检测到" in line or "未检测到" in line:
                waf_detected.append(line.strip())

        return {
            "logs": logs,
            "detected": waf_detected,
            "has_waf": len(waf_detected) > 0 and "未检测到" not in str(waf_detected),
        }

    def _step_fingerprint(self, target_ip: str, open_ports: list) -> dict:
        """指纹识别"""
        self._report_progress(52, "识别服务指纹...")

        fingerprints = []
        target_ports = open_ports[:30]  # 最多识别30个端口
        if not target_ports:
            target_ports = [80, 443, 22, 3306, 8080]

        for i, port in enumerate(target_ports):
            try:
                banner = self.assistant.get_banner(target_ip, port)
                service = COMMON_PORTS_SERVICE.get(port, "未知")
                fingerprints.append({
                    "port": port,
                    "service": service,
                    "banner": banner[:120] if banner else "无Banner",
                })
            except Exception:
                fingerprints.append({
                    "port": port,
                    "service": COMMON_PORTS_SERVICE.get(port, "未知"),
                    "banner": "获取失败",
                })
            if len(target_ports) > 0:
                pct = 52 + int(i / len(target_ports) * 10)
                self._report_progress(pct, f"指纹识别: {i+1}/{len(target_ports)}")

        return {"fingerprints": fingerprints, "count": len(fingerprints)}

    def _step_subdomain_enum(self, domain: str) -> dict:
        """子域名枚举"""
        self._report_progress(64, "子域名枚举...")

        try:
            valid_subs = self.assistant.run_subdomain_enum(domain)
        except Exception:
            valid_subs = []
        subs = valid_subs or []

        return {
            "subdomains": subs[:50],  # 最多保留50个
            "count": len(subs),
        }

    def _step_web_dir_scan(self, target_url: str) -> dict:
        """Web 目录扫描"""
        self._report_progress(74, "Web 目录扫描...")

        DEFAULT_DICT = [
            "admin", "login", "index.php", "backup", "db", "config",
            ".git", "robots.txt", "wp-admin", "shell.php", "upload",
            "api", "test", "dev", "console", "phpinfo.php", ".env",
            "admin.php", "wp-login.php", "phpmyadmin", "manager",
            ".svn", ".hg", ".DS_Store", "docker-compose.yml",
            "admin/login", "api/v1", "graphql", "swagger", "actuator",
            "jenkins", "web.config", "server-status", ".htaccess",
        ]

        results = []
        try:
            with ThreadPoolExecutor(max_workers=min(20, self.config["workers"])) as executor:
                future_map = {
                    executor.submit(network_scan.scan_dir, target_url, path, 3): path
                    for path in DEFAULT_DICT
                }
                completed = 0
                for future in as_completed(future_map):
                    completed += 1
                    r = future.result()
                    if r:
                        path, code, size = r
                        results.append({"path": path, "code": code, "size": size})
                    if completed % 10 == 0:
                        pct = 74 + int(completed / len(DEFAULT_DICT) * 10)
                        self._report_progress(pct, f"目录扫描: {completed}/{len(DEFAULT_DICT)}")
        except Exception:
            pass

        results.sort(key=lambda x: x["code"])
        return {"directories": results, "count": len(results), "total_tested": len(DEFAULT_DICT)}

    def _step_vuln_assessment(self, scan_data: dict) -> dict:
        """漏洞评估报告 - AI 驱动的智能漏洞分析"""
        self._report_progress(88, "AI 漏洞评估中...")

        findings = []
        matched_vulns = []

        port_scan = scan_data.get("port_scan", {})
        waf = scan_data.get("waf", {})
        fingerprint = scan_data.get("fingerprint", {})
        subdomain = scan_data.get("subdomain", {})
        web_dir = scan_data.get("web_dir", {})

        # 1. 高危端口检测
        services = port_scan.get("services", [])
        high_risk_ports = [s for s in services if s["risk_level"] == "高"]
        if high_risk_ports:
            findings.append({
                "level": "高",
                "title": "发现高危端口",
                "detail": f"检测到 {len(high_risk_ports)} 个高危端口: " +
                          ", ".join(f"{s['port']}({s['service']})" for s in high_risk_ports),
                "suggestion": "建议关闭非必要的高危端口，或限制访问来源IP",
            })

        medium_risk_ports = [s for s in services if s["risk_level"] == "中"]
        if medium_risk_ports:
            findings.append({
                "level": "中",
                "title": "发现中危端口",
                "detail": f"检测到 {len(medium_risk_ports)} 个中危端口: " +
                          ", ".join(f"{s['port']}({s['service']})" for s in medium_risk_ports),
                "suggestion": "建议评估各端口的必要性，非必要端口应关闭",
            })

        # 2. WAF 缺失检测
        if waf.get("has_waf") is False:
            findings.append({
                "level": "中",
                "title": "未检测到 WAF 防护",
                "detail": "目标未部署 Web 应用防火墙，存在 Web 攻击风险",
                "suggestion": "建议部署 WAF（如 ModSecurity、Cloudflare 等）",
            })

        # 3. Web 敏感路径检测
        web_dirs = web_dir.get("directories", [])
        sensitive_paths = [d for d in web_dirs if d["path"] in [".git", ".env", "backup", "db",
                            "phpmyadmin", ".svn", "docker-compose.yml", ".DS_Store",
                            "jenkins", "phpinfo.php"]]
        if sensitive_paths:
            findings.append({
                "level": "高",
                "title": "发现敏感路径/文件",
                "detail": f"发现 {len(sensitive_paths)} 个敏感路径: " +
                          ", ".join(d["path"] for d in sensitive_paths),
                "suggestion": "立即限制对敏感路径的访问，移除或保护敏感文件",
            })

        # 4. 子域名暴露面
        sub_count = subdomain.get("count", 0)
        if sub_count > 20:
            findings.append({
                "level": "中",
                "title": "子域名暴露面较大",
                "detail": f"发现 {sub_count} 个子域名，攻击面较大",
                "suggestion": "审查子域名列表，关闭不再使用的子域名",
            })

        # 5. Banner 信息泄露
        fps = fingerprint.get("fingerprints", [])
        info_leak_fps = [f for f in fps if any(kw in str(f.get("banner", "")).lower()
                         for kw in ["version", "apache/2.4", "nginx/1", "php/",
                                     "openssh", "mysql", "mariadb", "postgresql"])]
        if info_leak_fps:
            findings.append({
                "level": "低",
                "title": "服务版本信息泄露",
                "detail": f"发现 {len(info_leak_fps)} 个服务暴露了版本信息",
                "suggestion": "配置服务隐藏版本号（如 Nginx server_tokens off）",
            })

        # 6. 开放端口过多
        open_count = port_scan.get("open_count", 0)
        if open_count > 20:
            findings.append({
                "level": "中",
                "title": "开放端口过多",
                "detail": f"检测到 {open_count} 个开放端口，增大了攻击面",
                "suggestion": "进行端口最小化，仅保留业务必需的端口",
            })

        # ========== AI 驱动的漏洞数据库匹配 ==========
        self._report_progress(92, "AI 漏洞数据库匹配中...")

        matched_vulns = self._match_vulnerabilities(services, fps, web_dirs)

        if matched_vulns:
            findings.append({
                "level": "高" if any(v["severity"] == "严重" for v in matched_vulns) else "中",
                "title": f"AI 检测到 {len(matched_vulns)} 个匹配漏洞",
                "detail": f"基于漏洞数据库分析，发现 {len([v for v in matched_vulns if v['severity'] in ['严重', '高危']])} 个高危漏洞",
                "suggestion": "建议参考漏洞详情进行修复，关注严重级别漏洞",
            })

        # 7. 安全评分（包含 AI 漏洞评估）
        base_score = 100
        if high_risk_ports:
            base_score -= len(high_risk_ports) * 10
        if medium_risk_ports:
            base_score -= len(medium_risk_ports) * 3
        if waf.get("has_waf") is False:
            base_score -= 10
        if sensitive_paths:
            base_score -= len(sensitive_paths) * 8
        if sub_count > 20:
            base_score -= 5
        if open_count > 20:
            base_score -= min(15, (open_count - 20) * 2)
        if info_leak_fps:
            base_score -= len(info_leak_fps) * 2
        
        # AI 漏洞评分影响
        for vuln in matched_vulns:
            if vuln["severity"] == "严重":
                base_score -= 15
            elif vuln["severity"] == "高危":
                base_score -= 10
            elif vuln["severity"] == "中危":
                base_score -= 5

        score = max(0, min(100, base_score))
        if score >= 80:
            grade = "A"
            grade_text = "安全状态良好"
        elif score >= 60:
            grade = "B"
            grade_text = "存在一定风险，建议优化"
        elif score >= 40:
            grade = "C"
            grade_text = "存在较多风险，需要修复"
        elif score >= 20:
            grade = "D"
            grade_text = "风险较高，建议立即修复"
        else:
            grade = "F"
            grade_text = "严重风险，必须立即修复"

        return {
            "findings": findings,
            "total_findings": len(findings),
            "high_count": len([f for f in findings if f["level"] == "高"]),
            "medium_count": len([f for f in findings if f["level"] == "中"]),
            "low_count": len([f for f in findings if f["level"] == "低"]),
            "security_score": score,
            "security_grade": grade,
            "grade_text": grade_text,
            "matched_vulnerabilities": matched_vulns,
            "matched_vulns_count": len(matched_vulns),
        }

    def _match_vulnerabilities(self, services: list, fingerprints: list, web_dirs: list) -> list:
        """AI 漏洞数据库匹配 - 根据服务和指纹信息匹配已知漏洞"""
        matched_vulns = []
        matched_ids = set()

        # 服务名称匹配
        for service in services:
            service_name = service.get("service", "").lower()
            
            if "redis" in service_name:
                vuln = ExploitDB.get_vulnerability("CVE-2015-8080")
                if vuln and "CVE-2015-8080" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2015-8080")
            
            elif "smb" in service_name or service.get("port") == 445:
                vuln = ExploitDB.get_vulnerability("CVE-2017-0144")
                if vuln and "CVE-2017-0144" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2017-0144")
            
            elif "mysql" in service_name or service.get("port") == 3306:
                vuln = ExploitDB.get_vulnerability("CVE-2020-2574")
                if vuln and "CVE-2020-2574" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2020-2574")
            
            elif service.get("port") == 3389:
                vuln = ExploitDB.get_vulnerability("CVE-2019-0708")
                if vuln and "CVE-2019-0708" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2019-0708")

        # Banner 版本信息匹配
        for fp in fingerprints:
            banner = str(fp.get("banner", "")).lower()
            port = fp.get("port", 0)
            
            if "phpmyadmin" in banner:
                vuln = ExploitDB.get_vulnerability("CVE-2018-12613")
                if vuln and "CVE-2018-12613" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2018-12613")
            
            elif "jenkins" in banner:
                vuln = ExploitDB.get_vulnerability("CVE-2018-1000861")
                if vuln and "CVE-2018-1000861" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2018-1000861")
            
            elif "glassfish" in banner:
                vuln = ExploitDB.get_vulnerability("CVE-2019-17568")
                if vuln and "CVE-2019-17568" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2019-17568")
            
            elif "spring" in banner or "actuator" in banner:
                vuln = ExploitDB.get_vulnerability("CVE-2018-1270")
                if vuln and "CVE-2018-1270" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2018-1270")
            
            elif "log4j" in banner or "log4" in banner:
                vuln = ExploitDB.get_vulnerability("CVE-2021-44228")
                if vuln and "CVE-2021-44228" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2021-44228")
            
            elif "nginx/1.0" in banner or "nginx/1.1" in banner:
                vuln = ExploitDB.get_vulnerability("CVE-2013-4548")
                if vuln and "CVE-2013-4548" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2013-4548")

        # Web 目录匹配
        for web_dir in web_dirs:
            path = web_dir.get("path", "").lower()
            
            if "phpmyadmin" in path:
                vuln = ExploitDB.get_vulnerability("CVE-2018-12613")
                if vuln and "CVE-2018-12613" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2018-12613")
            
            elif "jenkins" in path:
                vuln = ExploitDB.get_vulnerability("CVE-2018-1000861")
                if vuln and "CVE-2018-1000861" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2018-1000861")
            
            elif "actuator" in path:
                vuln = ExploitDB.get_vulnerability("CVE-2018-1270")
                if vuln and "CVE-2018-1270" not in matched_ids:
                    matched_vulns.append(vuln)
                    matched_ids.add("CVE-2018-1270")

        # 添加 CVE 编号
        for i, vuln in enumerate(matched_vulns):
            matched_vulns[i]["cve_id"] = list(ExploitDB.VULNERABILITIES.keys())[
                list(ExploitDB.VULNERABILITIES.values()).index(vuln)
            ] if vuln in ExploitDB.VULNERABILITIES.values() else "Unknown"

        return matched_vulns

    def run(self):
        """执行完整扫描流程"""
        task = self.task
        task.status = "running"
        task.start_time = datetime.now()
        config = self.config

        try:
            # Step 0: 解析目标
            target_ip = self._resolve_target()
            if not target_ip:
                task.status = "failed"
                task.error = f"无法解析目标: {self.target}"
                self._report_progress(100, "扫描失败")
                return

            result = {
                "target": self.target,
                "target_ip": target_ip,
                "level": task.level,
                "scan_time": task.start_time.isoformat(),
            }

            # 构建目标 URL
            target_url = self.target
            if not target_url.startswith(("http://", "https://")):
                target_url = "http://" + target_url

            # 清洗域名
            domain = self.target.replace("http://", "").replace("https://", "").split("/")[0]

            # Step 1: 端口扫描
            if config["enable_port_scan"]:
                result["port_scan"] = self._step_port_scan(target_ip)
            else:
                result["port_scan"] = {"open_ports": [], "open_count": 0, "services": [], "risk_summary": {}}

            # Step 2: WAF 检测
            if config["enable_waf"]:
                result["waf"] = self._step_waf_detect(target_url)
            else:
                result["waf"] = {"has_waf": None, "logs": [], "detected": []}

            # Step 3: 指纹识别
            if config["enable_fingerprint"]:
                open_ports = result["port_scan"].get("open_ports", [])
                result["fingerprint"] = self._step_fingerprint(target_ip, open_ports)
            else:
                result["fingerprint"] = {"fingerprints": [], "count": 0}

            # Step 4: 子域名枚举
            if config["enable_subdomain"]:
                result["subdomain"] = self._step_subdomain_enum(domain)
            else:
                result["subdomain"] = {"subdomains": [], "count": 0}

            # Step 5: Web 目录扫描
            if config["enable_web_dir"]:
                result["web_dir"] = self._step_web_dir_scan(target_url)
            else:
                result["web_dir"] = {"directories": [], "count": 0}

            # Step 6: 漏洞评估（基于前面结果生成）
            if config["enable_vuln_assessment"]:
                result["vuln_assessment"] = self._step_vuln_assessment(result)
            else:
                result["vuln_assessment"] = {
                    "findings": [],
                    "security_score": None,
                    "security_grade": "N/A",
                }

            self._report_progress(100, "扫描完成")

            task.result = result
            task.status = "completed"
            task.end_time = datetime.now()

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.end_time = datetime.now()
            self._report_progress(100, f"扫描失败: {str(e)[:50]}")


# =========================
# 全局任务管理器
# =========================

_tasks: dict[str, SecurityScanTask] = {}
_tasks_lock = threading.Lock()

# 最多保留 50 个历史任务
_MAX_TASKS = 50


def create_scan_task(target: str, level: str) -> SecurityScanTask:
    """创建并启动扫描任务"""
    import uuid
    task_id = uuid.uuid4().hex[:12]
    task = SecurityScanTask(task_id, target, level)

    with _tasks_lock:
        _tasks[task_id] = task
        # 清理旧任务
        if len(_tasks) > _MAX_TASKS:
            oldest = sorted(_tasks.keys())[:len(_tasks) - _MAX_TASKS]
            for k in oldest:
                _tasks.pop(k, None)

    # 在线程中执行
    engine = SecurityScanEngine(task)
    t = threading.Thread(target=engine.run, daemon=True)
    t.start()

    return task


def get_task(task_id: str) -> Optional[SecurityScanTask]:
    with _tasks_lock:
        return _tasks.get(task_id)


def get_task_status(task_id: str) -> Optional[dict]:
    task = get_task(task_id)
    if task:
        return task.to_dict()
    return None


def get_task_result(task_id: str) -> Optional[dict]:
    task = get_task(task_id)
    if task and task.status in ("completed", "failed"):
        return task.to_result_dict()
    return None


def get_level_config(level: str) -> Optional[dict]:
    """获取某个等级配置（不含敏感信息）"""
    config = SCAN_LEVELS.get(level)
    if not config:
        return None
    return {
        "name": config["name"],
        "description": config["description"],
        "icon": config["icon"],
        "estimated_time": config["estimated_time"],
        "features": {
            "端口扫描": config["enable_port_scan"],
            "WAF检测": config["enable_waf"],
            "指纹识别": config["enable_fingerprint"],
            "子域名枚举": config["enable_subdomain"],
            "Web目录扫描": config["enable_web_dir"],
            "漏洞评估报告": config["enable_vuln_assessment"],
        },
    }
