import os
import sys

# Load .env from project root if present (do not override existing env vars)
if os.path.exists('.env'):
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)

try:
    from src.openrouter_llm import OpenRouterLLM
except Exception as e:
    print('ERROR: Failed to import OpenRouterLLM:', e)
    sys.exit(2)

api_key = os.environ.get('OPENROUTER_API_KEY')
if not api_key:
    print('ERROR: OPENROUTER_API_KEY not found in environment or .env')
    sys.exit(2)

llm = OpenRouterLLM()

try:
    prompt = [{'role': 'user', 'content': 'Please respond with a single short confirmation: \"OpenRouter reachable\".'}]
    resp = llm.call(prompt)
    print('OPENROUTER_SMOKE_RESPONSE:\n')
    print(resp)
except Exception as exc:
    print('ERROR: OpenRouter call failed:', exc)
    sys.exit(3)
