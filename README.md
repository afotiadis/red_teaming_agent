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

## Switching LLM Backend

- To use OpenRouter (recommended for temporary Ariadne outages), set the API key and backend:

```powershell
$env:OPENROUTER_API_KEY="your-openrouter-key"
$env:LLM_BACKEND="openrouter"
```

- To revert to Ariadne later (keeps the Ariadne code in place but deactivated by default):

```powershell
$env:ARIADNE_API_TOKEN="your-ariadne-token"
$env:LLM_BACKEND="ariadne"
```

The code selects the LLM implementation at runtime based on `LLM_BACKEND`. Ariadne's implementation is preserved in `src/ariadne_llm.py` but will not be used unless `LLM_BACKEND` is set to `ariadne`.

### OpenRouter `gpt-oss-120b` (free) recommendations

- Recommended model slug: `openai/gpt-oss-120b:free` (this is the default used by the code).
- This model supports very large context windows (up to ~131k tokens) and configurable reasoning.

Add the following env vars to your `.env` or environment before running:

```
# Required
OPENROUTER_API_KEY=sk-or-...
LLM_BACKEND=openrouter

# Optional but recommended for gpt-oss-120b
OPENROUTER_MODEL=openai/gpt-oss-120b:free
OPENROUTER_TEMPERATURE=0.7
LLM_MAX_TOKENS=8192
OPENROUTER_TIMEOUT=120

# Reasoning controls (enable if you want chain-of-thought / internal reasoning)
OPENROUTER_REASONING_ENABLED=true
OPENROUTER_REASONING_EFFORT=medium   # low|medium|high
OPENROUTER_REASONING_MAX_TOKENS=2000

# Optional headers to help OpenRouter attribute traffic
OPENROUTER_HTTP_REFERER=https://your.app
OPENROUTER_X_TITLE=MyRedTeamTool
```

Notes:
- If you enable `OPENROUTER_REASONING_ENABLED`, the wrapper will request reasoning tokens and the model may spend more internal compute before producing the final answer. This can increase latency but improve problem-solving for hard puzzles.
- `LLM_MAX_TOKENS` should be set according to the task; `gpt-oss-120b` supports very long outputs but this increases runtime and memory usage on the provider side.
- Streaming (`stream: true`) is supported by OpenRouter; for interactive streaming reliably consider using the official OpenRouter SDK. The lightweight wrapper included in `src/openrouter_llm.py` is focused on synchronous calls.