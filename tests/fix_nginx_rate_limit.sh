#!/bin/bash
# 修复 Nginx 登录限流问题
# 问题: rate=5r/m 太小，频繁登录/登出触发 503
# 用法: bash fix_nginx_rate_limit.sh

CONFIG_FILE="/etc/nginx/conf.d/ai_assistant.conf"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "错误: 找不到配置文件 $CONFIG_FILE"
    echo "请手动修改 Nginx conf 中的 rate 参数"
    exit 1
fi

# 备份
BACKUP="${CONFIG_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP"
echo "已备份到: $BACKUP"

# 修改限流参数
sed -i 's/rate=5r\/m/rate=30r\/m/g' "$CONFIG_FILE"
sed -i 's/burst=3/burst=10/g' "$CONFIG_FILE"

# 显示修改后的限流配置
echo "修改后的限流配置:"
grep -n 'limit_req_zone\|limit_req\b' "$CONFIG_FILE"

# 检查语法
if nginx -t; then
    systemctl reload nginx
    echo "Nginx 已重载"
else
    echo "Nginx 配置语法错误，正在恢复备份..."
    cp "$BACKUP" "$CONFIG_FILE"
    nginx -t && systemctl reload nginx
    echo "已恢复原始配置"
    exit 1
fi

echo "完成!"
