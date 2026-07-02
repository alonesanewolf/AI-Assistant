import sys
sys.path.insert(0, '/opt/ai_assistant/netsec')

# Test that the import works
import run
from model_router import ModelRouter
r = ModelRouter(mode='cloud_only')
result = r.chat(messages=[{'role': 'user', 'content': 'hi'}], max_tokens=15)
print('model import OK')
print('success:', result.get('success'))
print('model:', result.get('model'))
print('content:', result.get('content', '')[:100])

# Test from run.py's perspective
run.model_router = __import__('model_router')
print('run.py can import model_router:', hasattr(run, 'model_router'))
