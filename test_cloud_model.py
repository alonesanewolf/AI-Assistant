import sys
sys.stdout.reconfigure(encoding='utf-8')
from model_router import ModelRouter

print("Testing cloud_only...")
r = ModelRouter(mode='cloud_only')
result = r.chat(messages=[{'role': 'user', 'content': 'hi'}], max_tokens=20)
print('success:', result.get('success'))
print('model:', result.get('model'))
print('source:', result.get('source'))
print('content:', result.get('content', '')[:100])

print("\nTesting cloud_first...")
r = ModelRouter(mode='cloud_first')
result = r.chat(messages=[{'role': 'user', 'content': 'hi'}], max_tokens=20)
print('success:', result.get('success'))
print('model:', result.get('model'))
print('source:', result.get('source'))
print('content:', result.get('content', '')[:100])
