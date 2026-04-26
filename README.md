# red_teaming_agent

## Quick Start

1. Set the required environment variables:

```powershell
$env:ARIADNE_API_TOKEN="your-token"
$env:TARGET_PROMPT="A local python codebase in ./target_app using Ollama"
$env:TARGET_CHAT_URL="http://127.0.0.1:8000/chat"
```

2. Start the vulnerable chatbot in one terminal:

```powershell
python target_app/vulnerable_chatbot.py
```

3. Run the crew in another terminal:

```powershell
python main.py --target "A local python codebase in ./target_app using Ollama"
```

## Notes

- `TARGET_CHAT_URL` is shared by the attack tools and the target app should be reachable there.
- The crew currently uses the Promptfoo path as the stable execution route.
- If you want to change the Ollama model or host/port for the chatbot, set `OLLAMA_MODEL`, `TARGET_HOST`, and `TARGET_PORT` before starting the target app.