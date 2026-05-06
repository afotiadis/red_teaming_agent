# Red-Teaming Agent — End-to-End Workflow

Last updated: 2026-05-06

This document explains the red-teaming pipeline implemented in this repository and describes the full, configurable workflow from start to finish. It covers architecture, configuration, key files, agent flows, tools, run examples, troubleshooting, and recommended next steps.

**Purpose**: provide a target-agnostic, configurable red-teaming pipeline that performs automated reconnaissance, plans attacks using RAG and an LLM, executes non-destructive probes or attacks via modular tools, and generates structured reports.

---

**Architecture Overview**

- **Planner → Executor → Reporter**: a sequential CrewAI crew implemented in `main.py` that runs three agents in order: planner (designs attack_spec), executor (runs tools per attack_spec), reporter (compiles results into a human-friendly report).
- **RAG Retriever**: a Chroma vector store seeded by `ingest_knowledge.py` (configurable) to ground planner reasoning.
- **LLM Adapter**: `src/ariadne_llm.py` provides an Ariadne-compatible wrapper; connection parameters are environment-configurable so other adapters can be added.
- **Tools**: `src/tools.py` contains all Crew tools — discovery, inference, RAG retriever, Promptfoo integration, and request helpers.
- **Target App**: `target_app/vulnerable_chatbot.py` is a sample FastAPI target used for development and testing.

Diagram (high-level):

```mermaid
flowchart LR
  A[Start: main.py CLI] --> B[validate_runtime & env checks]
  B --> C[Planner Agent]
  C --> D[Discovery tools + RAG]
  D --> E[Attack spec (JSON)]
  E --> F[Executor Agent]
  F --> G[Tool calls / Promptfoo / network probes]
  G --> H[Execution output]
  H --> I[Reporter Agent]
  I --> J[Final report: PDF/HTML/JSON]
```

---

**Key Files (where to look / edit)**

- Agent orchestration: [main.py](main.py)
- Agents: [src/agents.py](src/agents.py)
- Tasks / agent prompts: [src/tasks.py](src/tasks.py)
- Tools (discovery, request builders, RAG): [src/tools.py](src/tools.py)
- LLM adapter: [src/ariadne_llm.py](src/ariadne_llm.py)
- Knowledge ingestion: [ingest_knowledge.py](ingest_knowledge.py)
- Example target: [target_app/vulnerable_chatbot.py](target_app/vulnerable_chatbot.py)
- Config templates and docs: [.env.template](.env.template), [config/agent_profiles.json](config/agent_profiles.json), [config/attack_strategies.json](config/attack_strategies.json), [config/knowledge_sources.json](config/knowledge_sources.json)

---

**Environment & Configuration**

The pipeline is driven by environment variables (see `.env.template`). Minimal variables to run a local test:

- `ARIADNE_API_TOKEN` — required for Ariadne LLM calls
- `TARGET_CHAT_URL` — target endpoint URL (optional for local target tests)
- `KNOWLEDGE_BASE_PATH` — where Chroma DB is stored (used by `ingest_knowledge.py` and the RAG retriever)

Major configurable variables (summarized):

- `ARIADNE_BASE_URL`, `ARIADNE_PROVIDER`, `LLM_MAX_TOKENS`, `ARIADNE_TIMEOUT` — LLM adapter settings in `src/ariadne_llm.py`.
- `TARGET_REQUEST_FORMAT` — controls how request bodies are built (supported: `json_message`, `json_query`, `json_input`, `json_prompt`, `plain_text`). See `src/tools.py` `_build_request_payload` for exact formats.
- `EMBEDDING_MODEL` — embedding model for vector DB (used by `ingest_knowledge.py` and RAG retriever).
- `VERBOSE` — agent verbosity toggle (controls extra logging in `src/agents.py`).
- `REPORT_FORMAT` — choose output format for final report: `pdf`, `html`, or `json` (implemented in `main.py`).

Where to edit persistent profiles and strategies:

- Agent profiles and role/backstory: `config/agent_profiles.json` — define or tune agent personas.
- Attack pacing & request strategies: `config/attack_strategies.json` — used by Promptfoo integration.
- Knowledge sources for ingestion: `config/knowledge_sources.json` — feeds `ingest_knowledge.py`.

---

**Detailed Flow: Planner → Executor → Reporter**

1) Startup (`main.py`)
  - Loads environment variables (via `dotenv` if present) and validates runtime keys (e.g., `ARIADNE_API_TOKEN`).
  - Optionally checks target health if `TARGET_CHAT_URL` is set.
  - Assembles Crew (planner, executor, reporter) using `src/agents.py`.

2) Planner (`src/agents.py` / `src/tasks.py`)
  - The planner is given a structured task from `src/tasks.py` (function `plan_attack`): perform discovery, consult RAG`, and return a strict JSON `attack_spec` describing what to run.
  - Discovery sequence (invoked by the planner) includes the tools:
    - `discover_target_surface` — surface endpoints, parameters, common resources.
    - `infer_target_schema` — infer expected request/response shapes.
    - `analyze_target_behavior` — detect likely validation or auth behaviors.
    - `scan_target_misconfigurations` — optional, non-destructive checks for common misconfigurations.
  - Planner then queries the RAG retriever tool (Chroma) to ground strategies with documentation and known patterns.
  - Output: `attack_spec` JSON with fields such as `strategy`, `tool` (which tool to call), `prompts_text` (pipe-delimited), `notes`, and optional `metadata`.

3) Executor
  - The executor reads the `attack_spec` and maps `tool` values to functions in `src/tools.py`.
  - Executor expects the planner to produce well-formed JSON. (Recommendation: add jsonschema validation in the executor stage for production; see "Next steps" below.)
  - The executor uses request helper functions in `src/tools.py`:
    - `_build_request_payload(prompt)` — builds body according to `TARGET_REQUEST_FORMAT`.
    - `_build_request_kwargs(prompt)` — builds `requests` kwargs (`json` vs `data`, headers).
  - For Promptfoo/Prompt-based attacks, the executor calls `promptfoo_tool` which will craft requests respecting the chosen attack pacing (`config/attack_strategies.json`).
  - Tools must return string outputs (CrewAI constraint); the executor captures raw responses and stores them for reporting.

4) Reporter
  - The reporter collates planner notes, discovery output, execution logs, and responses.
  - `main.py` supports exporting reports in multiple formats; the reporter writes a Markdown summary which is then converted to PDF/HTML if requested.

---

**RAG Ingestion & Retriever**

- Use `ingest_knowledge.py` to build the Chroma DB. The script reads `config/knowledge_sources.json` by default and can be parameterized by env variables for chunk sizes and embedding model.
- The RAG retriever in `src/tools.py` uses `HuggingFaceEmbeddings` (model name from `EMBEDDING_MODEL`) and opens the DB at `KNOWLEDGE_BASE_PATH`.
- If the vector DB is missing, the retriever tool returns a helpful fallback message rather than failing hard.

---

**LLM Adapter / Ariadne**

- `src/ariadne_llm.py` wraps the Ariadne API. Configure `ARIADNE_BASE_URL`, `ARIADNE_PROVIDER`, `ARIADNE_API_TOKEN`, `LLM_MAX_TOKENS`, and `ARIADNE_TIMEOUT` in the environment.
- The adapter supports provider-specific payloads and enforces timeouts and max tokens to avoid runaway calls.

---

**Request Payload Formats (supported)**

- `json_message`: {"message": "<prompt>"}
- `json_query`: {"query": "<prompt>"}
- `json_input`: {"input": "<prompt>"}
- `json_prompt`: {"prompt": "<prompt>"}
- `plain_text`: raw text in the request body

These formats are implemented in `src/tools.py` `_build_request_payload`. Update `TARGET_REQUEST_FORMAT` in `.env` or export as env var to adapt to a target's contract.

---

**Agent Profiles & Tuning**

- Edit `config/agent_profiles.json` to change planner/executor/reporter backstories, goals, and instruction styles.
- Toggle `VERBOSE=true` in env to get more debugging output from `src/agents.py` during runs.

---

**Execution Examples**

1) Run the sample target locally (in one terminal):

```bash
python -m target_app.vulnerable_chatbot
```

2) Run the pipeline (in another terminal) with minimal env (example using PowerShell):

```powershell
$env:ARIADNE_API_TOKEN = 'your-token'
$env:TARGET_CHAT_URL = 'http://localhost:8000/chat'
python main.py
```

3) Build the vector DB from repositories and sources:

```bash
python ingest_knowledge.py --output-path chroma_db
```

Notes:
- Use `.env.template` as a reference; copy to `.env` and edit.

---

**Troubleshooting & Common Issues**

- Missing `ARIADNE_API_TOKEN`: `main.py` will refuse to run; add token to env or `.env`.
- RAG retriever empty DB: run `ingest_knowledge.py`; retriever will provide a safe fallback message.
- Planner JSON invalid: executor may fail — add schema validation (recommended). See "Next steps".
- Target contract mismatch: set `TARGET_REQUEST_FORMAT` appropriately or update `_build_request_payload` if you need a custom contract.

---

**Security & Safety Notes**

- Discovery tools are implemented to be non-destructive by default. Avoid enabling destructive scanning tools unless you have explicit authorization to test the target.
- Keep secrets out of VCS; use `.env` or a secret manager.

---

**Next Steps & Recommendations**

1. Add JSON Schema validation in the executor to enforce `attack_spec` structure (use `jsonschema`).
2. Implement adapters for OpenAI and Ollama in addition to Ariadne to support multi-provider redundancy.
3. Add unit and integration tests for the planner → executor contract.
4. Add CI checks to build the vector DB and run a dry-run of the agents against the local `vulnerable_chatbot` in a sandboxed environment.

---

If you want, I can also:

- Export this file to PDF and place it at `docs/WORKFLOW.pdf`.
- Add a `jsonschema` file to `config/` and wire runtime validation into the executor.
- Create a small `README_RUN.md` with copy-paste commands for common workflows.

---

End of document.
