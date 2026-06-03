#!/bin/bash
# ============================================
# 启动模拟后端服务脚本
# 用途: 在端口 8081/8082/8083 启动 Python HTTP 服务
# ============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

BACKEND_DIR="/opt/backend"
PORTS=(8081 8082 8083)

# 检查 Python 环境
check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        echo -e "${RED}[ERROR] 未找到 Python 环境，请先安装${NC}"
        echo "  yum install -y python3"
        exit 1
    fi
    echo -e "${GREEN}[OK] 使用 Python: $($PYTHON_CMD --version 2>&1)${NC}"
}

# 停止旧的后端服务
stop_old_backends() {
    echo -e "${YELLOW}[INFO] 停止已有的后端服务...${NC}"
    for port in "${PORTS[@]}"; do
        local pid=$(lsof -ti:$port 2>/dev/null || true)
        if [ -n "$pid" ]; then
            kill -9 $pid 2>/dev/null || true
            echo -e "  - 端口 $port (PID: $pid) 已停止"
        fi
    done
}

# 创建后端目录和页面
setup_backends() {
    echo -e "${BLUE}[INFO] 创建后端服务目录和页面...${NC}"
    for i in "${!PORTS[@]}"; do
        local port=${PORTS[$i]}
        local num=$((i + 1))
        local dir="${BACKEND_DIR}/server${num}"

        mkdir -p "$dir"

        # 生成带颜色的 HTML 页面
        local colors=("#667eea" "#f093fb" "#4facfe")
        local color=${colors[$i]}

        cat > "${dir}/index.html" << EOF
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>后端服务 ${num}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .card {
            background: rgba(255,255,255,0.95);
            border-radius: 20px;
            padding: 50px 60px;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            transform: translateY(-20px);
            animation: floatIn 0.6s ease-out forwards;
        }
        @keyframes floatIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(-20px); }
        }
        .server-icon { font-size: 64px; margin-bottom: 20px; }
        .server-title {
            font-size: 28px;
            font-weight: 700;
            color: #333;
            margin-bottom: 10px;
        }
        .server-badge {
            display: inline-block;
            background: ${color};
            color: white;
            padding: 8px 24px;
            border-radius: 50px;
            font-size: 18px;
            font-weight: 600;
            margin: 10px 0;
        }
        .server-info {
            color: #666;
            font-size: 14px;
            margin-top: 20px;
            line-height: 1.8;
        }
        .server-info code {
            background: #f0f0f0;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 13px;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="server-icon">🖥️</div>
        <div class="server-title">后端服务 ${num}</div>
        <div class="server-badge">端口: ${port}</div>
        <div class="server-info">
            <p>服务地址: <code>127.0.0.1:${port}</code></p>
            <p>启动时间: <code>$(date '+%Y-%m-%d %H:%M:%S')</code></p>
            <p>进程 PID: <code>$$</code></p>
        </div>
    </div>
</body>
</html>
EOF
        echo -e "  - 后端 ${num} 页面已创建: ${dir}/index.html"
    done
}

# 启动后端服务
start_backends() {
    echo -e "${BLUE}[INFO] 启动后端服务...${NC}"
    for i in "${!PORTS[@]}"; do
        local port=${PORTS[$i]}
        local num=$((i + 1))
        local dir="${BACKEND_DIR}/server${num}"

        cd "$dir"
        nohup $PYTHON_CMD -m http.server $port --bind 127.0.0.1 \
            > "${BACKEND_DIR}/server${num}.log" 2>&1 &

        local pid=$!
        sleep 0.5

        # 验证服务是否启动成功
        if kill -0 $pid 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} 后端 ${num} (端口 ${port}) 启动成功 - PID: $pid"
        else
            echo -e "  ${RED}✗${NC} 后端 ${num} (端口 ${port}) 启动失败"
        fi
    done
}

# 显示运行状态
show_status() {
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  所有后端服务已启动！${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "  ${BLUE}端口映射:${NC}"
    for i in "${!PORTS[@]}"; do
        local port=${PORTS[$i]}
        local num=$((i + 1))
        echo -e "    后端服务 ${num}: http://127.0.0.1:${port}/"
    done
    echo ""
    echo -e "  ${BLUE}Nginx 代理入口:${NC}"
    echo -e "    默认轮询:     http://localhost/"
    echo -e "    加权轮询:     http://localhost:8090/"
    echo -e "    IP Hash:      http://localhost:8091/"
    echo -e "    最少连接数:   http://localhost:8092/"
    echo -e "    URL Hash:     http://localhost:8093/"
    echo -e "    高可用:       http://localhost:8094/"
    echo -e "    状态监控:     http://localhost:8088/nginx_status"
    echo ""
    echo -e "  ${BLUE}测试命令:${NC}"
    echo -e "    curl http://localhost/"
    echo -e "    for i in \$(seq 10); do curl -s http://localhost/ | grep '端口:'; done"
    echo ""
    echo -e "  ${BLUE}停止服务:${NC}"
    echo -e "    for port in ${PORTS[*]}; do kill \$(lsof -ti:\$port) 2>/dev/null; done"
    echo ""
}

# 主流程
main() {
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  Nginx 后端模拟服务启动脚本${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""

    check_python
    stop_old_backends
    setup_backends
    start_backends
    show_status
}

main "$@"
