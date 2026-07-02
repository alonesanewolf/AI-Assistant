import sys
sys.path.insert(0, '/opt/ai_assistant/netsec')
from run import make_password_hash
import pymysql

new_hash = make_password_hash('admin123')
conn = pymysql.connect(host='localhost', port=3306, user='root', password='123456', database='netsec_platform')
cur = conn.cursor()
cur.execute("UPDATE users SET password_hash=%s WHERE username='admin'", (new_hash,))
conn.commit()
print('admin password reset to: admin123')
conn.close()
