import os
import sys

# Load .env if present
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

# Skip heavy RAG initialization during this smoke test
os.environ['SKIP_RAG_INIT'] = '1'

# Ensure project root is importable
sys.path.insert(0, '.')

try:
    from src.agents import RedTeamingAgents
except Exception as e:
    print('ERROR: Failed to import RedTeamingAgents:', e)
    sys.exit(2)

agents = RedTeamingAgents()
planner = agents.planner_agent()

# Use the agent's llm directly for a quick smoke prompt to avoid full Crew execution.
prompt = [{'role': 'system', 'content': 'You are a concise red-team planner.'},
          {'role': 'user', 'content': 'Given the target: "A local python codebase in ./target_app using Ollama", produce a one-line JSON plan naming a single tool to run and a short prompt.'}]

try:
    resp = planner.llm.call(prompt)
    print('PLANNER_SMOKE_RESPONSE:\n')
    print(resp)
except Exception as exc:
    print('ERROR: Planner LLM call failed:', exc)
    sys.exit(3)
