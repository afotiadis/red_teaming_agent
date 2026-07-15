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

## Report Archive

Every completed run is saved under `reports/` with a unique target, UTC timestamp, and random suffix, for example:

```text
reports/red_team_report_zero_health_20260714T183012_123456Z_a1b2c3d4.pdf
```

Existing reports are never overwritten. Set `REPORT_OUTPUT_DIR` to use another directory; relative paths are resolved from the repository root. The same archive behavior applies to PDF, HTML, and JSON report formats.

Report analysis and evidence are generated separately: the reporter LLM writes the concise executive, methodology, findings, and remediation sections, while Python renders every executor payload and target response deterministically. A completeness check verifies all evidence markers and required sections before a PDF can be archived.

### OpenRouter free-model configuration

- Stable free default: `openrouter/free`, which routes requests to a currently available free model.
- You may still select a specific free model with `OPENROUTER_MODEL`, but availability can change over time.

Add the following env vars to your `.env` or environment before running:

```
# Required
OPENROUTER_API_KEY=sk-or-...
LLM_BACKEND=openrouter

# Optional: pin a specific model; otherwise use the maintained free router
OPENROUTER_MODEL=openrouter/free
OPENROUTER_TEMPERATURE=0.7
LLM_MAX_TOKENS=8192
OPENROUTER_TIMEOUT=120
OPENROUTER_MAX_RETRIES=2
OPENROUTER_RETRY_BACKOFF=2
OPENROUTER_FALLBACK_MODELS=openrouter/free

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
- `LLM_MAX_TOKENS` should be set according to the task; larger outputs increase runtime and provider load.
- `OPENROUTER_MAX_RETRIES` controls bounded retries for transient HTTP failures, invalid JSON, and successful responses whose assistant content is unexpectedly null or empty.
- `OPENROUTER_FALLBACK_MODELS` is a comma-separated client-side failover chain. It is also used for HTTP 200 responses with null content, a case OpenRouter's normal server-side error fallback does not catch.
- Streaming (`stream: true`) is supported by OpenRouter; for interactive streaming reliably consider using the official OpenRouter SDK. The lightweight wrapper included in `src/openrouter_llm.py` is focused on synchronous calls.

## Switching Targets

Use `TARGET_APP` to switch the workflow from the generic chatbot path to Zero-Health without editing code.

### Zero-Health profile

```powershell
$env:TARGET_APP="zero_health"
$env:TARGET_AUTH_TOKEN="<your-zero-health-jwt>"
$env:TARGET_CHAT_URL="http://localhost:5000/api/chatbot/chat"
$env:TARGET_HEALTH_URL="http://localhost:5000/api/health"
$env:TARGET_HISTORY_URL="http://localhost:5000/api/chatbot/history"
$env:TARGET_ENHANCED_CHAT_URL="http://localhost:5000/api/chatbot/enhanced-chat"
```

Notes:
- Zero-Health uses bearer auth, so the chatbot requests must include a valid JWT in `TARGET_AUTH_TOKEN`.
- The default request body field is `message`, which matches the Zero-Health `/api/chatbot/chat` contract.
- If you want to probe the injection-friendly endpoint instead, point `TARGET_CHAT_URL` at `/api/chatbot/enhanced-chat` or set `TARGET_ENHANCED_CHAT_URL` and use it in a custom run.
- The current code sends the auth token automatically in `Authorization: Bearer ...` for the Zero-Health profile.
- When `ATTACK_STRATEGY` is unset, this target automatically uses the `zero_health` pacing profile: a 60-second read timeout, one 90-second retry for non-action prompts, and recovery cooldowns after consecutive timeouts.
- Timed-out prompts that may change state (for example scheduling, cancelling, emailing, or exporting) are not retried by default because the original request may still complete server-side. Set `ATTACK_RETRY_ACTION_PROMPTS=true` only against a disposable target where duplicate actions are acceptable.
