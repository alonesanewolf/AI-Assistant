import sys
sys.path.insert(0, '/opt/ai_assistant')
sys.path.insert(0, '/opt/ai_assistant/netsec')
import model_router
print('model_router file:', model_router.__file__)
print('DEEPSEEK_API_KEY:', model_router.DEEPSEEK_API_KEY[:15] + '...')
