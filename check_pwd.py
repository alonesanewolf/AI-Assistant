import pymysql
import hashlib

db = pymysql.connect(host='127.0.0.1', user='root', password='123456', database='netsec_platform')
cur = db.cursor()

# 先看表结构
cur.execute("DESCRIBE users")
cols = cur.fetchall()
print("=== users 表结构 ===")
for c in cols:
    print(f"  {c[0]} ({c[1]})")

# 查看所有用户
cols_list = [c[0] for c in cols]
if 'id' in cols_list and 'username' in cols_list:
    cur.execute("SELECT id, username FROM users")
    users = cur.fetchall()
    print("\n=== 用户列表 ===")
    for u in users:
        print(f"  id={u[0]}, username={u[1]}")
    
    # 重置 admin 密码 - 先看用的什么加密
    from werkzeug.security import generate_password_hash, check_password_hash
    h = generate_password_hash('admin123')
    
    # 直接用 werkzeug 重置
    cur.execute("UPDATE users SET password_hash=%s WHERE username=%s", (h, 'admin'))
    affected = cur.rowcount
    db.commit()
    print(f"\n=== 密码重置: {affected} 行更新 ===")
    print(f"admin 密码已重置为: admin123")
    print(f"hash: {h}")

db.close()
