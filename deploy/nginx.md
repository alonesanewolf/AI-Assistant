# CentOS 7.6 在线安装 Nginx + 反向代理 + 负载均衡 完整案例

- [环境说明](#环境说明)
- [一、Nginx 在线安装](#一nginx-在线安装)
- [二、Nginx 基础操作](#二nginx-基础操作)
- [三、反向代理配置](#三反向代理配置)
- [四、负载均衡配置](#四负载均衡配置)
- [五、完整测试验证](#五完整测试验证)
- [六、常见问题排查](#六常见问题排查)

---

## 环境说明

| 项目 | 说明 |
|------|------|
| 操作系统 | CentOS 7.6 (x86_64) |
| Nginx 版本 | 1.20.x (稳定版) |
| 后端服务 | Node.js / Python (模拟) |
| 端口规划 | Nginx: 80, 后端1: 8081, 后端2: 8082, 后端3: 8083 |

**架构图：**

```
                     ┌─────────────────┐
                     │   客户端/浏览器    │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │   Nginx :80     │
                     │  反向代理/负载均衡  │
                     └────────┬────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
     │  后端服务 1   │ │  后端服务 2   │ │  后端服务 3   │
     │  :8081       │ │  :8082       │ │  :8083       │
     └─────────────┘ └─────────────┘ └─────────────┘
```

---

## 一、Nginx 在线安装

### 1.1 添加 Nginx 官方 YUM 源

```bash
# 创建 nginx.repo 文件
cat > /etc/yum.repos.d/nginx.repo << 'EOF'
[nginx-stable]
name=nginx stable repo
baseurl=http://nginx.org/packages/centos/$releasever/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
EOF
```

### 1.2 查看可安装版本

```bash
yum list nginx --showduplicates
```

### 1.3 安装 Nginx

```bash
# 安装 nginx
yum install -y nginx

# 查看安装版本
nginx -v
```

### 1.4 启动并设置开机自启

```bash
# 启动 nginx
systemctl start nginx

# 设置开机自启
systemctl enable nginx

# 查看运行状态
systemctl status nginx
```

### 1.5 防火墙配置

```bash
# 开放 80 端口
firewall-cmd --zone=public --add-port=80/tcp --permanent

# 如果后端服务需要从外部访问（仅测试用）
firewall-cmd --zone=public --add-port=8081/tcp --permanent
firewall-cmd --zone=public --add-port=8082/tcp --permanent
firewall-cmd --zone=public --add-port=8083/tcp --permanent

# 重载防火墙
firewall-cmd --reload

# 验证端口
firewall-cmd --list-ports
```

> **提示**：如果防火墙未启用或使用 iptables，请自行调整。测试环境可直接 `systemctl stop firewalld`。

### 1.6 关闭 SELinux（测试环境推荐）

```bash
# 临时关闭
setenforce 0

# 永久关闭（需重启）
sed -i 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config
```

---

## 二、Nginx 基础操作

### 2.1 常用命令

```bash
# 启动
systemctl start nginx

# 停止
systemctl stop nginx

# 重启
systemctl restart nginx

# 重载配置（不停机）
nginx -s reload
# 或
systemctl reload nginx

# 测试配置文件语法
nginx -t

# 查看 Nginx 主配置文件路径
nginx -V 2>&1 | grep conf-path
```

### 2.2 配置文件结构

```
/etc/nginx/
├── nginx.conf              # 主配置文件
├── conf.d/                 # 子配置目录（推荐在此创建配置）
│   └── default.conf        # 默认站点配置
├── mime.types              # MIME 类型定义
├── fastcgi_params          # FastCGI 参数	
└── modules/                # 模块目录
```

### 2.3 主配置文件说明

`/etc/nginx/nginx.conf` 关键配置：

```nginx
user  nginx;                          # 运行用户
worker_processes  auto;               # 工作进程数（auto = CPU核心数）
error_log  /var/log/nginx/error.log;  # 错误日志
pid        /var/run/nginx.pid;        # PID文件

events {
    worker_connections  1024;         # 每个进程最大连接数
    use epoll;                        # Linux 下推荐使用 epoll 事件模型
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # 日志格式
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';

    access_log  /var/log/nginx/access.log  main;

    sendfile        on;
    keepalive_timeout  65;

    # 引入子配置文件
    include /etc/nginx/conf.d/*.conf;
}
```

---

## 三、反向代理配置

### 3.1 什么是反向代理？

反向代理位于客户端和后端服务器之间，客户端请求先到 Nginx，Nginx 再将请求转发给后端服务器，并将后端响应返回给客户端。客户端并不知道后端服务器的存在。

### 3.2 启动模拟后端服务

首先创建几个简单的后端服务用于测试（使用 Python）：

**后端服务 1 (端口 8081)：**

```bash
# 创建测试页面
mkdir -p /opt/backend/server1
cat > /opt/backend/server1/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>后端服务 1</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 100px auto; width: 600px; text-align: center; }
        .server { color: #fff; padding: 40px; border-radius: 10px; }
        .s1 { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
    </style>
</head>
<body>
    <div class="server s1">
        <h1>🖥️ 后端服务 1</h1>
        <p>端口: 8081</p>
        <p>服务器地址: SERVER_ADDR_PLACEHOLDER</p>
    </div>
</body>
</html>
EOF

# 启动 Python HTTP 服务
cd /opt/backend/server1 && nohup python -m SimpleHTTPServer 8081 > /dev/null 2>&1 &
echo "后端服务1已启动，PID: $!"
```

**后端服务 2 (端口 8082)：**

```bash
mkdir -p /opt/backend/server2
cat > /opt/backend/server2/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>后端服务 2</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 100px auto; width: 600px; text-align: center; }
        .server { color: #fff; padding: 40px; border-radius: 10px; }
        .s2 { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
    </style>
</head>
<body>
    <div class="server s2">
        <h1>🖥️ 后端服务 2</h1>
        <p>端口: 8082</p>
        <p>服务器地址: SERVER_ADDR_PLACEHOLDER</p>
    </div>
</body>
</html>
EOF

cd /opt/backend/server2 && nohup python -m SimpleHTTPServer 8082 > /dev/null 2>&1 &
echo "后端服务2已启动，PID: $!"
```

### 3.3 反向代理配置文件

创建 `/etc/nginx/conf.d/proxy.conf`：

```nginx
# ============================================
# 反向代理配置
# ============================================

# 上游后端服务器定义（upstream）
upstream backend_app {
    server 127.0.0.1:8081 weight=1 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:8082 weight=1 max_fails=3 fail_timeout=30s;
    # 健康检查配置
    # max_fails: 最大失败次数
    # fail_timeout: 失败超时后重新尝试的时间
}

server {
    listen 80;
    # 如果有域名，替换为实际域名
    server_name _;

    # 字符集
    charset utf-8;

    # 访问日志（使用自定义格式记录代理信息）
    access_log /var/log/nginx/proxy_access.log main;
    error_log  /var/log/nginx/proxy_error.log  warn;

    # ========== 反向代理核心配置 ==========
    location / {
        # 代理到上游服务器
        proxy_pass http://backend_app;

        # 传递真实客户端 IP
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto  $scheme;

        # 代理缓冲区设置
        proxy_buffering            on;
        proxy_buffer_size          4k;
        proxy_buffers              8 32k;
        proxy_busy_buffers_size    64k;

        # 超时设置
        proxy_connect_timeout      30s;   # 连接后端超时
        proxy_send_timeout         60s;   # 发送请求到后端超时
        proxy_read_timeout         60s;   # 读取后端响应超时

        # 开启 WebSocket 支持（如需要）
        proxy_http_version         1.1;
        proxy_set_header           Upgrade    $http_upgrade;
        proxy_set_header           Connection "upgrade";
    }

    # ========== 静态资源单独处理（性能优化） ==========
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|woff|woff2|ttf|svg|eot)$ {
        proxy_pass http://backend_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # 静态资源缓存
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # ========== 健康检查端点 ==========
    location /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

### 3.4 应用反向代理配置

```bash
# 测试配置语法
nginx -t

# 重载配置
nginx -s reload

# 验证服务
curl http://localhost/
curl http://localhost/health
```

---

## 四、负载均衡配置

### 4.1 Nginx 支持的负载均衡策略

| 策略 | 指令 | 说明 |
|------|------|------|
| **轮询（默认）** | 无需指定 | 请求按时间顺序逐一分配到后端 |
| **加权轮询** | `weight=N` | 权重越高分配越多，适合后端性能不均 |
| **IP Hash** | `ip_hash` | 同一客户端 IP 固定分配到同一后端（解决 Session 问题） |
| **最少连接** | `least_conn` | 请求分配给当前活跃连接数最少的后端 |
| **URL Hash** | `hash $request_uri` | 相同 URL 请求分配到同一后端 |
| **Fair（第三方）** | `fair` | 按响应时间分配（需安装第三方模块） |

### 4.2 启动三个模拟后端服务

使用提供的启动脚本 `start_backends.sh`：

```bash
chmod +x start_backends.sh
./start_backends.sh
```

或者参考 `backends/` 目录下的各服务配置。

### 4.3 负载均衡配置文件

创建 `/etc/nginx/conf.d/loadbalance.conf`：

```nginx
# ============================================
# 负载均衡配置 - 完整示例
# ============================================

# 策略1：默认轮询（Round Robin）
upstream lb_round_robin {
    server 127.0.0.1:8081;
    server 127.0.0.1:8082;
    server 127.0.0.1:8083;
}

# 策略2：加权轮询（Weighted Round Robin）
# 8081 性能最强，分配更多请求
upstream lb_weighted {
    server 127.0.0.1:8081 weight=5;    # 权重 5
    server 127.0.0.1:8082 weight=3;    # 权重 3
    server 127.0.0.1:8083 weight=1;    # 权重 1
}

# 策略3：IP Hash（会话保持）
upstream lb_ip_hash {
    ip_hash;
    server 127.0.0.1:8081;
    server 127.0.0.1:8082;
    server 127.0.0.1:8083;
}

# 策略4：最少连接数
upstream lb_least_conn {
    least_conn;
    server 127.0.0.1:8081;
    server 127.0.0.1:8082;
    server 127.0.0.1:8083;
}

# 策略5：带健康检查 + 备用服务器
upstream lb_ha {
    server 127.0.0.1:8081 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:8082 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:8083 max_fails=3 fail_timeout=30s;
    # 备用服务器：仅当其他所有服务器都不可用时才启用
    server 127.0.0.1:8080 backup;
}


# ============== 虚拟主机配置 ==============

# --- 虚拟主机1：默认轮询 ---
server {
    listen 80;
    server_name lb.example.com;

    charset utf-8;
    access_log /var/log/nginx/lb_access.log main;
    error_log  /var/log/nginx/lb_error.log warn;

    location / {
        proxy_pass http://lb_round_robin;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-LB-Strategy     "round_robin";   # 自定义头：标识策略

        proxy_connect_timeout 5s;
        proxy_read_timeout    30s;
        proxy_send_timeout    30s;
    }
}


# --- 虚拟主机2：加权轮询 ---
server {
    listen 8090;
    server_name _;

    charset utf-8;
    access_log /var/log/nginx/lb_weighted_access.log main;

    location / {
        proxy_pass http://lb_weighted;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-LB-Strategy     "weighted";

        proxy_connect_timeout 5s;
        proxy_read_timeout    30s;
        proxy_send_timeout    30s;
    }
}


# --- 虚拟主机3：IP Hash ---
server {
    listen 8091;
    server_name _;

    charset utf-8;
    access_log /var/log/nginx/lb_iphash_access.log main;

    location / {
        proxy_pass http://lb_ip_hash;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-LB-Strategy     "ip_hash";

        proxy_connect_timeout 5s;
        proxy_read_timeout    30s;
        proxy_send_timeout    30s;
    }
}


# --- 虚拟主机4：最少连接 ---
server {
    listen 8092;
    server_name _;

    charset utf-8;
    access_log /var/log/nginx/lb_leastconn_access.log main;

    location / {
        proxy_pass http://lb_least_conn;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-LB-Strategy     "least_conn";

        proxy_connect_timeout 5s;
        proxy_read_timeout    30s;
        proxy_send_timeout    30s;
    }
}


# --- 统一入口：Nginx 状态页面 ---
server {
    listen 8088;
    server_name _;

    location /nginx_status {
        stub_status on;
        access_log off;
        allow 127.0.0.1;         # 仅允许本机访问
        deny all;
    }

    location / {
        return 200 "Nginx LB Status Page - Use /nginx_status for metrics\n";
        add_header Content-Type text/plain;
    }
}
```

### 4.4 应用负载均衡配置

```bash
# 测试配置语法
nginx -t

# 重载配置
nginx -s reload

# 查看 Nginx 状态
curl http://127.0.0.1:8088/nginx_status
```

### 4.5 Nginx 状态页面说明

访问 `http://127.0.0.1:8088/nginx_status` 会看到类似：

```
Active connections: 3
server accepts handled requests
 10 10 25
Reading: 0 Writing: 1 Waiting: 2
```

| 字段 | 说明 |
|------|------|
| Active connections | 当前活跃连接数 |
| accepts | 已接受的连接总数 |
| handled | 已处理的连接总数 |
| requests | 请求总数 |
| Reading | 正在读取请求头的连接数 |
| Writing | 正在写响应的连接数 |
| Waiting | 空闲等待的连接数 |

---

## 五、完整测试验证

### 5.1 启动所有服务

```bash
# 1. 确保 Nginx 运行
systemctl restart nginx

# 2. 启动后端模拟服务
chmod +x start_backends.sh
./start_backends.sh

# 3. 检查所有端口
netstat -tlnp | grep -E '80|8081|8082|8083|8088|8090|8091|8092'
```

### 5.2 测试反向代理

```bash
# 测试默认代理（轮询后端 8081 和 8082）
curl http://localhost/

# 多次请求，观察轮询效果
for i in {1..6}; do
    echo "=== 请求 #$i ==="
    curl -s http://localhost/ | grep -oP '(?<=端口: ).*(?=</p>)'
done
```

### 5.3 测试负载均衡策略

```bash
# --- 测试默认轮询（端口 80）---
echo "========== 默认轮询 =========="
for i in {1..6}; do
    echo -n "请求 $i -> "
    curl -s http://localhost/ | grep -oP '\d{4}' | head -1
done

# --- 测试加权轮询（端口 8090）---
echo "========== 加权轮询 (5:3:1) =========="
for i in {1..9}; do
    echo -n "请求 $i -> "
    curl -s http://localhost:8090/ | grep -oP '\d{4}' | head -1
done

# --- 测试 IP Hash（端口 8091）---
echo "========== IP Hash =========="
for i in {1..5}; do
    echo -n "请求 $i -> "
    curl -s http://localhost:8091/ | grep -oP '\d{4}' | head -1
done

# --- 测试最少连接（端口 8092）---
echo "========== 最少连接 =========="
for i in {1..6}; do
    echo -n "请求 $i -> "
    curl -s http://localhost:8092/ | grep -oP '\d{4}' | head -1
done
```

### 5.4 压力测试（可选，需要安装 ab 工具）

```bash
# 安装 Apache Bench
yum install -y httpd-tools

# 并发 100，总请求 1000 次
ab -n 1000 -c 100 http://localhost/

# 查看各后端日志
tail -f /var/log/nginx/lb_access.log
```

### 5.5 验证健康检查和故障转移

```bash
# 1. 模拟后端 8081 宕机
kill $(lsof -ti:8081)

# 2. 请求仍然正常（自动转移到其他后端）
curl http://localhost/

# 3. 查看 Nginx 错误日志
tail -f /var/log/nginx/lb_error.log
# 应该能看到类似: connect() failed (111: Connection refused) ... upstream: "..."
```

---

## 六、常见问题排查

### 6.1 端口被占用

```bash
# 查看端口占用情况
netstat -tlnp | grep 80
# 或
ss -tlnp | grep 80

# 杀死占用进程
kill -9 <PID>
```

### 6.2 502 Bad Gateway

```bash
# 检查后端服务是否启动
curl http://127.0.0.1:8081/

# 检查 Nginx 错误日志
tail -100 /var/log/nginx/error.log

# 查看 SELinux 是否阻止
getenforce
# 如果是 Enforcing：
setenforce 0  # 临时关闭测试
```

### 6.3 403 Forbidden

```bash
# 查看文件权限
ls -la /opt/backend/

# 查看 Nginx 错误日志
tail -50 /var/log/nginx/error.log
# 常见原因：目录无读权限或 index 文件不存在
```

### 6.4 配置语法错误

```bash
# 始终先用此命令检查配置
nginx -t

# 查看具体错误行
nginx -t 2>&1 | grep -i error
```

### 6.5 日志中大量 upstream 超时

```nginx
# 增加超时时间
proxy_connect_timeout 60s;
proxy_read_timeout    300s;
proxy_send_timeout    300s;
```

---

## 📁 项目文件清单

| 文件 | 说明 |
|------|------|
| `README.md` | 本文档 - 完整安装配置指南 |
| `conf/proxy.conf` | 反向代理配置模板 |
| `conf/loadbalance.conf` | 负载均衡配置模板（含5种策略） |
| `conf/full-example.conf` | 综合案例配置（反向代理+负载均衡） |
| `backends/server1/index.html` | 后端服务1 页面 |
| `backends/server2/index.html` | 后端服务2 页面 |
| `backends/server3/index.html` | 后端服务3 页面 |
| `start_backends.sh` | 一键启动所有后端服务脚本 |
| `test.sh` | 自动化测试脚本 |

---

## ⚙️ 快速开始（复制粘贴即用）

```bash
# === 一键部署脚本 ===
# 1. 安装 Nginx
cat > /etc/yum.repos.d/nginx.repo << 'EOF'
[nginx-stable]
name=nginx stable repo
baseurl=http://nginx.org/packages/centos/$releasever/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
EOF

yum install -y nginx
systemctl start nginx && systemctl enable nginx

# 2. 关闭防火墙和 SELinux（测试环境）
systemctl stop firewalld
setenforce 0

# 3. 创建后端页面并启动
for port in 8081 8082 8083; do
    mkdir -p /opt/backend/server${port##*8}
    cat > /opt/backend/server${port##*8}/index.html << EOF
<html><body><h1>Server Port: $port</h1></body></html>
EOF
    cd /opt/backend/server${port##*8} && nohup python -m SimpleHTTPServer $port &>/dev/null &
done

# 4. 配置 Nginx 反向代理+负载均衡
cat > /etc/nginx/conf.d/myapp.conf << 'NGINX_EOF'
upstream myapp {
    server 127.0.0.1:8081 weight=1;
    server 127.0.0.1:8082 weight=1;
    server 127.0.0.1:8083 weight=1;
}

server {
    listen 80;
    server_name _;
    charset utf-8;

    location / {
        proxy_pass http://myapp;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
NGINX_EOF

# 5. 重载 Nginx
nginx -t && nginx -s reload

# 6. 验证
curl http://localhost/

echo "部署完成！访问 http://服务器IP 即可测试"
```

---

> **提示**：生产环境请务必配置防火墙规则、开启 SELinux 并设置正确的上下文策略。本案例中的 `setenforce 0` 仅用于快速测试。
