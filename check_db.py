import pymysql
conn = pymysql.connect(host='localhost', port=3306, user='root', password='123456', database='netsec_platform')
cur = conn.cursor()
cur.execute("SELECT username, LEFT(password_hash, 30) FROM users LIMIT 5")
for row in cur.fetchall():
    print(row)
conn.close()
