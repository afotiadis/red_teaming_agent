# Hardcoded Components: Quick Reference

## Critical Issues (Fix First)

### 1. TARGET URL HARDCODING
| Severity | Files | Impact |
|----------|-------|--------|
| 🔴 Critical | main.py, src/tools.py | Cannot target anything except `http://127.0.0.1:8000/chat` |

**Current:**
```python
TARGET_CHAT_URL = os.getenv("TARGET_CHAT_URL", "http://127.0.0.1:8000/chat")
```

**Why it matters:** Your planner makes a strategy, but executor blindly assumes:
- Target is at localhost:8000
- Chat endpoint is `/chat` (not `/api/chat`, `/messages`, etc.)
- Request format is `{"message": prompt}`

If target expects different format → attacks fail silently.

**Fix:** See Section 1.1 in HARDCODED_ANALYSIS.md

---

### 2. LLM PROVIDER LOCKED TO ARIADNE
| Severity | File | Impact |
|----------|------|--------|
| 🔴 Critical | src/ariadne_llm.py | Cannot use OpenAI, Ollama, Anthropic, or other LLMs |

**Current:**
```python
self.base_url = "https://ariadne.issel.ee.auth.gr/api"
self.provider = "gcp"
```

**Why it matters:** If Ariadne becomes unavailable or you want to test with cheaper/different models, entire system breaks.

**Fix:** See Section 1.2 in HARDCODED_ANALYSIS.md

---

### 3. DATABASE PATH NOT ABSOLUTE
| Severity | Files | Impact |
|----------|-------|--------|
| 🔴 Critical | src/tools.py, ingest_knowledge.py | Cannot run from different directories; breaks concurrent sessions |

**Current:**
```python
if os.path.exists("chroma_db"):
    vector_store = Chroma(persist_directory="chroma_db", ...)
```

**Why it matters:** 
- Running from `project/scripts/` will look for `project/scripts/chroma_db` instead of `project/chroma_db`
- Can't run multiple concurrent red-teaming sessions
- Can't organize knowledge bases by target type

**Fix:** See Section 1.3 in HARDCODED_ANALYSIS.md

---

### 4. AGENT ROLES/GOALS/BACKSTORIES HARDCODED
| Severity | Files | Impact |
|----------|-------|--------|
| 🔴 Critical | src/agents.py, src/tasks.py | Cannot adapt to different attack methodologies or targets |

**Current:**
```python
Agent(
    role='Red Teaming Strategist',
    goal='Analyze the target description, consult the RAG knowledge base, ...',
    backstory="You are an expert AI security researcher. ...",
)
```

**Why it matters:** If you want to test for different vulnerabilities (e.g., data exfiltration vs. jailbreak), agent personality must change. Currently locked to one attack style.

**Fix:** See Section 1.4 in HARDCODED_ANALYSIS.md (use YAML profiles)

---

### 5. HTTP REQUEST FORMAT HARDCODED
| Severity | File | Impact |
|----------|------|--------|
| 🔴 Critical | src/tools.py | Only works with `{"message": p}` format |

**Current:**
```python
payload = {"message": p}  # ← hardcoded
```

**Why it matters:** Targets use different field names:
- `{"query": p}` (search-oriented APIs)
- `{"input": p}` (LangChain agents)
- `{"prompt": p}` (model serving endpoints)
- `{"text": p}` (some custom implementations)

Different format = zero exploitation capability.

**Fix:** See Section 1.1 in HARDCODED_ANALYSIS.md

---

## Medium-Priority Issues (Fix Next)

### 6. TIMING PARAMETERS SCATTERED
- `INTER_PROMPT_DELAY = "0.5"` (0.5s too fast for remote targets)
- `ATTACK_REQUEST_TIMEOUT = "15"` (15s too short for slow APIs)
- `ATTACK_JOB_TIMEOUT = "120"` (2 min too short for batch processing)

→ **Fix:** Move to YAML strategy profiles (local_fast, remote_api, rate_limited)

### 7. JSON ATTACK SPEC SCHEMA HARDCODED
Currently inline in task description; needs JSON schema validation file.

→ **Fix:** Create `config/attack_spec_schema.json`

### 8. REPOSITORY URLS HARDCODED
```python
REPOSITORIES = {
    "promptfoo": "https://github.com/promptfoo/promptfoo.git",
    "pyrit": "https://github.com/Azure/PyRIT.git",
    "agentic-radar": "https://github.com/splx-ai/agentic-radar.git"
}
```

Can't add custom knowledge bases without editing code.

→ **Fix:** Move to `config/knowledge_sources.yaml`

### 9. EMBEDDING MODEL HARDCODED
```python
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
```

Small model; larger models might capture domain-specific attack patterns better.

→ **Fix:** Support `all-mpnet-base-v2`, `OpenAI`, `Cohere` providers

### 10. PDF REPORT GENERATION HARDCODED
Only PDF output; no HTML or JSON export options.

→ **Fix:** Create `config/report_templates.yaml` for multiple formats

---

## Low-Priority Issues (Nice-to-Have)

| Issue | Current | Fix |
|-------|---------|-----|
| Verbose logging always on | `verbose=True` | Use env var `VERBOSE=true\|false` |
| Max tokens fixed | `max_tokens: 4096` | Env var `LLM_MAX_TOKENS=4096` |
| Temperature fixed | `temperature: 0.7` | Env var `LLM_TEMPERATURE=0.7` |
| Chunk size fixed | `chunk_size=1000` | Env vars `CHUNK_SIZE`, `CHUNK_OVERLAP` |
| Safe commands fixed | `["whoami", "echo", "dir", ...]` | Env var `SAFE_COMMANDS=whoami,echo,dir,...` |

---

## NEW SUPPORTING TOOLS NEEDED

### 4.1 Discover Target Surface
Maps endpoints, request format, response structure.

```python
@tool("discover_target_surface")
def discover_target_surface(endpoint: str) -> str:
    """Probe target to discover API surface and capabilities.
    
    Returns:
    - Available endpoints (from OPTIONS, error responses)
    - Expected request format (JSON keys, query params)
    - Response structure and content type
    - Authentication requirements
    - Rate limiting headers
    """
```

**Use in planner task before RAG queries.**

---

### 4.2 Infer Target Schema
Tests field names to discover exact request format.

```python
@tool("infer_target_schema")
def infer_target_schema(endpoint: str, test_field_names: str) -> str:
    """Test which JSON field names the target accepts.
    
    Try: message, query, input, prompt
    Returns which ones work and their response structure.
    """
```

**Non-destructive reconnaissance.**

---

### 4.3 Analyze Target Behavior
Send benign test prompts to understand response patterns.

```python
@tool("analyze_target_behavior")
def analyze_target_behavior(endpoint: str, test_prompts: str) -> str:
    """Send safe test prompts (hello, help, test) to learn:
    - Response format and structure
    - Response times (indicates rate limiting)
    - Information leakage in error messages
    - Whether target reasons through tool calls
    """
```

**Helps planner understand target quirks.**

---

### 4.4 Scan Target Misconfigurations (Optional)
Identify common security misconfigurations.

```python
@tool("scan_target_misconfigurations")
def scan_target_misconfigurations(endpoint: str) -> str:
    """Check for:
    - Debug endpoints exposed (/debug, /admin)
    - CORS misconfiguration (Allow-Origin: *)
    - Missing authentication
    - Verbose error messages
    - Default credentials
    """
```

**Helps prioritize which vulnerabilities are likely successful.**

---

## Implementation Roadmap

### Week 1-2: Critical (Tier 1)
- [ ] Create `.env.template` (DONE - see file)
- [ ] Add env var loading for target URL & request format
- [ ] Support multiple LLM providers
- [ ] Fix database path to absolute

### Week 3-4: Medium (Tier 2)
- [ ] Create YAML config for agent profiles
- [ ] Create YAML config for attack strategies (timing)
- [ ] Add discovery tools to agents
- [ ] Add JSON schema validation

### Week 5+: Polish (Tier 3)
- [ ] Multi-format report generation
- [ ] Add remaining env vars
- [ ] Test against 3+ different targets
- [ ] Document configuration

---

## Key Insight

Your current architecture assumes:
```
Target Description → [Planner makes GUESS] → [Executor fires attacks] → [Reporter documents]
```

With discovery tools, it becomes:
```
Target Description → [Planner PROBES target] → [Planner makes INFORMED strategy] → [Executor fires targeted attacks] → [Reporter documents]
```

This 30% improvement in effectiveness costs ~2-3 hours per tool implementation.

---

## Files to Reference

- **HARDCODED_ANALYSIS.md** — 60+ page detailed analysis with code examples
- **.env.template** — Copy and customize for each deployment
- This file — Quick reference for decision-making
