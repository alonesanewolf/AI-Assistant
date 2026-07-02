import sys, os
sys.path.insert(0, '/opt/ai_assistant/netsec')
os.chdir('/opt/ai_assistant/netsec')

import run
run.app.config['TESTING'] = True
run.app.config['SERVER_NAME'] = None

client = run.app.test_client()

with run.app.app_context():
    # 模拟登录
    with client.session_transaction() as sess:
        sess['user'] = 'admin_test'
        sess['user_id'] = 1
        sess['username'] = 'admin_test'
        sess['role'] = 'admin'
        sess['role_key'] = 'admin'

    # 调用 AI 攻防接口
    resp = client.post('/api/ai-attack/chat',
        json={'message': 'hi 介绍一下你自己', 'session_id': 'test_final', 'target': ''})
    
    print('status:', resp.status_code)
    data = resp.get_json()
    if data:
        print('success:', data.get('success'))
        print('model:', data.get('model'))
        print('fallback:', data.get('fallback'))
        print('reply:', data.get('reply', '')[:200])
    else:
        print('NO JSON. Raw:', resp.get_data(as_text=True)[:500])
