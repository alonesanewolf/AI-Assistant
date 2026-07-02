"""
系统监控模块
===========
提供 CPU、内存、磁盘、网络、进程的实时监控功能

功能:
  1. CPU 监控 - 使用率、核心数、温度
  2. 内存监控 - 已用、可用、缓存、交换分区
  3. 磁盘监控 - 各分区使用率、读写速度
  4. 网络监控 - 上传/下载速度、连接数、流量统计
  5. 进程监控 - 进程列表、CPU/内存占用 Top 10
  6. 系统信息 - 操作系统、内核版本、运行时间
  7. 健康度评估 - 综合评估系统健康状态

技术要求:
  - 使用 psutil 库实现跨平台监控
  - 支持 Windows/Linux/macOS
  - 返回字典格式数据，便于 JSON 序列化
"""

import psutil
import platform
import time
import datetime
from typing import Dict, List, Optional


class SystemMonitor:
    """系统监控类"""
    
    def __init__(self):
        self._prev_net_io = None
        self._prev_time = None
    
    def get_cpu_info(self) -> Dict:
        """获取 CPU 信息"""
        try:
            cpu_count = psutil.cpu_count(logical=False) or 0
            cpu_count_logical = psutil.cpu_count(logical=True) or 0
            cpu_usage = psutil.cpu_percent(interval=0.5)
            cpu_times = psutil.cpu_times()
            
            cpu_freq = psutil.cpu_freq()
            cpu_freq_dict = {
                "current": cpu_freq.current if cpu_freq else 0,
                "min": cpu_freq.min if cpu_freq else 0,
                "max": cpu_freq.max if cpu_freq else 0,
            }
            
            per_cpu_usage = psutil.cpu_percent(interval=0.5, percpu=True)
            
            cpu_temp = self._get_cpu_temp()
            
            return {
                "success": True,
                "physical_cores": cpu_count,
                "logical_cores": cpu_count_logical,
                "total_usage": cpu_usage,
                "per_core_usage": per_cpu_usage,
                "frequency": cpu_freq_dict,
                "times": {
                    "user": cpu_times.user,
                    "system": cpu_times.system,
                    "idle": cpu_times.idle,
                    "nice": getattr(cpu_times, "nice", 0),
                    "iowait": getattr(cpu_times, "iowait", 0),
                    "irq": getattr(cpu_times, "irq", 0),
                    "softirq": getattr(cpu_times, "softirq", 0),
                    "steal": getattr(cpu_times, "steal", 0),
                    "guest": getattr(cpu_times, "guest", 0),
                },
                "temperature": cpu_temp,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _get_cpu_temp(self) -> Dict:
        """获取 CPU 温度（Linux/macOS）"""
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                cpu_temp = temps.get("cpu-thermal") or temps.get("coretemp") or temps.get("acpitz")
                if cpu_temp:
                    return {
                        "available": True,
                        "current": cpu_temp[0].current,
                        "high": cpu_temp[0].high,
                        "critical": cpu_temp[0].critical,
                    }
            return {"available": False, "current": 0, "high": 0, "critical": 0}
        except Exception:
            return {"available": False, "current": 0, "high": 0, "critical": 0}
    
    def get_memory_info(self) -> Dict:
        """获取内存信息"""
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            return {
                "success": True,
                "total": mem.total,
                "available": mem.available,
                "used": mem.used,
                "free": mem.free,
                "active": getattr(mem, "active", 0),
                "inactive": getattr(mem, "inactive", 0),
                "buffers": getattr(mem, "buffers", 0),
                "cached": getattr(mem, "cached", 0),
                "shared": getattr(mem, "shared", 0),
                "usage_percent": mem.percent,
                "swap": {
                    "total": swap.total,
                    "used": swap.used,
                    "free": swap.free,
                    "usage_percent": swap.percent,
                    "sin": swap.sin,
                    "sout": swap.sout,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_disk_info(self) -> Dict:
        """获取磁盘信息"""
        try:
            partitions = psutil.disk_partitions(all=False)
            disk_info = []
            
            for partition in partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    io_counters = psutil.disk_io_counters(perdisk=True).get(partition.device.split('/')[-1], None)
                    
                    disk_info.append({
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "fstype": partition.fstype,
                        "opts": partition.opts,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "usage_percent": usage.percent,
                        "io": {
                            "read_count": io_counters.read_count if io_counters else 0,
                            "write_count": io_counters.write_count if io_counters else 0,
                            "read_bytes": io_counters.read_bytes if io_counters else 0,
                            "write_bytes": io_counters.write_bytes if io_counters else 0,
                            "read_time": io_counters.read_time if io_counters else 0,
                            "write_time": io_counters.write_time if io_counters else 0,
                        } if io_counters else {},
                    })
                except Exception:
                    continue
            
            disk_io_total = psutil.disk_io_counters()
            
            return {
                "success": True,
                "partitions": disk_info,
                "total_io": {
                    "read_count": disk_io_total.read_count,
                    "write_count": disk_io_total.write_count,
                    "read_bytes": disk_io_total.read_bytes,
                    "write_bytes": disk_io_total.write_bytes,
                    "read_time": disk_io_total.read_time,
                    "write_time": disk_io_total.write_time,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_network_info(self) -> Dict:
        """获取网络信息"""
        try:
            net_io = psutil.net_io_counters(pernic=True)
            net_if_addrs = psutil.net_if_addrs()
            net_if_stats = psutil.net_if_stats()
            
            interfaces = []
            for iface, io in net_io.items():
                addrs = net_if_addrs.get(iface, [])
                stats = net_if_stats.get(iface, None)
                
                ip_address = ""
                for addr in addrs:
                    if addr.family == 2:
                        ip_address = addr.address
                        break
                
                interfaces.append({
                    "name": iface,
                    "ip_address": ip_address,
                    "bytes_sent": io.bytes_sent,
                    "bytes_recv": io.bytes_recv,
                    "packets_sent": io.packets_sent,
                    "packets_recv": io.packets_recv,
                    "errin": io.errin,
                    "errout": io.errout,
                    "dropin": io.dropin,
                    "dropout": io.dropout,
                    "speed": stats.speed if stats else 0,
                    "is_up": stats.isup if stats else False,
                })
            
            speed_info = self._calculate_network_speed(net_io)
            
            return {
                "success": True,
                "interfaces": interfaces,
                "speed": speed_info,
                "connections": len(psutil.net_connections()),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _calculate_network_speed(self, net_io: Dict) -> Dict:
        """计算网络速度"""
        current_time = time.time()
        current_io = psutil.net_io_counters()
        
        if self._prev_net_io is None or self._prev_time is None:
            self._prev_net_io = current_io
            self._prev_time = current_time
            return {"upload_speed": 0, "download_speed": 0}
        
        time_diff = current_time - self._prev_time
        if time_diff < 0.1:
            return {"upload_speed": 0, "download_speed": 0}
        
        upload_speed = (current_io.bytes_sent - self._prev_net_io.bytes_sent) / time_diff
        download_speed = (current_io.bytes_recv - self._prev_net_io.bytes_recv) / time_diff
        
        self._prev_net_io = current_io
        self._prev_time = current_time
        
        return {
            "upload_speed": upload_speed,
            "download_speed": download_speed,
        }
    
    def get_process_info(self, limit: int = 10) -> Dict:
        """获取进程信息"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status', 'create_time']):
                try:
                    info = proc.info
                    processes.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu_percent": info['cpu_percent'],
                        "memory_percent": info['memory_percent'],
                        "memory_used": info['memory_info'].rss if info['memory_info'] else 0,
                        "status": info['status'],
                        "create_time": info['create_time'],
                        "create_time_str": datetime.datetime.fromtimestamp(info['create_time']).strftime('%Y-%m-%d %H:%M:%S'),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError):
                    continue
                except Exception:
                    continue
            
            processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
            top_cpu = processes[:limit]
            
            processes.sort(key=lambda x: x['memory_percent'], reverse=True)
            top_memory = processes[:limit]
            
            return {
                "success": True,
                "total_processes": len(processes),
                "top_cpu": top_cpu,
                "top_memory": top_memory,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_system_info(self) -> Dict:
        """获取系统信息"""
        try:
            boot_time = psutil.boot_time()
            boot_time_str = datetime.datetime.fromtimestamp(boot_time).strftime('%Y-%m-%d %H:%M:%S')
            
            uptime_seconds = time.time() - boot_time
            uptime_str = str(datetime.timedelta(seconds=int(uptime_seconds)))
            
            return {
                "success": True,
                "os": platform.system(),
                "os_version": platform.version(),
                "os_release": platform.release(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
                "boot_time": boot_time,
                "boot_time_str": boot_time_str,
                "uptime_seconds": int(uptime_seconds),
                "uptime_str": uptime_str,
                "hostname": platform.node(),
                "user": psutil.users()[0].name if psutil.users() else "",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_health_status(self) -> Dict:
        """获取系统健康状态"""
        cpu = self.get_cpu_info()
        memory = self.get_memory_info()
        disk = self.get_disk_info()
        
        if not cpu["success"] or not memory["success"] or not disk["success"]:
            return {
                "success": False,
                "health_score": 0,
                "status": "未知",
                "details": "获取系统信息失败",
            }
        
        cpu_score = max(0, 100 - cpu["total_usage"])
        mem_score = max(0, 100 - memory["usage_percent"])
        
        max_disk_usage = 0
        for partition in disk.get("partitions", []):
            if partition.get("usage_percent", 0) > max_disk_usage:
                max_disk_usage = partition["usage_percent"]
        disk_score = max(0, 100 - max_disk_usage)
        
        health_score = (cpu_score + mem_score + disk_score) / 3
        
        if health_score >= 80:
            status = "健康"
        elif health_score >= 60:
            status = "良好"
        elif health_score >= 40:
            status = "警告"
        else:
            status = "危险"
        
        issues = []
        if cpu["total_usage"] > 90:
            issues.append(f"CPU 使用率过高 ({cpu['total_usage']}%)")
        if memory["usage_percent"] > 90:
            issues.append(f"内存使用率过高 ({memory['usage_percent']}%)")
        for partition in disk.get("partitions", []):
            if partition.get("usage_percent", 0) > 90:
                issues.append(f"磁盘 {partition['mountpoint']} 使用率过高 ({partition['usage_percent']}%)")
        
        return {
            "success": True,
            "health_score": round(health_score, 2),
            "status": status,
            "details": {
                "cpu_score": round(cpu_score, 2),
                "mem_score": round(mem_score, 2),
                "disk_score": round(disk_score, 2),
            },
            "issues": issues,
            "cpu_usage": cpu["total_usage"],
            "memory_usage": memory["usage_percent"],
            "disk_usage": max_disk_usage,
        }
    
    def get_full_status(self) -> Dict:
        """获取完整系统状态"""
        return {
            "success": True,
            "timestamp": time.time(),
            "timestamp_str": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "health": self.get_health_status(),
            "cpu": self.get_cpu_info(),
            "memory": self.get_memory_info(),
            "disk": self.get_disk_info(),
            "network": self.get_network_info(),
            "processes": self.get_process_info(),
            "system": self.get_system_info(),
        }


system_monitor = SystemMonitor()