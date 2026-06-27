# 测试脚本目录

用于快速检测和修复部署环境中的问题。

## 脚本说明

| 脚本 | 用途 | 执行位置 |
|------|------|----------|
| `test_all_pages.py` | 检测所有路由是否返回 200 | 服务器 |
| `test_deep.py` | 深度测试 POST 交互、API、通关检测 | 服务器 |
| `reset_password.py` | 重置管理员密码 | 服务器 |
| `test_direct_port.py` | 绕过 Nginx 直连 Flask 端口测试 | 服务器 |
| `fix_nginx_rate_limit.sh` | 修复 Nginx 登录限流过大问题 | 服务器 |

## 典型用法

```bash
# 上传到服务器
scp tests/*.py root@YOUR_IP:/tmp/

# 运行全量页面检测
ssh root@YOUR_IP "python3 /tmp/test_all_pages.py"

# 运行深度交互检测
ssh root@YOUR_IP "python3 /tmp/test_deep.py"

# 重置管理员密码
ssh root@YOUR_IP "python3 /tmp/reset_password.py"

# 直连 Flask 端口排查问题（区分 Nginx/Flask）
ssh root@YOUR_IP "python3 /tmp/test_direct_port.py"
```

## 注意

- 所有 Python 脚本的 `BASE` URL 指向 `http://127.0.0.1:5100`，请确认 Flask 端口正确
- `reset_password.py` 需要 `DB_PATH` 环境变量或默认路径 `$DB_PATH`
