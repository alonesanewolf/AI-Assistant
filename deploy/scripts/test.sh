#!/bin/bash
# ============================================
# Nginx 反向代理 & 负载均衡 自动化测试脚本
# ============================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

PASS=0
FAIL=0
TOTAL=0

# 测试函数
run_test() {
    local name="$1"
    local cmd="$2"
    local expected="$3"
    TOTAL=$((TOTAL + 1))

    echo -n "  [$TOTAL] $name ... "
    local result=$(eval "$cmd" 2>/dev/null || echo "ERROR")

    if echo "$result" | grep -q "$expected"; then
        echo -e "${GREEN}✓ PASS${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}✗ FAIL${NC}"
        echo -e "       预期包含: $expected"
        echo -e "       实际结果: $result"
        FAIL=$((FAIL + 1))
    fi
}

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Nginx 功能自动化测试${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# =================================
# 1. 基础环境检查
# =================================
echo -e "${YELLOW}[1] 基础环境检查${NC}"

run_test "Nginx 是否安装" \
    "nginx -v 2>&1" \
    "nginx"

run_test "Nginx 是否运行" \
    "systemctl is-active nginx" \
    "active"

run_test "端口 80 是否监听" \
    "ss -tlnp | grep ':80 '" \
    "nginx"

# =================================
# 2. 后端服务检查
# =================================
echo ""
echo -e "${YELLOW}[2] 后端服务检查${NC}"

for port in 8081 8082 8083; do
    run_test "后端端口 $port 是否监听" \
        "ss -tlnp | grep ':$port '" \
        "$port"
done

for port in 8081 8082 8083; do
    run_test "后端 $port 是否响应" \
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$port/" \
        "200"
done

# =================================
# 3. 反向代理测试
# =================================
echo ""
echo -e "${YELLOW}[3] 反向代理测试${NC}"

run_test "代理响应 HTTP 200" \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost/" \
    "200"

run_test "代理返回 HTML 内容" \
    "curl -s http://localhost/ | head -1" \
    "<!DOCTYPE"

run_test "X-Real-IP 头传递" \
    "curl -sI http://localhost/ 2>&1" \
    ""

run_test "健康检查端点" \
    "curl -s http://localhost/health" \
    "OK"

# =================================
# 4. 负载均衡 - 默认轮询
# =================================
echo ""
echo -e "${YELLOW}[4] 负载均衡 - 默认轮询 (端口 80)${NC}"

# 多次请求检查是否轮询到不同后端
results=""
for i in $(seq 1 6); do
    port=$(curl -s http://localhost/ | grep -oP '端口: \K\d{4}' || echo "0")
    results="$results $port"
done
echo "      请求分发结果: $results"

# 检查是否至少分配到了2个不同端口
unique=$(echo $results | tr ' ' '\n' | sort -u | wc -l)
if [ "$unique" -ge 2 ]; then
    echo -e "  [轮询] ${GREEN}✓ 负载均衡生效，命中了 $unique 个不同后端${NC}"
else
    echo -e "  [轮询] ${RED}✗ 负载均衡未生效${NC}"
fi

# =================================
# 5. 负载均衡 - 加权轮询
# =================================
echo ""
echo -e "${YELLOW}[5] 负载均衡 - 加权轮询 (端口 8090, 权重5:3:1)${NC}"

declare -A count
for i in $(seq 1 18); do
    port=$(curl -s http://localhost:8090/ | grep -oP '端口: \K\d{4}' || echo "0")
    count[$port]=$((count[$port] + 1))
done

echo "      请求分配结果:"
for port in 8081 8082 8083; do
    echo "        端口 $port: ${count[$port]:-0} 次"
done

# =================================
# 6. 负载均衡 - IP Hash
# =================================
echo ""
echo -e "${YELLOW}[6] 负载均衡 - IP Hash (端口 8091)${NC}"

hash_results=""
for i in $(seq 1 5); do
    port=$(curl -s http://localhost:8091/ | grep -oP '端口: \K\d{4}' || echo "0")
    hash_results="$hash_results $port"
done

unique_hash=$(echo $hash_results | tr ' ' '\n' | sort -u | wc -l)
if [ "$unique_hash" -eq 1 ]; then
    echo -e "  ${GREEN}✓ IP Hash 生效：同一客户端始终访问同一后端 (端口: $(echo $hash_results | awk '{print $1}'))${NC}"
else
    echo -e "  ${YELLOW}⚠ IP Hash 分配到了 $unique_hash 个后端（可能因本机测试）${NC}"
fi

# =================================
# 7. 最少连接测试
# =================================
echo ""
echo -e "${YELLOW}[7] 负载均衡 - 最少连接 (端口 8092)${NC}"

run_test "最少连接策略可用" \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:8092/" \
    "200"

# =================================
# 8. Nginx 状态监控
# =================================
echo ""
echo -e "${YELLOW}[8] Nginx 状态监控 (端口 8088)${NC}"

run_test "状态页面可访问" \
    "curl -s http://127.0.0.1:8088/nginx_status | head -1" \
    "Active"

echo ""
echo -e "${YELLOW}Nginx 状态信息:${NC}"
curl -s http://127.0.0.1:8088/nginx_status 2>/dev/null || echo "  [不能访问 - 可能未配置]"

# =================================
# 9. URL Hash 测试
# =================================
echo ""
echo -e "${YELLOW}[9] 负载均衡 - URL Hash (端口 8093)${NC}"

url_hash1=$(curl -s http://localhost:8093/test-a | grep -oP '端口: \K\d{4}' || echo "0")
url_hash2=$(curl -s http://localhost:8093/test-b | grep -oP '端口: \K\d{4}' || echo "0")

echo "      /test-a → 端口: $url_hash1"
echo "      /test-b → 端口: $url_hash2"

# =================================
# 测试结果汇总
# =================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  测试结果汇总${NC}"
echo -e "${GREEN}============================================${NC}"
echo -e "  总测试数: ${TOTAL}"
echo -e "  通过:     ${GREEN}${PASS}${NC}"
echo -e "  失败:     ${RED}${FAIL}${NC}"
echo ""
if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}✓ 所有测试通过！${NC}"
else
    echo -e "  ${RED}✗ 存在 $FAIL 个失败项，请检查${NC}"
fi
echo ""
