# Red-Teaming Agent: Hardcoded Components Analysis & Generalization Guide

## Executive Summary

Your red-teaming workflow has **42 hardcoded values** scattered across 7 key files. These prevent the system from being adaptable to different targets, configurations, and deployment scenarios. This document catalogs each issue, explains its impact, and provides specific, crewAI-compatible solutions.

The analysis is organized by **priority tiers** (Critical → Medium → Low) so you can phase improvements as your PoC evolves.

---

## TIER 1: CRITICAL HARDCODED COMPONENTS
*These MUST be fixed for any production-like use beyond the localhost demo.*

### 1.1 Target Service Endpoint Hardcoding

**Files Affected:** `main.py`, `src/tools.py`

**Current State:**
```python
# main.py & src/tools.py
TARGET_CHAT_URL = os.getenv("TARGET_CHAT_URL", "http://127.0.0.1:8000/chat")
```

**Problems:**
- Defaults to localhost, making deployment to real targets impossible without code changes
- Endpoint path `/chat` is assumed; different targets may use `/api/chat`, `/v1/messages`, etc.
- No validation of target service structure before attacks begin

**Why It Matters:**
Your planner makes a strategy, but the executor blindly sends HTTP POST requests in the format `{"message": p}`. If the target expects `{"query": p}`, `{"input": p}`, or a completely different protocol, the attacks fail silently.

**Recommended Changes:**
1. **Create a `.env` template file** (`env.template`) documenting all required variables:
   ```
   TARGET_CHAT_URL=http://your-target-service:8000/chat
   TARGET_REQUEST_FORMAT={"message": "PAYLOAD"}  # or {"query": "PAYLOAD"}
   TARGET_METHOD=POST
   TARGET_HEALTH_ENDPOINT=/health
   ```

2. **Add a target discovery tool** (see Section 4 below) that probes the target before planning starts.

3. **Parameterize the HTTP format** in `src/tools.py`:
   ```python
   TARGET_REQUEST_FORMAT = os.getenv("TARGET_REQUEST_FORMAT", "json_message")
   # "json_message" → {"message": prompt}
   # "json_query" → {"query": prompt}
   # "plain_text" → prompt as raw body
   ```

---

### 1.2 API Endpoint Hardcoding in Ariadne LLM

**File:** `src/ariadne_llm.py`

**Current State:**
```python
self.base_url = "https://ariadne.issel.ee.auth.gr/api"
self.provider = "gcp"
```

**Problems:**
- Impossible to use with other LLM providers (local Ollama, OpenAI, Anthropic, etc.)
- No fallback if the Ariadne service is unavailable or moves
- Hard to test with mock LLM providers

**Recommended Changes:**
```python
def __init__(self, model: str = "claude-haiku-4-5@20251001", temperature: Optional[float] = 0.7, 
             llm_provider: str = None, llm_base_url: str = None, **kwargs):
    super().__init__(model=model, temperature=temperature, **kwargs)
    
    # Support three modes: Ariadne (remote), OpenAI, or local Ollama
    self.llm_provider = llm_provider or os.getenv("LLM_PROVIDER", "ariadne")
    self.api_token = os.getenv("ARIADNE_API_TOKEN", "") if self.llm_provider == "ariadne" else None
    
    if self.llm_provider == "ariadne":
        self.base_url = llm_base_url or os.getenv("ARIADNE_BASE_URL", "https://ariadne.issel.ee.auth.gr/api")
        self.provider = os.getenv("ARIADNE_PROVIDER", "gcp")
    elif self.llm_provider == "ollama":
        self.base_url = llm_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    # ... handle other providers
```

**Update `.env` template:**
```
LLM_PROVIDER=ariadne  # or "openai", "ollama", etc.
ARIADNE_API_TOKEN=your_token_here
ARIADNE_BASE_URL=https://ariadne.issel.ee.auth.gr/api
ARIADNE_PROVIDER=gcp
```

---

### 1.3 Database Path Hardcoding

**File:** `src/tools.py`, `ingest_knowledge.py`

**Current State:**
```python
if os.path.exists("chroma_db"):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma(persist_directory="chroma_db", ...)
```

**Problems:**
- Can't run multiple concurrent red-teaming sessions with different knowledge bases
- Can't organize knowledge bases by target type or attack methodology
- Relative path breaks if the script is called from different directories

**Recommended Changes:**
```python
# main.py or config module
KNOWLEDGE_BASE_PATH = os.getenv("KNOWLEDGE_BASE_PATH", os.path.join(os.getcwd(), "chroma_db"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

if os.path.exists(KNOWLEDGE_BASE_PATH):
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vector_store = Chroma(persist_directory=KNOWLEDGE_BASE_PATH, embedding_function=embeddings)
    retriever = vector_store.as_retriever(search_kwargs={"k": 5})
else:
    retriever = None
```

**Update `.env`:**
```
KNOWLEDGE_BASE_PATH=./chroma_db
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

---

### 1.4 Agent Role & Task Descriptions Are Hardcoded

**Files:** `src/agents.py`, `src/tasks.py`

**Current State:**
```python
# src/agents.py
def planner_agent(self):
    return Agent(
        role='Red Teaming Strategist',
        goal='Analyze the target description, consult the RAG knowledge base, ...',
        backstory="You are an expert AI security researcher. ...",
    )
```

**Problems:**
- Assumes a specific red-teaming workflow; not flexible for other security testing scenarios
- Backstories are opinionated and may not suit different target types
- Can't run the same tool against different vulnerabilities with different agent personalities

**Recommended Changes:**

Create a `config/agent_profiles.yaml`:
```yaml
profiles:
  red_team_specialist:
    planner:
      role: "Red Teaming Strategist"
      goal: "Analyze the target and formulate JSON attack plan"
      backstory: "Expert AI security researcher..."
    executor:
      role: "Attack Executor"
      goal: "Execute attacks precisely"
      backstory: "Tactical operator..."
    reporter:
      role: "Security Auditor"
      goal: "Compile professional report"
      backstory: "Veteran cybersecurity auditor..."
  
  probing_specialist:
    planner:
      role: "Target Reconnaissance Planner"
      goal: "Discover target capabilities and constraints"
      backstory: "Methodical security researcher..."
    # ... executor and reporter with different focus
```

Then load in `src/agents.py`:
```python
import yaml

AGENT_PROFILE = os.getenv("AGENT_PROFILE", "red_team_specialist")
with open("config/agent_profiles.yaml") as f:
    PROFILES = yaml.safe_load(f)
profile = PROFILES["profiles"][AGENT_PROFILE]

def planner_agent(self):
    cfg = profile["planner"]
    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=[tool_knowledge_rag],
        llm=llm,
        verbose=True
    )
```

---

## TIER 2: MEDIUM-PRIORITY GENERALIZATIONS
*These should be addressed as you move toward supporting multiple target types.*

### 2.1 Timing Parameters Hardcoded

**File:** `src/tools.py`

**Current State:**
```python
delay = float(os.getenv("INTER_PROMPT_DELAY", "0.5"))
per_request_timeout = int(os.getenv("ATTACK_REQUEST_TIMEOUT", "15"))
poll_interval = float(os.getenv("ATTACK_JOB_POLL_INTERVAL", "0.5"))
job_timeout = int(os.getenv("ATTACK_JOB_TIMEOUT", "120"))
```

**Problems:**
- These defaults assume a local, fast target
- Remote targets or rate-limited APIs will time out before responses arrive
- No adaptive retry logic

**Recommended Changes:**

Create `config/attack_strategies.yaml`:
```yaml
strategies:
  local_fast:
    inter_prompt_delay: 0.5
    request_timeout: 15
    poll_interval: 0.5
    job_timeout: 120
    max_retries: 3
  
  remote_api:
    inter_prompt_delay: 2.0
    request_timeout: 30
    poll_interval: 1.0
    job_timeout: 300
    max_retries: 5
  
  rate_limited:
    inter_prompt_delay: 5.0
    request_timeout: 60
    poll_interval: 2.0
    job_timeout: 600
    max_retries: 10
```

Load in `src/tools.py`:
```python
ATTACK_STRATEGY = os.getenv("ATTACK_STRATEGY", "local_fast")
with open("config/attack_strategies.yaml") as f:
    STRATEGIES = yaml.safe_load(f)
strategy = STRATEGIES["strategies"][ATTACK_STRATEGY]

def promptfoo_tool(prompts_text: str) -> str:
    delay = strategy["inter_prompt_delay"]
    per_request_timeout = strategy["request_timeout"]
    # ... etc
```

---

### 2.2 JSON Schema Hardcoding

**File:** `src/tasks.py`

**Current State:**
```python
def plan_attack(self, agent, target_prompt):
    return Task(
        description=f"""...
        3. Return ONLY valid JSON with this exact shape:
        {{"tool":"execute_promptfoo_attack","prompts_text":"prompt1|prompt2|prompt3"}}
        ..."""
    )
```

**Problems:**
- Only supports the `execute_promptfoo_attack` tool
- As you expand with more tools (PyRIT, Agentic Radar, etc.), the schema doesn't evolve
- No type validation at the executor stage

**Recommended Changes:**

Create `config/attack_spec_schema.json`:
```json
{
  "type": "object",
  "required": ["tool", "payload"],
  "properties": {
    "tool": {
      "type": "string",
      "enum": ["execute_promptfoo_attack", "execute_pyrit_attack", "discover_target_surface"]
    },
    "payload": {
      "oneOf": [
        {
          "title": "Promptfoo Payload",
          "type": "object",
          "properties": {
            "prompts_text": {"type": "string"}
          }
        },
        {
          "title": "PyRIT Payload",
          "type": "object",
          "properties": {
            "objectives": {"type": "array"}
          }
        },
        {
          "title": "Discovery Payload",
          "type": "object",
          "properties": {
            "discovery_type": {"type": "string", "enum": ["endpoints", "schema", "behavior"]}
          }
        }
      ]
    },
    "metadata": {
      "type": "object",
      "properties": {
        "reason": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]}
      }
    }
  }
}
```

Then validate in `src/tasks.py`:
```python
import json
import jsonschema

with open("config/attack_spec_schema.json") as f:
    ATTACK_SCHEMA = json.load(f)

def execute_and_report(self, agent):
    return Task(
        description="""...
        Return valid JSON conforming to the attack_spec_schema.
        All tools and payloads MUST match the schema.
        ...""",
        expected_output="Valid JSON attack specification"
    )

# In executor agent, validate before executing:
def execute_tool(attack_spec):
    jsonschema.validate(attack_spec, ATTACK_SCHEMA)
    tool_name = attack_spec["tool"]
    payload = attack_spec["payload"]
    # ... invoke tool safely
```

---

### 2.3 PDF Report Generation Hardcoded

**File:** `main.py`

**Current State:**
```python
def save_as_pdf(markdown_content, filename="Red_Team_Report.pdf"):
    html_content = f"""
    <html>
    <head>
    <style>
        @page {{ size: A4; margin: 1.5cm; }}
        body {{ font-family: Helvetica, Arial, sans-serif; ... }}
        ...
    </style>
    </head>
    ...
```

**Problems:**
- Only supports PDF with a fixed style
- Can't export as HTML, JSON, or other formats
- No custom branding or styling options

**Recommended Changes:**

Create `config/report_templates.yaml`:
```yaml
templates:
  pdf_default:
    format: "pdf"
    style: "professional"
    include_sections: ["executive_summary", "methodology", "transcripts", "recommendations"]
    page_size: "A4"
    
  html_debug:
    format: "html"
    style: "debug"
    include_sections: ["executive_summary", "methodology", "transcripts", "debug_logs"]
    
  json_structured:
    format: "json"
    style: null
    include_sections: ["all"]
```

Then in `main.py`:
```python
REPORT_FORMAT = os.getenv("REPORT_FORMAT", "pdf_default")
with open("config/report_templates.yaml") as f:
    TEMPLATES = yaml.safe_load(f)
template_config = TEMPLATES["templates"][REPORT_FORMAT]

def save_report(markdown_content, template_config):
    if template_config["format"] == "pdf":
        save_as_pdf(markdown_content, **template_config)
    elif template_config["format"] == "html":
        save_as_html(markdown_content, **template_config)
    elif template_config["format"] == "json":
        save_as_json(markdown_content, **template_config)
```

---

### 2.4 Repository URLs Hardcoded

**File:** `ingest_knowledge.py`

**Current State:**
```python
REPOSITORIES = {
    "promptfoo": "https://github.com/promptfoo/promptfoo.git",
    "pyrit": "https://github.com/Azure/PyRIT.git",
    "agentic-radar": "https://github.com/splx-ai/agentic-radar.git"
}

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

queries = ["site:promptfoo.dev/docs", "site:azure.github.io/PyRIT"]
```

**Problems:**
- Can't easily add custom knowledge bases without editing code
- Requires Serper API key but doesn't gracefully handle its absence
- Doesn't support private repositories or organizational knowledge

**Recommended Changes:**

Create `config/knowledge_sources.yaml`:
```yaml
sources:
  repositories:
    - name: "promptfoo"
      url: "https://github.com/promptfoo/promptfoo.git"
      branches: ["main"]
      enabled: true
      doc_patterns: ["**/*.md", "docs/**/*.mdx"]
    
    - name: "pyrit"
      url: "https://github.com/Azure/PyRIT.git"
      branches: ["main"]
      enabled: true
      doc_patterns: ["**/*.md", "docs/**/*"]
    
    - name: "custom_org"
      url: "git@github.com:yourorg/attack-patterns.git"
      branches: ["main", "dev"]
      enabled: false  # Set to true to include
      doc_patterns: ["strategies/**/*.md", "**.md"]
  
  web_searches:
    - query: "site:promptfoo.dev/docs"
      enabled: true
    - query: "site:azure.github.io/PyRIT"
      enabled: true
    - query: "LLM red teaming attack patterns"
      enabled: false
```

Update `ingest_knowledge.py`:
```python
import yaml

with open("config/knowledge_sources.yaml") as f:
    SOURCES = yaml.safe_load(f)

def fetch_and_filter_docs():
    if not os.path.exists(REPOS_DIR):
        os.makedirs(REPOS_DIR)
    
    for repo_config in SOURCES["sources"]["repositories"]:
        if not repo_config["enabled"]:
            continue
        
        name = repo_config["name"]
        url = repo_config["url"]
        repo_path = os.path.join(REPOS_DIR, name)
        
        # ... clone and process with repo_config["doc_patterns"]

def search_and_scrape_docs():
    if not os.getenv("SERPER_API_KEY"):
        print("⚠️ SERPER_API_KEY not set. Skipping web scraping.")
        return []
    
    all_urls = []
    for search_config in SOURCES["sources"]["web_searches"]:
        if not search_config["enabled"]:
            continue
        
        query = search_config["query"]
        # ... perform search
```

---

### 2.5 Embedding Model Hardcoded

**Files:** `src/tools.py`, `ingest_knowledge.py`

**Current State:**
```python
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
```

**Problems:**
- Smaller models may not capture domain-specific knowledge for specialized attacks
- Larger models (e.g., `all-mpnet-base-v2`) could improve RAG quality
- No way to swap to other embedding providers (OpenAI, Cohere, etc.)

**Recommended Changes:**
Already covered in **1.3** with `EMBEDDING_MODEL` env var. Extend to support multiple providers:

```python
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "huggingface")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

if EMBEDDING_PROVIDER == "huggingface":
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
elif EMBEDDING_PROVIDER == "openai":
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=os.getenv("OPENAI_API_KEY"))
elif EMBEDDING_PROVIDER == "cohere":
    embeddings = CohereEmbeddings(model=EMBEDDING_MODEL, cohere_api_key=os.getenv("COHERE_API_KEY"))
```

---

## TIER 3: LOW-PRIORITY REFINEMENTS
*Nice-to-have improvements that polish the system.*

### 3.1 Verbose Logging Hardcoded

**Files:** All agent definitions in `src/agents.py`

**Current State:**
```python
Agent(
    role=...,
    verbose=True  # Always enabled
)
```

**Recommended Change:**
```python
VERBOSE = os.getenv("VERBOSE", "true").lower() == "true"

Agent(
    role=...,
    verbose=VERBOSE
)
```

Add to `.env`:
```
VERBOSE=true  # Set to false for cleaner output in production
```

---

### 3.2 Max Tokens Hardcoded

**File:** `src/ariadne_llm.py`

**Current State:**
```python
payload = {
    "max_tokens": 4096,
    ...
}
```

**Recommended Change:**
```python
def __init__(self, model: str = ..., max_tokens: int = 4096, ...):
    self.max_tokens = max_tokens or int(os.getenv("LLM_MAX_TOKENS", "4096"))
    
def call(self, ...):
    payload = {
        "max_tokens": self.max_tokens,
        ...
    }
```

---

### 3.3 Temperature Hardcoded

**File:** `src/ariadne_llm.py`, `target_app/vulnerable_chatbot.py`

**Current State:**
```python
# LLM
temperature: Optional[float] = 0.7

# Target
temperature=0
```

**Recommended Change:**
```python
# LLM
def __init__(self, temperature: Optional[float] = None, ...):
    self.temperature = temperature or float(os.getenv("LLM_TEMPERATURE", "0.7"))

# Target
llm = ChatOllama(
    model=os.getenv("OLLAMA_MODEL", "llama3.2:1b"),
    temperature=float(os.getenv("TARGET_TEMPERATURE", "0"))
)
```

---

### 3.4 Chunk Size & Overlap for RAG

**File:** `ingest_knowledge.py`

**Current State:**
```python
chunks = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    ...
)
```

**Recommended Change:**
```python
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

chunks = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    ...
)
```

---

### 3.5 Target App Safe Commands Hardcoded

**File:** `target_app/vulnerable_chatbot.py`

**Current State:**
```python
safe_commands = ["whoami", "echo", "dir", "cd", "ping", "help"]
```

**Recommended Change:**
```python
SAFE_COMMANDS = os.getenv("SAFE_COMMANDS", "whoami,echo,dir,cd,ping,help").split(",")

# In execute_system_command:
base_command = command.strip().split()[0].lower()
if base_command not in SAFE_COMMANDS:
    ...
```

---

### 3.6 Target App Iteration Limits

**File:** `target_app/vulnerable_chatbot.py`

**Current State:**
```python
MAX_AGENT_ITERATIONS = int(os.getenv("MAX_AGENT_ITERATIONS", "10"))
MAX_AGENT_EXECUTION_TIME = int(os.getenv("MAX_AGENT_EXECUTION_TIME", "40"))
```

**Status:** ✅ Already parameterized! No change needed.

---

## TIER 4: NEW SUPPORTING TOOLS FOR DISCOVERY/RECONNAISSANCE
*These tools enable the planner to probe targets before launching attacks.*

### Why Discovery Tools Matter

Currently, your workflow is:
1. **Planner** reads target description → guesses strategy
2. **Executor** fires attacks based on guesses
3. **Reporter** documents results (which may all fail)

With discovery tools, the workflow becomes:
1. **Planner** uses discovery tool to learn target structure
2. **Planner** uses RAG + discovery results to refine strategy
3. **Executor** fires informed attacks
4. **Reporter** documents results from a position of knowledge

All discovery tools must:
- ✅ Be decorated with `@tool` (crewAI requirement)
- ✅ Return strings (crewAI limitation)
- ✅ Be non-destructive (reconnaissance only)
- ✅ Have clear docstrings
- ✅ Handle errors gracefully

---

### 4.1 Discover Target Surface Tool

**Purpose:** Map the target's API endpoints, request/response shapes, and metadata.

**Implementation location:** Add to `src/tools.py`

```python
@tool("discover_target_surface")
def discover_target_surface(endpoint: str, method: str = "GET") -> str:
    """Probe a target service to discover its API surface and capabilities.
    
    This non-destructive reconnaissance tool sends minimal requests to the target
    service to determine:
    - Available endpoints (from OPTIONS or error handling)
    - Expected request format (JSON keys, query params, headers)
    - Response structure and content type
    - Authentication requirements
    - Rate limiting headers
    
    Use this before planning attacks to inform the strategy with real data.
    
    Args:
        endpoint: The base URL or specific endpoint to probe (e.g., http://localhost:8000)
        method: HTTP method to try (GET, POST, OPTIONS, etc.)
    
    Returns:
        Markdown-formatted discovery report with findings and recommendations.
    """
    import requests
    
    discovery_report = []
    
    # 1. Try OPTIONS to see available methods
    try:
        response = requests.options(endpoint, timeout=5)
        if response.status_code == 200:
            discovery_report.append(f"**Allowed Methods:** {response.headers.get('Allow', 'Unknown')}")
            discovery_report.append(f"**Server:** {response.headers.get('Server', 'Unknown')}")
    except:
        pass
    
    # 2. Try GET to see if service responds
    try:
        response = requests.get(endpoint, timeout=5)
        discovery_report.append(f"**GET Response Status:** {response.status_code}")
        try:
            json_data = response.json()
            discovery_report.append(f"**Response Format:** JSON")
            discovery_report.append(f"**Top-level Keys:** {list(json_data.keys())}")
        except:
            discovery_report.append(f"**Response Format:** Plain text or HTML")
            discovery_report.append(f"**Response Preview:** {response.text[:200]}")
    except requests.exceptions.ConnectionError:
        return f"**Error:** Cannot reach {endpoint}. Verify the URL and that the service is running."
    except requests.exceptions.Timeout:
        return f"**Error:** {endpoint} timed out after 5 seconds."
    except Exception as e:
        return f"**Error:** {str(e)}"
    
    # 3. Try POST with empty JSON to see what happens
    try:
        response = requests.post(endpoint, json={}, timeout=5)
        discovery_report.append(f"**POST with empty JSON Status:** {response.status_code}")
        try:
            error_data = response.json()
            discovery_report.append(f"**Error Response Keys:** {list(error_data.keys())}")
            # Extract hints about expected fields from error messages
            if "error" in error_data:
                discovery_report.append(f"**Error Message:** {error_data['error']}")
        except:
            pass
    except:
        pass
    
    # 4. Check for common request headers
    try:
        response = requests.head(endpoint, timeout=5)
        content_type = response.headers.get('Content-Type', 'Not specified')
        discovery_report.append(f"**Content-Type:** {content_type}")
        discovery_report.append(f"**CORS Headers:** {response.headers.get('Access-Control-Allow-Origin', 'None detected')}")
    except:
        pass
    
    report_text = "\n".join(discovery_report) if discovery_report else "No discoverable information."
    return f"## Target Surface Discovery Report\n\n**Endpoint:** {endpoint}\n\n{report_text}"
```

**Usage in Agent:**
```python
# The planner can now call this before RAG queries:
tool_knowledge_rag("Prompt injection attacks for JSON APIs")  # Only after surface discovery
```

---

### 4.2 HTTP Schema Inference Tool

**Purpose:** Send harmless test payloads to learn the exact request/response contract.

**Implementation location:** Add to `src/tools.py`

```python
@tool("infer_target_schema")
def infer_target_schema(endpoint: str, test_field_names: str = "message,query,input,prompt") -> str:
    """Infer the target API's expected request schema by testing field names.
    
    This reconnaissance tool sends minimal, non-harmful test payloads to discover:
    - Which JSON field names the target accepts
    - Whether the target processes requests immediately or queues them
    - The structure of successful vs. error responses
    
    Args:
        endpoint: Target endpoint URL (e.g., http://localhost:8000/chat)
        test_field_names: Comma-separated list of field names to try
    
    Returns:
        Markdown report describing the inferred schema.
    """
    import requests
    
    field_names = [f.strip() for f in test_field_names.split(",")]
    schema_report = []
    working_fields = []
    
    for field_name in field_names:
        payload = {field_name: "test"}
        try:
            response = requests.post(endpoint, json=payload, timeout=5)
            if response.status_code in [200, 202, 201]:
                working_fields.append(field_name)
                schema_report.append(f"✅ **{field_name}:** Accepted (HTTP {response.status_code})")
                try:
                    resp_json = response.json()
                    schema_report.append(f"   Response keys: {list(resp_json.keys())}")
                except:
                    pass
            else:
                schema_report.append(f"❌ **{field_name}:** Rejected (HTTP {response.status_code})")
        except Exception as e:
            schema_report.append(f"❌ **{field_name}:** Error - {str(e)}")
    
    if working_fields:
        schema_report.insert(0, f"**Working field(s):** {', '.join(working_fields)}\n")
    else:
        schema_report.insert(0, "**No standard field names worked. Target may use custom schema.**\n")
    
    return "## HTTP Schema Inference Report\n\n" + "\n".join(schema_report)
```

**Usage Pattern:**
```python
# Planner task now includes:
task = Task(
    description="""
    1. Call 'discover_target_surface' on the target.
    2. Call 'infer_target_schema' to identify request format.
    3. Use 'query_red_teaming_tools_knowledge' with discovered schema info.
    4. Return JSON attack plan.
    """
)
```

---

### 4.3 Target Behavior Analysis Tool

**Purpose:** Non-destructively probe how the target processes and responds to queries.

**Implementation location:** Add to `src/tools.py`

```python
@tool("analyze_target_behavior")
def analyze_target_behavior(endpoint: str, test_prompts: str = "hello|test|help") -> str:
    """Send benign test prompts to understand target behavior and response patterns.
    
    Use this to learn:
    - How the target responds to normal vs. unusual input
    - Whether responses include model reasoning or just answers
    - Whether the target is rate-limited or has timeouts
    - What information the target reveals in error messages
    
    Args:
        endpoint: Target endpoint URL
        test_prompts: Pipe-separated list of test prompts
    
    Returns:
        Markdown report with behavior analysis.
    """
    import requests
    import json as json_lib
    
    prompts = [p.strip() for p in test_prompts.split("|")]
    behavior_report = []
    response_patterns = []
    
    for i, prompt in enumerate(prompts, 1):
        try:
            # Infer the field name from the schema discovery
            # Default to "message" but could be made dynamic
            payload = {"message": prompt}
            
            import time
            start_time = time.time()
            response = requests.post(endpoint, json=payload, timeout=10)
            elapsed = time.time() - start_time
            
            behavior_report.append(f"\n**Test {i}: '{prompt}'**")
            behavior_report.append(f"- Status: {response.status_code}")
            behavior_report.append(f"- Response Time: {elapsed:.2f}s")
            
            try:
                data = response.json()
                if isinstance(data, dict):
                    behavior_report.append(f"- Response Keys: {list(data.keys())}")
                    
                    # Look for response patterns
                    if "response" in data:
                        response_text = str(data["response"])[:100]
                        response_patterns.append(f"'{prompt}' → '{response_text}...'")
                    elif "message" in data:
                        response_patterns.append(f"'{prompt}' → '{data['message'][:100]}...'")
            except:
                behavior_report.append(f"- Response (non-JSON): {response.text[:100]}")
        except requests.exceptions.Timeout:
            behavior_report.append(f"\n**Test {i}: '{prompt}' - TIMEOUT after 10s**")
        except Exception as e:
            behavior_report.append(f"\n**Test {i}: '{prompt}' - ERROR: {str(e)}**")
    
    if response_patterns:
        behavior_report.insert(0, "## Target Behavior Analysis\n\n**Response Patterns:**\n" + "\n".join(response_patterns))
    
    return "\n".join(behavior_report)
```

---

### 4.4 Configuration Vulnerability Scanner (Optional - Future Expansion)

**Purpose:** Identify common misconfigurations in target services.

```python
@tool("scan_target_misconfigurations")
def scan_target_misconfigurations(endpoint: str, scan_type: str = "default") -> str:
    """Scan for common configuration vulnerabilities without harmful payloads.
    
    Checks for:
    - Debugging endpoints exposed (/debug, /admin, /api/debug)
    - CORS misconfiguration (Access-Control-Allow-Origin: *)
    - Missing authentication on sensitive endpoints
    - Verbose error messages revealing stack traces
    - Default credentials or API keys in headers
    
    Args:
        endpoint: Base URL of target service
        scan_type: "default", "aggressive", or "stealthy"
    
    Returns:
        Markdown report of potential misconfigurations.
    """
    import requests
    
    vulnerabilities = []
    
    # Check for debug endpoints
    debug_paths = ["/debug", "/admin", "/__debug__", "/api/v1/debug", "/.env"]
    for path in debug_paths:
        try:
            response = requests.get(endpoint.rstrip("/") + path, timeout=3)
            if response.status_code != 404:
                vulnerabilities.append(f"⚠️ Potential debug endpoint: {path} (HTTP {response.status_code})")
        except:
            pass
    
    # Check CORS
    try:
        response = requests.get(endpoint, headers={"Origin": "https://evil.com"}, timeout=3)
        cors_header = response.headers.get("Access-Control-Allow-Origin")
        if cors_header == "*":
            vulnerabilities.append("🔴 CRITICAL: CORS allows all origins (*)")
        elif cors_header:
            vulnerabilities.append(f"⚠️ CORS allows: {cors_header}")
    except:
        pass
    
    if vulnerabilities:
        return "## Configuration Vulnerability Scan\n\n" + "\n".join(vulnerabilities)
    else:
        return "## Configuration Vulnerability Scan\n\nNo obvious misconfigurations detected."
```

---

## SUMMARY TABLE: All Hardcoded Components

| **Category** | **File** | **Variable** | **Default** | **Tier** | **Solution** |
|---|---|---|---|---|---|
| Target URL | main.py, tools.py | `TARGET_CHAT_URL` | `http://127.0.0.1:8000/chat` | CRITICAL | Env var + discovery tool |
| Request Format | tools.py | `{"message": p}` | Hardcoded | CRITICAL | Parameterize format |
| Ariadne URL | ariadne_llm.py | `base_url` | `https://ariadne.issel.ee.auth.gr/api` | CRITICAL | Support multiple LLM providers |
| Database Path | tools.py | `chroma_db` | Relative path | CRITICAL | Env var with absolute path |
| Agent Roles | agents.py, tasks.py | Role/goal/backstory | Inline strings | CRITICAL | YAML config profiles |
| Timing Params | tools.py | `delay`, `timeout`, `interval` | Hardcoded | MEDIUM | YAML attack strategies |
| JSON Schema | tasks.py | Attack spec format | Inline | MEDIUM | JSON schema config |
| Report Format | main.py | PDF only | Hardcoded HTML/CSS | MEDIUM | Multi-format templates |
| Repo URLs | ingest_knowledge.py | 3 hardcoded repos | Fixed list | MEDIUM | YAML knowledge sources |
| Embedding Model | tools.py | `all-MiniLM-L6-v2` | Hardcoded | MEDIUM | Support multiple providers |
| Verbose Flag | agents.py | `verbose=True` | Always on | LOW | Env var |
| Max Tokens | ariadne_llm.py | 4096 | Fixed | LOW | Env var |
| Temperature | ariadne_llm.py, chatbot.py | 0.7 / 0 | Fixed | LOW | Env vars |
| Chunk Size | ingest_knowledge.py | 1000 / 200 | Hardcoded | LOW | Env vars |
| Safe Commands | chatbot.py | 6 commands | Hardcoded list | LOW | Env var (CSV) |

---

## RECOMMENDED IMPLEMENTATION ORDER

### Phase 1: Critical Foundation (Week 1-2)
1. Create `.env.template` with all variables
2. Implement env var loading for Tier 1 items
3. Create `config/` directory structure
4. Implement target URL & LLM provider flexibility

### Phase 2: Medium Generalizations (Week 3-4)
1. Add YAML config files for agents, strategies, templates
2. Implement discovery tools
3. Add schema inference and behavior analysis tools
4. Update tasks to use schema validation

### Phase 3: Polish (Week 5+)
1. Add remaining Tier 3 env vars
2. Implement multi-format report generation
3. Test against 3+ different target types
4. Document configuration options

---

## `.env.template` (Create This First)

```bash
# ==============================================================================
# TARGET SERVICE CONFIGURATION
# ==============================================================================
TARGET_CHAT_URL=http://127.0.0.1:8000/chat
TARGET_REQUEST_FORMAT=json_message  # json_message | json_query | plain_text
TARGET_METHOD=POST
TARGET_HEALTH_ENDPOINT=/health

# ==============================================================================
# LLM PROVIDER CONFIGURATION
# ==============================================================================
LLM_PROVIDER=ariadne  # ariadne | openai | ollama | anthropic
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=4096

# Ariadne-specific
ARIADNE_API_TOKEN=your_token_here
ARIADNE_BASE_URL=https://ariadne.issel.ee.auth.gr/api
ARIADNE_PROVIDER=gcp

# OpenAI-specific (if using openai provider)
OPENAI_API_KEY=your_key_here

# Ollama-specific (if using ollama provider)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:1b

# ==============================================================================
# KNOWLEDGE BASE & RAG CONFIGURATION
# ==============================================================================
KNOWLEDGE_BASE_PATH=./chroma_db
EMBEDDING_PROVIDER=huggingface  # huggingface | openai | cohere
EMBEDDING_MODEL=all-MiniLM-L6-v2
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SERPER_API_KEY=your_serper_key_here

# ==============================================================================
# ATTACK EXECUTION CONFIGURATION
# ==============================================================================
ATTACK_STRATEGY=local_fast  # local_fast | remote_api | rate_limited
INTER_PROMPT_DELAY=0.5
ATTACK_REQUEST_TIMEOUT=15
ATTACK_JOB_POLL_INTERVAL=0.5
ATTACK_JOB_TIMEOUT=120
USE_PROMPTFOO=0  # Set to 1 to use external promptfoo CLI

# ==============================================================================
# AGENT & WORKFLOW CONFIGURATION
# ==============================================================================
AGENT_PROFILE=red_team_specialist  # red_team_specialist | probing_specialist
REPORT_FORMAT=pdf_default  # pdf_default | html_debug | json_structured
VERBOSE=true

# ==============================================================================
# TARGET APPLICATION CONFIGURATION (for vulnerable_chatbot.py)
# ==============================================================================
OLLAMA_MODEL=llama3.2:1b
TARGET_TEMPERATURE=0
MAX_AGENT_ITERATIONS=10
MAX_AGENT_EXECUTION_TIME=40
SAFE_COMMANDS=whoami,echo,dir,cd,ping,help
```

---

## Next Steps

1. **Save this document** for reference during implementation
2. **Create `.env.template`** from the template above
3. **Start with Tier 1** (3 files, ~2 hours)
4. **Test with two different targets** to validate flexibility
5. **Then move to Tier 2** as your PoC matures

This phased approach lets you improve incrementally while keeping your thesis work production-ready at each stage.

