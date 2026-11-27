# red_teaming_agent

A CrewAI-based framework for testing AI chat applications. It plans attack prompts, sends them to a configured target, analyzes the responses, and saves a report with the execution evidence.

## Prerequisites

- **Python 3.12**, including `pip` and `venv`, for the commands below.
- **Git** to clone this repository and, optionally, documentation sources.
- **An LLM API credential**: an OpenRouter API key for the default backend, or an Ariadne API token. This powers the red-teaming agents.
- **A running target application**. The local walkthrough below uses the bundled FastAPI chatbot, which also requires **Ollama** and the `llama3.2:1b` model. Ollama powers the target chatbot; it does not replace the agents' API backend.
- **Internet access** to install dependencies, call the selected API backend, and download the Ollama model. Optional knowledge ingestion also downloads documentation and an embedding model.

Node.js and the Promptfoo CLI are optional: the default executor sends HTTP requests directly from Python.

## Installation

### Windows (PowerShell)

```powershell
git clone https://github.com/afotiadis/red_teaming_agent.git
cd red_teaming_agent
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
$env:PYTHONUTF8="1"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks the activation script, use `.\venv\Scripts\python.exe` in place of `python` in subsequent commands. Run all commands from the repository root.

### macOS / Linux (bash or zsh)

```bash
git clone https://github.com/afotiadis/red_teaming_agent.git
cd red_teaming_agent
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you already have a checkout, start by opening its root directory and creating or activating the virtual environment. Dependencies are currently unpinned in `requirements.txt`; there is no lockfile.

## Configure the environment

Copy the example configuration once. If `.env` already exists, edit it instead of overwriting it.

```powershell
# Windows
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

For the bundled chatbot walkthrough, edit `.env` so it contains these values, replacing the API key placeholder:

```dotenv
LLM_BACKEND=openrouter
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_MODEL=openrouter/free
LLM_MAX_TOKENS=8192
TARGET_APP=generic
USE_PROMPTFOO=0
```

The copied `.env.example` selects `TARGET_APP=vulnerable_chat`, which is a separate application on port 5000. Change it to `generic` to use `target_app/vulnerable_chatbot.py` on port 8000. The generic profile supplies `http://127.0.0.1:8000/chat` and `/health`; no target authentication token is needed.

`main.py` loads `.env` automatically. Variables already exported in your shell take precedence, and explicit `TARGET_CHAT_URL` / `TARGET_HEALTH_URL` values override the selected profile. Remove stale target overrides when switching applications. Keep credentials in `.env`, which is ignored by Git.

Use `LLM_BACKEND` to choose between `openrouter` and `ariadne`; the `LLM_PROVIDER` variable shown in `.env.template` does not select the runtime backend.

## Run with the bundled chatbot

### 1. Start Ollama and download the target model

Install Ollama and ensure its server is running at `http://localhost:11434`. If it is not already running through the desktop application or a service, start it in a terminal and leave that terminal open:

```text
ollama serve
```

In another terminal, download the model and confirm it is available:

```text
ollama pull llama3.2:1b
ollama list
```

### 2. Start the target chatbot

Open a terminal at the repository root, activate the virtual environment, and start the target. Leave it running while the campaign executes.

```powershell
# Windows PowerShell
.\venv\Scripts\Activate.ps1
$env:PYTHONUTF8="1"
$env:OLLAMA_MODEL="llama3.2:1b"
$env:TARGET_HOST="127.0.0.1"
$env:TARGET_PORT="8000"
python target_app/vulnerable_chatbot.py
```

```bash
# macOS / Linux
source venv/bin/activate
export OLLAMA_MODEL=llama3.2:1b
export TARGET_HOST=127.0.0.1
export TARGET_PORT=8000
python target_app/vulnerable_chatbot.py
```

The target script reads its settings from the process environment and does **not** load `.env`. Export target-specific settings in this terminal, as shown above. `TARGET_HOST` and `TARGET_PORT` control where the target listens; changing them also requires updating the crew's `TARGET_BASE_URL` in `.env`.

### 3. Check the target and run the crew

Open a second terminal at the repository root and activate the same virtual environment:

```powershell
# Windows PowerShell
.\venv\Scripts\Activate.ps1
$env:PYTHONUTF8="1"
Invoke-RestMethod http://127.0.0.1:8000/health
python main.py
```

```bash
# macOS / Linux
source venv/bin/activate
curl --fail http://127.0.0.1:8000/health
python main.py
```

The health endpoint should return `{"status":"ok"}`. It confirms that FastAPI is reachable; Ollama must also be running with the requested model for chat responses to work. The crew checks the configured API credential and target health before starting, then plans, executes, and analyzes prompts over multiple rounds before generating a report.

The selected profile supplies a target description. To provide a more specific description, use:

```text
python main.py --target "The bundled IT-support chatbot in ./target_app using Ollama"
```

`--target` changes the planner's description; connection details still come from the target profile and environment variables. `TARGET_PROMPT` is another way to supply a description. The default campaign budget is five rounds; set `MAX_ATTACK_ROUNDS` to change it. Stop the local target with `Ctrl+C` when finished.

## Switching LLM backend

OpenRouter is the default. To use Ariadne, change these values in `.env`:

```dotenv
LLM_BACKEND=ariadne
ARIADNE_API_TOKEN=your-ariadne-token
```

To switch back, set `LLM_BACKEND=openrouter` and provide `OPENROUTER_API_KEY`. Only the selected backend's credential is required. Neither backend requires `OPENAI_API_KEY` for the standard workflow.

### OpenRouter options

The wrapper defaults to `openrouter/free`. Set `OPENROUTER_MODEL` to select another model available to your account. Optional settings include:

```dotenv
OPENROUTER_TEMPERATURE=0.7
LLM_MAX_TOKENS=8192
OPENROUTER_TIMEOUT=120
OPENROUTER_MAX_RETRIES=2
OPENROUTER_RETRY_BACKOFF=2
OPENROUTER_FALLBACK_MODELS=openrouter/free

# Optional reasoning controls; support depends on the selected model
OPENROUTER_REASONING_ENABLED=true
OPENROUTER_REASONING_EFFORT=medium
OPENROUTER_REASONING_MAX_TOKENS=2000

# Optional attribution headers
OPENROUTER_HTTP_REFERER=https://your.app
OPENROUTER_X_TITLE=MyRedTeamTool
```

`OPENROUTER_MAX_RETRIES` bounds retries for transient HTTP failures, invalid JSON, and empty assistant content. `OPENROUTER_FALLBACK_MODELS` is a comma-separated client-side failover chain, including for HTTP 200 responses with empty content. Larger token budgets and reasoning requests can increase runtime.

## Switching targets

Set `TARGET_APP` in `.env` to select an HTTP contract. The profile supplies chat and health URLs, the request field, authentication requirements, and attack pacing. The four validation applications are separate projects: install and start the selected application using its own instructions before running `python main.py`.

| `TARGET_APP` | Default chat endpoint | Health path | Payload | Authentication |
|---|---|---|---|---|
| `generic` | `http://127.0.0.1:8000/chat` | `/health` | `{"message": ...}` | None |
| `zero_health` | `http://localhost:5000/api/chatbot/chat` | `/api/health` | `{"message": ...}` | Bearer JWT required |
| `dvaia` | `http://localhost:5000/api/agent/chat` | `/api/health` | `{"prompt": ...}` | None |
| `vuln_bank` | `http://localhost:5000/api/ai/chat` | `/healthz` | `{"message": ...}` | Bearer JWT required |
| `vulnerable_chat` | `http://localhost:5000/api/chat` | `/health` | `{"message": ...}` | None |

All four external profiles default to port 5000, so run only the selected application or map it to another port. Ollama is needed for the bundled target; external targets have their own model and service requirements.

For example, to select Zero-Health, obtain a JWT from that application's authentication flow and set:

```dotenv
TARGET_APP=zero_health
TARGET_AUTH_TOKEN=your-zero-health-jwt
```

Use the raw JWT as `TARGET_AUTH_TOKEN`; the profile adds the `Bearer` prefix. Vuln-Bank also requires a target JWT. This credential is separate from the red-team LLM API key.

Use `TARGET_BASE_URL` to change the host or port while retaining the profile paths, for example `TARGET_BASE_URL=http://localhost:5100`. For custom routes, set `TARGET_CHAT_URL` and `TARGET_HEALTH_URL` explicitly. `TARGET_REQUEST_FIELD`, `TARGET_REQUEST_FORMAT`, and the authentication overrides support custom request contracts.

Alternate routes include DVAIA's simpler `/api/chat` and Zero-Health's `/api/chatbot/enhanced-chat`. To use Vuln-Bank's anonymous `/api/ai/chat/anonymous` route without a JWT, set `TARGET_CHAT_URL` to that full URL, `TARGET_AUTH_MODE=none`, and `TARGET_AUTH_REQUIRED=false`.

Timed-out prompts that may change state are not retried by default because the original request may still complete server-side. `ATTACK_RETRY_ACTION_PROMPTS=true` enables those retries for disposable targets where duplicate actions are acceptable.

## Optional: build the documentation knowledge base

Knowledge ingestion is not required to run `main.py`. The standard campaign uses the target dossiers and playbooks in `config/`; the retrieval tool can fall back to keyword search over local documents when Chroma is unavailable.

To build the optional semantic-search database, activate the virtual environment, review [config/knowledge_sources.json](config/knowledge_sources.json), and run from the repository root:

```text
python ingest_knowledge.py
```

The script clones enabled documentation repositories into `data/repos/`, loads configured local documents, downloads the embedding model (default: `all-MiniLM-L6-v2`), and builds `chroma_db/`. It replaces any existing database at `KNOWLEDGE_BASE_PATH`. Only the cloned documentation copies are filtered; configure ingestion sources before running if you want a smaller corpus.

`SERPER_API_KEY` is optional and enables web search and scraping during ingestion. Remove its placeholder from the copied `.env.example`, or leave the value empty, to skip that step. Use `KNOWLEDGE_BASE_PATH`, `EMBEDDING_MODEL`, `CHUNK_SIZE`, and `CHUNK_OVERLAP` to customize ingestion. Set `SKIP_RAG_INIT=1` to skip loading the vector database during lightweight runs.

## Optional: use the Promptfoo CLI

Despite the executor's `execute_promptfoo_attack` name, `USE_PROMPTFOO=0` uses direct Python HTTP requests and needs no Node.js installation. To use the external CLI, install Node.js and npm, then install Promptfoo and verify that it is on your `PATH`:

```text
npm install -g promptfoo
promptfoo --version
```

Set `USE_PROMPTFOO=1` in `.env` before running `python main.py`. The executor generates a temporary configuration and invokes `promptfoo eval`.

## Reports and saved state

Every completed run is saved under `reports/` with a unique target, UTC timestamp, and random suffix, for example:

```text
reports/red_team_report_generic_20260714T183012_123456Z_a1b2c3d4.pdf
```

Existing reports are never overwritten. Set `REPORT_OUTPUT_DIR` to use another directory; relative paths are resolved from the repository root. `REPORT_FORMAT` selects `pdf_default` (default), `html_debug`, or `json_structured`.

The reporter LLM writes the analytical sections, while Python renders every executor payload and target response. A completeness check verifies the evidence markers and required sections before archiving the report.

Planner history and coverage are stored in `planner_state.json` and `planner_state.json.cov`. Set `PLANNER_STATE_PATH` to a new filename to start with separate state, particularly when changing targets.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `ModuleNotFoundError` | Activate the virtual environment in this terminal and install `requirements.txt` using that environment's Python. |
| `UnicodeEncodeError` on Windows | Set `$env:PYTHONUTF8="1"` before launching Python, or run `python -X utf8 main.py`. |
| Missing API credential | Supply the key for the selected `LLM_BACKEND`; placeholder values must be replaced. |
| Target is not reachable / health check fails | Start the selected application, verify its health URL, and remove stale URL overrides. The bundled target uses `generic` on port 8000. |
| Target health is OK but chat returns an Ollama error | Ensure Ollama is running and `ollama list` contains the exact `OLLAMA_MODEL` configured in the target's terminal. |
| Target returns HTTP 401 or 403 | Obtain a valid target JWT and set `TARGET_AUTH_TOKEN` for the authenticated profile. |
| LLM request fails or returns empty content | Check API access, model availability, and provider limits; adjust the model, timeout, retries, or fallback chain. |
| Missing Chroma database | Ingestion is optional. Run `python ingest_knowledge.py` if you need semantic retrieval, or use `SKIP_RAG_INIT=1`. |

For workflow details, see [docs/WORKFLOW.md](docs/WORKFLOW.md). Runtime target contracts are defined in [src/target_profiles.py](src/target_profiles.py), and pacing profiles are in [config/attack_strategies.json](config/attack_strategies.json).
