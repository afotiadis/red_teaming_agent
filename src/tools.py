"""Tools exposed to the red-teaming planner and deterministic executor.

This module is the operational bridge between the crew and the outside world.
It provides three kinds of capabilities:

* a retrieval tool that lets the planner consult the documentation knowledge base,
* a Promptfoo-based attack executor that can replay test prompts against the target,
* reconnaissance helpers that map the configured chatbot surface.

The file also initializes the local vector-store retriever if the knowledge base
has already been built. That makes the planner step self-contained: it can ask
for documentation support without needing to know how the embeddings are stored.
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import time
import uuid
import re
from pathlib import Path
import requests
from crewai.tools import tool
from langchain_chroma import Chroma
from src.gandalf_utils import SEMANTIC_GUESS_CLUSTERS
from langchain_community.embeddings import HuggingFaceEmbeddings
from src.target_profiles import (
    build_target_headers,
    build_target_payload,
    get_target_app,
    get_target_chat_url,
    get_target_health_url,
    get_target_history_url,
    get_target_enhanced_chat_url,
    get_target_request_field,
    get_target_request_format,
    get_target_auth_mode,
    get_target_auth_token,
    get_target_attack_strategy,
    get_target_base_url,
    target_auth_is_required,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_ROOT = os.getenv("SKILLS_ROOT", os.path.join(PROJECT_ROOT, "skills"))
TARGET_APP = get_target_app()
TARGET_CHAT_URL = get_target_chat_url()
TARGET_HEALTH_URL = get_target_health_url()
TARGET_HISTORY_URL = get_target_history_url()
TARGET_ENHANCED_CHAT_URL = get_target_enhanced_chat_url()
TARGET_REQUEST_FORMAT = get_target_request_format()
TARGET_REQUEST_FIELD = get_target_request_field()
TARGET_AUTH_MODE = get_target_auth_mode()
TARGET_AUTH_TOKEN = get_target_auth_token()
KNOWLEDGE_BASE_PATH = os.getenv("KNOWLEDGE_BASE_PATH", os.path.join(PROJECT_ROOT, "chroma_db"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
GANDALF_SKILL_CANDIDATES = [
    os.getenv("GANDALF_SKILL_PATH", "skills/gandalf-ctf/SKILL.md"),
    "skills/gandalf/SKILL.md",
    "skills/gandalf-ctf/SKILL.md",
]
ATTACK_STRATEGIES_PATH = os.getenv("ATTACK_STRATEGIES_PATH", os.path.join(PROJECT_ROOT, "config", "attack_strategies.json"))


DEFAULT_ATTACK_STRATEGY = {
    "inter_prompt_delay": float(os.getenv("INTER_PROMPT_DELAY", "0.5")),
    "connect_timeout": int(os.getenv("ATTACK_CONNECT_TIMEOUT", "5")),
    "request_timeout": int(os.getenv("ATTACK_REQUEST_TIMEOUT", "15")),
    "poll_interval": float(os.getenv("ATTACK_JOB_POLL_INTERVAL", "0.5")),
    "job_timeout": int(os.getenv("ATTACK_JOB_TIMEOUT", "120")),
    "max_retries": int(os.getenv("ATTACK_MAX_RETRIES", "0")),
    "retry_timeout_multiplier": float(os.getenv("ATTACK_RETRY_TIMEOUT_MULTIPLIER", "1.5")),
    "retry_backoff": float(os.getenv("ATTACK_RETRY_BACKOFF", "5")),
    "consecutive_timeout_threshold": int(os.getenv("ATTACK_TIMEOUT_THRESHOLD", "2")),
    "timeout_cooldown": float(os.getenv("ATTACK_TIMEOUT_COOLDOWN", "20")),
    "health_check_timeout": int(os.getenv("ATTACK_HEALTH_CHECK_TIMEOUT", "5")),
    "retry_action_prompts": os.getenv("ATTACK_RETRY_ACTION_PROMPTS", "false").lower() == "true",
}


def _load_attack_strategy() -> dict:
    """Load the selected attack pacing profile from disk, with env defaults."""
    default_strategy_name = get_target_attack_strategy()
    strategy_name = os.getenv("ATTACK_STRATEGY", default_strategy_name)
    try:
        with open(ATTACK_STRATEGIES_PATH, "r", encoding="utf-8") as strategy_file:
            strategies = json.load(strategy_file)
        selected_strategy = strategies.get(strategy_name, {})
        return {**DEFAULT_ATTACK_STRATEGY, **selected_strategy, "name": strategy_name}
    except Exception:
        return {**DEFAULT_ATTACK_STRATEGY, "name": strategy_name}


ATTACK_STRATEGY = _load_attack_strategy()


STATE_CHANGING_PROMPT_PATTERN = re.compile(
    r"\b(book|schedule|cancel|reschedule|create|update|delete|modify|send|email|sms|export|"
    r"grant|revoke|disable|enable|execute|run)\b",
    re.IGNORECASE,
)


def _is_potentially_state_changing_prompt(prompt: str) -> bool:
    """Return True when retrying a timed-out prompt could repeat a side effect."""
    return bool(STATE_CHANGING_PROMPT_PATTERN.search(prompt or ""))


def _safe_response_body(response) -> object:
    """Return JSON when available and preserve non-JSON error bodies otherwise."""
    try:
        return response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        return {"raw_text": response.text}


def _probe_target_health(session: requests.Session, timeout: int) -> dict:
    """Check whether the target recovered without aborting the attack run."""
    try:
        response = session.get(TARGET_HEALTH_URL, headers=_target_headers(), timeout=timeout)
        return {"reachable": True, "status_code": response.status_code}
    except requests.RequestException as exc:
        return {"reachable": False, "error": str(exc)}


def _target_headers(extra_headers: dict | None = None) -> dict:
    return build_target_headers(extra_headers)

def _build_job_url(chat_url: str, job_id: str) -> str:
    """Build the polling URL for a queued chat job.

    The target app returns a job id immediately and finishes processing in the
    background. This helper translates the base chat URL into the corresponding
    `/job/{job_id}` endpoint so the executor can poll for completion.
    """
    base_url = chat_url[:-5] if chat_url.endswith("/chat") else chat_url.rstrip("/")
    return f"{base_url}/job/{job_id}"


def _build_health_url(chat_url: str) -> str:
    """Convert the configured chat URL into its health-check endpoint."""
    if chat_url.endswith("/chat"):
        return f"{chat_url[:-5]}/health"
    return f"{chat_url.rstrip('/')}/health"


def _build_request_payload(prompt: str) -> object:
    """Build a request body that matches the configured target contract."""
    return build_target_payload(prompt)


def _build_request_kwargs(prompt: str) -> dict:
    """Build the requests.post keyword arguments for the configured target contract."""
    payload = _build_request_payload(prompt)
    if TARGET_REQUEST_FORMAT == "plain_text":
        return {
            "data": payload,
            "headers": _target_headers({"Content-Type": "text/plain"}),
        }
    return {"json": payload, "headers": _target_headers({"Content-Type": "application/json"})}


def _resolve_skill_path(skill_path: str) -> Path:
    """Resolve a skill path safely inside the configured skills directory."""
    candidate = Path(skill_path)
    if not candidate.is_absolute():
        candidate = Path(PROJECT_ROOT) / candidate

    skills_root = Path(SKILLS_ROOT).resolve()
    resolved = candidate.resolve()
    if skills_root not in resolved.parents and resolved != skills_root:
        raise ValueError(f"Skill path must live under {skills_root}. Got: {resolved}")
    return resolved


def _resolve_existing_skill_path(skill_path_candidates: list[str]) -> Path:
    """Return the first existing skill path from a list of candidates."""
    last_error = None
    for candidate in skill_path_candidates:
        try:
            resolved = _resolve_skill_path(candidate)
            if resolved.exists():
                return resolved
        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise FileNotFoundError(f"None of the configured skill paths exist: {skill_path_candidates}")


def _load_jsonish_payload(payload_text: str) -> dict:
    """Parse a planner handoff payload that may be JSON or a raw text block."""
    payload_text = (payload_text or "").strip()
    if not payload_text:
        return {}

    try:
        return json.loads(payload_text)
    except Exception:
        return {"raw_text": payload_text}


def _build_promptfoo_command(config_path: str) -> list[str]:
    """Resolve a working Promptfoo launcher for the current platform.

    Promptfoo can be installed in a few different ways depending on the operating
    system and shell. This helper checks for the most likely entry points and
    returns the command line that should actually be executed.
    """
    if os.name != "nt":
        binary = shutil.which("promptfoo")
        if not binary:
            raise FileNotFoundError("promptfoo is not installed or not in PATH.")
        return [binary, "eval", "-c", config_path]

    cmd_binary = shutil.which("promptfoo.cmd")
    if cmd_binary:
        return [cmd_binary, "eval", "-c", config_path]

    ps1_binary = shutil.which("promptfoo.ps1")
    if ps1_binary:
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ps1_binary,
            "eval",
            "-c",
            config_path,
        ]

    raise FileNotFoundError(
        "Promptfoo launcher not found. Install promptfoo and ensure promptfoo.cmd or promptfoo.ps1 is on PATH."
    )


RAG_FALLBACK_ROOTS = [
    Path(PROJECT_ROOT) / "data" / "repos",
    Path(PROJECT_ROOT) / "data" / "attack_knowledge",
    Path(PROJECT_ROOT) / "data" / "experiential_memory",
    Path(PROJECT_ROOT) / "skills",
]


def _initialize_retriever():
    """Load Chroma if possible, otherwise fall back to keyword search."""
    if not os.path.exists(KNOWLEDGE_BASE_PATH):
        return None, f"Knowledge base path not found: {KNOWLEDGE_BASE_PATH}"

    try:
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        vector_store = Chroma(persist_directory=KNOWLEDGE_BASE_PATH, embedding_function=embeddings)
        return vector_store.as_retriever(search_kwargs={"k": 5}), None
    except Exception as exc:
        return None, str(exc)


def _load_fallback_corpus(max_files: int = 300) -> list[tuple[str, str]]:
    """Load a lightweight text corpus from local docs for fallback search."""
    corpus = []
    seen_paths = set()
    for root in RAG_FALLBACK_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if len(corpus) >= max_files:
                return corpus
            if not path.is_file() or path.suffix.lower() not in {".md", ".mdx", ".txt"}:
                continue
            if path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                corpus.append((str(path), path.read_text(encoding="utf-8", errors="ignore")))
            except Exception:
                pass
    return corpus


def _fallback_rag_search(query: str) -> str:
    """Keyword-score the local docs when Chroma is unavailable or broken."""
    keywords = [token for token in re.findall(r"[A-Za-z0-9_\-]+", query.lower()) if len(token) > 2]
    if not keywords:
        return "No relevant information found in the documentation."

    scored = []
    for source, text in _load_fallback_corpus():
        lower_text = text.lower()
        score = sum(lower_text.count(keyword) for keyword in keywords)
        if score:
            best_index = min((lower_text.find(keyword) for keyword in keywords if keyword in lower_text), default=-1)
            if best_index >= 0:
                start = max(0, best_index - 200)
                end = min(len(text), best_index + 500)
                snippet = text[start:end].replace("\n", " ").strip()
            else:
                snippet = text[:700].replace("\n", " ").strip()
            scored.append((score, source, snippet))

    if not scored:
        return "No relevant information found in the documentation."

    scored.sort(key=lambda item: item[0], reverse=True)
    top_matches = scored[:3]
    return "\n\n".join([f"Source: {source}\nContent: {snippet}" for _, source, snippet in top_matches])


def rag_search_knowledge(query: str) -> str:
    """Search the local documentation corpus without a CrewAI tool wrapper."""
    if retriever:
        try:
            results = retriever.invoke(query)
            if not results:
                return "No relevant information found in the documentation."
            return "\n\n".join([
                f"Source: {doc.metadata.get('source', 'Unknown')}\nContent: {doc.page_content}"
                for doc in results
            ])
        except Exception as exc:
            fallback = _fallback_rag_search(query)
            if fallback != "No relevant information found in the documentation.":
                return f"RAG fallback search used because Chroma query failed ({exc}).\n\n{fallback}"
            return f"Error: Chroma query failed and fallback search found no matches. {exc}"

    fallback = _fallback_rag_search(query)
    if fallback != "No relevant information found in the documentation.":
        reason = _retriever_error or "knowledge base unavailable"
        return f"RAG fallback search used because the vector store could not be loaded ({reason}).\n\n{fallback}"
    return f"Error: Chroma DB not available and fallback search found no matches. {_retriever_error or 'unknown error'}"


# Allow tests and lightweight runs to skip heavy RAG init by setting SKIP_RAG_INIT=1.
# Normal runs preserve the existing behavior and initialize the vector store.
if os.getenv("SKIP_RAG_INIT", "0") == "1":
    retriever, _retriever_error = None, "SKIP_RAG_INIT enabled"
else:
    try:
        retriever, _retriever_error = _initialize_retriever()
    except Exception as _exc:
        retriever, _retriever_error = None, str(_exc)


def _looks_like_definition(text: str) -> tuple[bool, list[str], str]:
    """Heuristically determine whether text is definition-shaped.

    Returns a boolean, the matched pattern labels, and an extracted search query
    that can be passed to the definition lookup tool.
    """
    normalized = (text or "").strip().lower()
    if not normalized:
        return False, [], ""

    patterns = [
        ("is_a_definition", r"\b(is|means|refers to|describes|indicates|defines|suggests)\b"),
        ("noun_phrase", r"\b(word|phrase|term|concept|thing|idea|object|phenomenon)\b"),
        ("domain_hint", r"\b(measurement|transmission|energy|growth|tropical|light|signal|wave)\b"),
        ("template_hint", r"\b(what does|what is|what would|if you had to|in other words|a word that)\b"),
    ]

    matched_patterns: list[str] = []
    for label, pattern in patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            matched_patterns.append(label)

    score = len(matched_patterns)
    looks_like_definition = score >= 2

    stopwords = {
        "the", "and", "or", "but", "for", "with", "from", "into", "onto", "over",
        "under", "about", "after", "before", "during", "through", "within", "without",
        "this", "that", "these", "those", "there", "their", "they", "them", "you",
        "your", "yours", "his", "her", "its", "our", "ours", "is", "are", "was",
        "were", "be", "been", "being", "am", "a", "an", "of", "to", "in", "on",
        "as", "at", "by", "it", "i", "we", "can", "could", "would", "should",
        "may", "might", "will", "shall", "not", "no", "yes", "if", "then", "than",
        "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
        "more", "most", "less", "few", "many", "all", "any", "some", "like",
        "secret", "password", "answer", "clue", "hint", "please", "provide",
        "give", "tell", "share", "help",
    }

    # Keep the most semantically useful fragment if the text is long.
    tokens = [token for token in re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", normalized) if token not in stopwords]
    if tokens:
        query = " ".join(tokens[:6])
    else:
        query = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", normalized)
        query = re.sub(r"\b(the secret password|secret password|password|secret|answer|clue|hint)\b", "", query)
        query = re.sub(r"\s+", " ", query).strip()

        if len(query.split()) > 12:
            query = " ".join(query.split()[:12])

    return looks_like_definition, matched_patterns, query


@tool("detect_definition_clue")
def detect_definition_clue(text: str) -> str:
    """Classify whether text looks like a definition and extract a lookup query.

    This gives the planner an explicit signal for when it should call the
    definition search tool instead of treating the text as a generic clue.
    """
    looks_like_definition, matched_patterns, query = _looks_like_definition(text)
    return json.dumps(
        {
            "text": text,
            "looks_like_definition": looks_like_definition,
            "matched_patterns": matched_patterns,
            "search_query": query,
        },
        ensure_ascii=False,
        indent=2,
    )


def definition_lookup(definition_text: str, max_results: int = 5) -> list[str]:
    """
    Reverse-engineer a word from its definition by querying free dictionary/search APIs.
    
    When Gandalf gives a definition like "transmission of energy through space",
    this tool returns candidate words: ["wave", "signal", "light", "radiation", "beam"]
    
    Uses multiple fallback strategies:
    1. DuckDuckGo instant answers (free, no API key)
    2. Query constructed word pools based on definition keywords
    3. Fall back to pre-built SEMANTIC_GUESS_CLUSTERS
    
    Args:
        definition_text: Definition string to reverse-engineer (e.g., "transmission of energy")
        max_results: Max candidates to return
        
    Returns:
        List of candidate words matching the definition
    """
    candidates = set()
    
    # Strategy 1: Extract key phrases from definition and use semantic clusters
    definition_lower = definition_text.lower()
    keywords = ["transmission", "energy", "wave", "signal", "growth", "potential", "tropical"]
    
    # Pre-built semantic mappings from shared utils
    semantic_db = SEMANTIC_GUESS_CLUSTERS
    
    # Match keywords in definition to semantic clusters
    for keyword, words in semantic_db.items():
        if keyword in definition_lower:
            candidates.update(words)
    
    # Strategy 2: Query DuckDuckGo instant answer API (no auth required)
    try:
        import urllib.parse
        query = f"define {definition_text}"
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            # DuckDuckGo returns InstantAnswer in AbstractText if available
            if data.get("AbstractText"):
                abstract = data["AbstractText"].lower()
                # Try to extract candidate words from the answer
                words_in_abstract = re.findall(r'\b[a-z]{3,10}\b', abstract)
                candidates.update(words_in_abstract[:3])
    except Exception:
        pass
    
    # Strategy 3: Try to parse definition for common word patterns
    # E.g., "transmission of energy" -> extract "transmission", "energy" as key tokens
    try:
        tokens = re.findall(r'\b[a-z]{3,}\b', definition_lower)
        # Expand short tokens to related words
        token_expansions = {
            "transmission": ["wave", "signal", "beam"],
            "energy": ["wave", "light", "power", "force"],
            "space": ["wave", "signal", "void"],
            "movement": ["wave", "pulse", "motion"],
            "grow": ["potential", "seed", "growth"],
            "plant": ["seed", "coconut", "growth"],
            "tropical": ["coconut", "island", "beach"],
            "capable": ["potential", "capacity"],
            "becoming": ["potential", "growth"],
            "achieving": ["potential", "success"],
        }
        for token in tokens:
            if token in token_expansions:
                candidates.update(token_expansions[token])
    except Exception:
        pass
    
    stopwords = {
        "the", "and", "or", "but", "for", "with", "from", "into", "onto", "over",
        "under", "about", "after", "before", "during", "through", "within", "without",
        "this", "that", "these", "those", "there", "their", "they", "them", "you",
        "your", "yours", "his", "her", "its", "our", "ours", "is", "are", "was",
        "were", "be", "been", "being", "am", "a", "an", "of", "to", "in", "on",
        "as", "at", "by", "it", "i", "we", "can", "could", "would", "should",
        "may", "might", "will", "shall", "not", "no", "yes", "if", "then", "than",
        "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
        "more", "most", "less", "few", "many", "all", "any", "some",
    }

    filtered_candidates = []
    seen = set()
    for candidate in sorted(list(candidates)):
        normalized = candidate.strip().lower()
        if not normalized or normalized in stopwords or len(normalized) < 3:
            continue
        if normalized not in seen:
            seen.add(normalized)
            filtered_candidates.append(normalized)

    # Deduplicate and limit to max_results
    result = filtered_candidates[:max_results]
    return result


@tool("definition_lookup_tool")
def definition_lookup_tool(definition_text: str) -> str:
    """
    Tool wrapper for definition_lookup that returns JSON.
    
    When the planner or solver needs to reverse-engineer a word from its definition,
    this tool queries multiple sources to find candidate words.
    
    Args:
        definition_text: The definition or clue text (e.g., "transmission of energy through space")
        
    Returns:
        JSON with "definition", "candidates", and "confidence" fields
    """
    candidates = definition_lookup(definition_text, max_results=8)
    return json.dumps({
        "definition": definition_text,
        "candidates": candidates,
        "count": len(candidates),
        "method": "semantic_clustering + duckduckgo_api + token_expansion"
    }, ensure_ascii=False, indent=2)


@tool("discover_target_surface")
def discover_target_surface(target_url: str = "") -> str:
    """Report the configured target service surface.

    Final campaigns normally use target profiles, so the default behavior avoids
    redundant OPTIONS/GET/empty POST probes. Set TARGET_SURFACE_ACTIVE_PROBES=1
    to re-enable the legacy probing behavior for unknown custom deployments.
    """
    target_url = (target_url or TARGET_CHAT_URL).rstrip("/")
    findings = [
        "## Target Surface Discovery\n",
        f"**Target App:** {TARGET_APP}\n",
        f"**Base URL:** {get_target_base_url()}\n",
        f"**Chat URL:** {target_url}\n",
        f"**Health URL:** {TARGET_HEALTH_URL}\n",
        f"**Enhanced Chat URL:** {TARGET_ENHANCED_CHAT_URL}\n",
        f"**History URL:** {TARGET_HISTORY_URL}\n",
        f"**Request Format:** {TARGET_REQUEST_FORMAT}\n",
        f"**Request Field:** {TARGET_REQUEST_FIELD}\n",
        f"**Auth Mode:** {TARGET_AUTH_MODE}\n",
        f"**Auth Required:** {target_auth_is_required()}\n",
        f"**Attack Strategy:** {ATTACK_STRATEGY.get('name', get_target_attack_strategy())}\n",
    ]

    if os.getenv("TARGET_SURFACE_ACTIVE_PROBES", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        findings.append("**Active Probes:** skipped; configured target profile is being used.\n")
        return "".join(findings)

    findings.append("**Active Probes:** enabled by TARGET_SURFACE_ACTIVE_PROBES.\n")
    headers = _target_headers()

    try:
        options_response = requests.options(target_url, headers=headers, timeout=5)
        allow_header = options_response.headers.get("Allow")
        if allow_header:
            findings.append(f"**Allowed Methods:** {allow_header}\n")
    except requests.RequestException:
        pass

    try:
        get_response = requests.get(target_url, headers=headers, timeout=5)
        findings.append(f"**GET Status:** {get_response.status_code}\n")
        findings.append(f"**GET Content-Type:** {get_response.headers.get('Content-Type', 'Unknown')}\n")
        try:
            get_json = get_response.json()
            if isinstance(get_json, dict):
                findings.append(f"**GET JSON Keys:** {', '.join(list(get_json.keys())[:10])}\n")
        except Exception:
            findings.append(f"**GET Preview:** {get_response.text[:150].replace(chr(10), ' ')}\n")
    except requests.RequestException as exc:
        return f"Cannot reach {target_url}: {exc}"

    try:
        post_response = requests.post(target_url, json={}, headers=headers, timeout=5)
        findings.append(f"**POST Empty JSON Status:** {post_response.status_code}\n")
        try:
            post_json = post_response.json()
            if isinstance(post_json, dict):
                findings.append(f"**POST JSON Keys:** {', '.join(list(post_json.keys())[:10])}\n")
                if "job_id" in post_json or "job_uuid" in post_json:
                    findings.append("**Behavior:** async job-based response\n")
                if "response" in post_json or "message" in post_json:
                    findings.append("**Behavior:** direct response payload\n")
        except Exception:
            findings.append(f"**POST Preview:** {post_response.text[:150].replace(chr(10), ' ')}\n")
    except requests.RequestException:
        pass

    return "".join(findings)


@tool("infer_target_schema")
def infer_target_schema(target_url: str = "", field_names: str = "message,query,input,prompt,text,content") -> str:
    """Probe a target to discover which request field names it accepts.

    The tool sends safe test payloads with common field names and reports which
    ones are accepted. This helps the planner adapt to target-specific request
    contracts without hardcoding a single schema.
    """
    target_url = (target_url or TARGET_CHAT_URL).rstrip("/")
    candidates = [name.strip() for name in field_names.split(",") if name.strip()]
    results = [f"## Target Schema Inference\n", f"**Target URL:** {target_url}\n"]
    headers = _target_headers()

    for field_name in candidates:
        try:
            response = requests.post(target_url, json={field_name: "test"}, headers=headers, timeout=5)
            if response.status_code in {200, 201, 202}:
                results.append(f"**Accepted field:** {field_name} (HTTP {response.status_code})\n")
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        results.append(f"**Response keys:** {', '.join(list(payload.keys())[:10])}\n")
                except Exception:
                    results.append(f"**Response preview:** {response.text[:120].replace(chr(10), ' ')}\n")
            else:
                results.append(f"**Rejected field:** {field_name} (HTTP {response.status_code})\n")
        except requests.RequestException as exc:
            results.append(f"**Error for field {field_name}:** {exc}\n")

    return "".join(results)


@tool("analyze_target_behavior")
def analyze_target_behavior(target_url: str = "", test_prompts: str = "hello|help|test|who are you|what can you do", field_name: str = "") -> str:
    """Send benign prompts to characterize response shape, timing, and output style."""
    target_url = (target_url or TARGET_CHAT_URL).rstrip("/")
    field_name = field_name.strip() or TARGET_REQUEST_FIELD
    prompts = [prompt.strip() for prompt in test_prompts.split("|") if prompt.strip()]
    report = [f"## Target Behavior Analysis\n", f"**Target URL:** {target_url}\n", f"**Field Name:** {field_name}\n"]
    headers = _target_headers()

    response_times = []
    samples = []

    for prompt in prompts:
        try:
            start = time.time()
            response = requests.post(target_url, json={field_name: prompt}, headers=headers, timeout=15)
            elapsed = time.time() - start
            response_times.append(elapsed)
            report.append(f"**Prompt:** {prompt} -> HTTP {response.status_code} in {elapsed:.2f}s\n")
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    for key in ("response", "message", "output", "result", "text"):
                        if key in payload:
                            samples.append(f"{prompt} -> {str(payload[key])[:120]}")
                            break
            except Exception:
                samples.append(f"{prompt} -> {response.text[:120].replace(chr(10), ' ')}")
        except requests.RequestException as exc:
            report.append(f"**Prompt:** {prompt} -> ERROR {exc}\n")

    if response_times:
        report.append(f"**Average Response Time:** {sum(response_times) / len(response_times):.2f}s\n")
        report.append(f"**Max Response Time:** {max(response_times):.2f}s\n")

    if samples:
        report.append("\n### Samples\n")
        report.extend([f"- {sample}\n" for sample in samples])

    return "".join(report)


@tool("scan_target_misconfigurations")
def scan_target_misconfigurations(target_url: str = "") -> str:
    """Non-destructively check for obvious security misconfigurations."""
    target_url = (target_url or TARGET_CHAT_URL).rstrip("/")
    base_url = get_target_base_url() if target_url == TARGET_CHAT_URL else target_url.rsplit("/", 1)[0]
    findings = [f"## Misconfiguration Scan\n", f"**Target:** {base_url}\n"]
    headers = _target_headers({"Origin": "https://attacker.example.com"})

    debug_paths = ["/debug", "/__debug__", "/_debug", "/admin", "/api/debug", "/metrics", "/prometheus"]
    exposed = []
    for path in debug_paths:
        try:
            response = requests.get(base_url + path, headers=headers, timeout=3)
            if response.status_code != 404:
                exposed.append(f"{path} (HTTP {response.status_code})")
        except requests.RequestException:
            pass

    if exposed:
        findings.append("**Potential Exposed Endpoints:**\n")
        findings.extend([f"- {item}\n" for item in exposed])
    else:
        findings.append("**Potential Exposed Endpoints:** none detected\n")

    try:
        response = requests.options(base_url, headers=headers, timeout=3)
        cors_origin = response.headers.get("Access-Control-Allow-Origin")
        if cors_origin:
            findings.append(f"**CORS Origin:** {cors_origin}\n")
    except requests.RequestException:
        pass

    return "".join(findings)

@tool("query_red_teaming_tools_knowledge")
def tool_knowledge_rag(query: str) -> str:
    """Search the local documentation corpus for red-teaming guidance.

    The planner uses this tool to ground its attack plan in the docs that were
    ingested from Promptfoo, PyRIT, and related documentation sources. The tool
    returns the retrieved text directly so the model can reason over the content
    without needing to know anything about Chroma or embeddings.
    """
    return rag_search_knowledge(query)


@tool("load_skill")
def load_skill(skill_path: str = "skills/gandalf/SKILL.md") -> str:
    """Load a skill markdown file from the local skills directory.

    The loader is intentionally constrained to the repository's skills folder so
    the planner can safely ingest a skill spec without turning the tool into a
    general file reader.
    """
    try:
        resolved_path = _resolve_existing_skill_path([skill_path, *GANDALF_SKILL_CANDIDATES])
    except Exception as exc:
        return f"Error resolving skill path {skill_path}: {exc}"

    try:
        with open(resolved_path, "r", encoding="utf-8") as skill_file:
            return skill_file.read()
    except Exception as exc:
        return f"Error reading skill file at {resolved_path}: {exc}"


@tool("register_gandalf_agent")
def register_gandalf_agent(agent_name: str = "", description: str = "") -> str:
    """Register an agent with Gandalf and return the token payload.

    This tool makes the authentication step explicit for the planner so the
    model can treat token acquisition as a required precondition before any
    level requests are attempted.
    """
    base_url = _gandalf_api_base()
    resolved_agent_name = agent_name.strip() or f"gandalf_agent_{uuid.uuid4().hex[:8]}"
    resolved_description = description.strip() or "Automated Gandalf CTF agent"

    session = requests.Session()
    try:
        registration = _register_gandalf_agent(session, base_url, resolved_agent_name, resolved_description)
        payload = {
            "base_url": base_url,
            "agent_name": registration["agent_name"],
            "token": registration["token"],
            "authorization_header": f"Bearer {registration['token']}",
            "registration": registration["registration"],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Gandalf registration failed: {exc}"
    finally:
        session.close()


def _gandalf_api_base() -> str:
    return os.getenv("GANDALF_API_BASE", "https://gandalf-api.lakera.ai").rstrip("/")


def _gandalf_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_gandalf_agent(session: requests.Session, base_url: str, agent_name: str, description: str) -> dict:
    register_url = f"{base_url}/api/agent-ctf/register"
    payload = {"agent_name": agent_name, "description": description}
    print(f"--> [Gandalf] Registering agent at {register_url} as {agent_name}")
    response = session.post(register_url, json=payload, timeout=15)
    if response.status_code == 409:
        agent_name = f"{agent_name}-{uuid.uuid4().hex[:6]}"
        payload["agent_name"] = agent_name
        print(f"--> [Gandalf] Agent name collision, retrying as {agent_name}")
        response = session.post(register_url, json=payload, timeout=15)
    print(f"--> [Gandalf] Register response status: {response.status_code}")
    if response.status_code >= 400:
        print(f"--> [Gandalf] Register response headers: {dict(response.headers)}")
        print(f"--> [Gandalf] Register response body: {response.text}")
    response.raise_for_status()
    data = response.json()
    print(f"--> [Gandalf] Register response JSON: {data}")
    token = (
        data.get("token")
        or data.get("access_token")
        or data.get("key")
        or data.get("api_key")
        or (data.get("data") or {}).get("token")
        or (data.get("data") or {}).get("key")
    )
    if not token:
        raise RuntimeError(f"Registration response did not include a token: {data}")
    return {"agent_name": agent_name, "token": token, "registration": data}


@tool("gandalf_level_executor")
def gandalf_level_executor(level_number: int, prompt: str, token: str) -> str:
    """Send a single prompt to a Gandalf CTF level and return the defender response.

    This tool is called by the executor for each prompt at each level. It returns
    the raw defender response so the executor can parse it and decide on a guess.
    """
    base_url = _gandalf_api_base()
    headers = _gandalf_headers(token)
    chat_url = f"{base_url}/api/agent-ctf/levels/{level_number}/chat"
    
    try:
        print(f"--> [Gandalf] Sending prompt to level {level_number}: {prompt[:80]}...")
        response = requests.post(chat_url, headers=headers, json={"message": prompt}, timeout=15)
        response.raise_for_status()
        data = response.json()
        print(f"--> [Gandalf] Level {level_number} response status: {response.status_code}")
        return json.dumps({"level": level_number, "prompt": prompt, "defender_response": data}, ensure_ascii=False, indent=2)
    except requests.RequestException as exc:
        return f"Gandalf level {level_number} prompt failed: {exc}"
    except Exception as exc:
        return f"Gandalf level {level_number} prompt error: {exc}"


@tool("gandalf_guess_generator")
def gandalf_guess_generator(defender_response_json: str, level_number: int, token: str) -> str:
    """Parse a defender response and generate a guess for the secret.

    This tool analyzes the defender's message from the chat endpoint and attempts
    to extract or infer the secret password. It returns a structured JSON with
    the generated guess and any clues found in the response.
    """
    try:
        return json.dumps(
            _gandalf_guess_from_response(defender_response_json, level_number),
            ensure_ascii=False,
            indent=2,
        )
    except Exception as exc:
        return f"Guess generation failed for level {level_number}: {exc}"


def _gandalf_guess_from_response(defender_response_json: str, level_number: int) -> dict:
    """Extract candidate secrets from a Gandalf response payload.

    This helper is pure Python so gandalf_game.py can use the same heuristic
    without trying to call the CrewAI Tool object directly.
    """
    response_data = json.loads(defender_response_json) if isinstance(defender_response_json, str) else defender_response_json
    if not isinstance(response_data, dict):
        response_data = {"raw": str(response_data)}

    defender_message = (
        response_data.get("defender_response")
        or response_data.get("message")
        or response_data.get("response")
        or response_data.get("text")
        or str(response_data)
    )

    import re

    potential_secrets = []
    quoted = re.findall(r'["\']([^"\']+)["\']', defender_message)
    potential_secrets.extend(quoted)
    caps_words = re.findall(r'\b([A-Z]{3,})\b', defender_message)
    potential_secrets.extend(caps_words)
    keyword_hits = re.findall(r'\b(secret|password|token|key|code|name)\b', defender_message, flags=re.IGNORECASE)
    potential_secrets.extend(keyword_hits)

    potential_secrets = [item.strip() for item in dict.fromkeys(potential_secrets) if item and item.strip()]
    primary_guess = potential_secrets[0] if potential_secrets else "UNKNOWN"

    print(f"--> [Gandalf] Level {level_number} guess candidates: {potential_secrets[:3]}")
    return {
        "level": level_number,
        "defender_message": defender_message[:300],
        "potential_secrets": potential_secrets[:5],
        "primary_guess": primary_guess,
    }


@tool("execute_gandalf_attack")
def gandalf_executor(plan_json: str) -> str:
    """Execute a Gandalf CTF plan against Lakera's agent-CTF API.

    The planner provides a JSON payload describing the target base URL, the
    skill file to load, the prompts to try, and optional guess candidates. This
    tool handles registration, level enumeration, prompt execution, and optional
    guesses while keeping the attack flow rate-limited and observable.
    """
    plan = _load_jsonish_payload(plan_json)
    if not isinstance(plan, dict):
        return "Gandalf execution aborted: planner payload could not be parsed as JSON."

    base_url = str(plan.get("base_url") or _gandalf_api_base()).rstrip("/")
    skill_path = str(plan.get("skill_path") or os.getenv("GANDALF_SKILL_PATH", "skills/gandalf-ctf/SKILL.md"))
    agent_name = str(plan.get("agent_name") or os.getenv("GANDALF_AGENT_NAME") or f"gandalf_agent_{uuid.uuid4().hex[:8]}")
    description = str(plan.get("description") or os.getenv("GANDALF_AGENT_DESCRIPTION") or "Automated Gandalf CTF agent")
    prompts_text = str(plan.get("prompts_text") or plan.get("prompts") or "")
    guess_candidates_text = str(plan.get("guess_candidates_text") or plan.get("guess_candidates") or "")
    max_levels = int(plan.get("max_levels") or os.getenv("GANDALF_MAX_LEVELS", "8"))

    skill_text = load_skill(skill_path)
    if skill_text.startswith("Error:"):
        return f"Gandalf execution aborted: {skill_text}"

    prompts = [prompt.strip() for prompt in prompts_text.split("|") if prompt.strip()]
    guess_candidates = [guess.strip() for guess in guess_candidates_text.split("|") if guess.strip()]

    if not prompts:
        return "Gandalf execution aborted: no prompts were provided in prompts_text."

    session = requests.Session()
    summary = {
        "base_url": base_url,
        "skill_path": str(_resolve_skill_path(skill_path)),
        "skill_preview": skill_text[:600],
        "agent_name": agent_name,
        "max_levels": max_levels,
        "levels": [],
    }

    try:
        token = plan.get("token")

        if not token:
            registration = _register_gandalf_agent(session, base_url, agent_name, description)
            token = registration["token"]
            summary["agent_name"] = registration["agent_name"]

        headers = _gandalf_headers(token)

        levels_url = f"{base_url}/api/agent-ctf/levels"
        levels_response = session.get(levels_url, headers=headers, timeout=15)
        levels_response.raise_for_status()
        levels_payload = levels_response.json()
        summary["levels_overview"] = levels_payload

        available_levels = levels_payload.get("levels", levels_payload if isinstance(levels_payload, list) else [])
        unlocked_levels = []
        for level in available_levels:
            level_number = level.get("level") or level.get("id") or level.get("number")
            status = str(level.get("status", "")).lower()
            if level_number is None:
                continue
            if status in {"unlocked", "open", "available"} or not status:
                unlocked_levels.append(int(level_number))

        if not unlocked_levels:
            unlocked_levels = list(range(1, max_levels + 1))

        for level_number in unlocked_levels[:max_levels]:
            level_entry = {"level": level_number, "prompts": []}
            chat_url = f"{base_url}/api/agent-ctf/levels/{level_number}/chat"
            guess_url = f"{base_url}/api/agent-ctf/levels/{level_number}/guess"

            for prompt in prompts:
                try:
                    chat_response = session.post(chat_url, headers=headers, json={"message": prompt}, timeout=15)
                    chat_payload = chat_response.json()
                    level_entry["prompts"].append({
                        "prompt": prompt,
                        "status_code": chat_response.status_code,
                        "response": chat_payload,
                    })

                    if guess_candidates:
                        for candidate in guess_candidates:
                            guess_response = session.post(guess_url, headers=headers, json={"secret": candidate}, timeout=15)
                            guess_payload = guess_response.json()
                            level_entry.setdefault("guesses", []).append({
                                "candidate": candidate,
                                "status_code": guess_response.status_code,
                                "response": guess_payload,
                            })
                            if isinstance(guess_payload, dict) and guess_payload.get("correct") is True:
                                level_entry["completed"] = True
                                break
                        if level_entry.get("completed"):
                            break
                except requests.RequestException as exc:
                    level_entry.setdefault("errors", []).append(str(exc))

                time.sleep(float(ATTACK_STRATEGY.get("inter_prompt_delay", DEFAULT_ATTACK_STRATEGY["inter_prompt_delay"])))

            summary["levels"].append(level_entry)

        return json.dumps(summary, ensure_ascii=False, indent=2)

    except requests.RequestException as exc:
        return f"Gandalf execution failed: {exc}"
    except Exception as exc:
        return f"Gandalf execution failed: {exc}"
    finally:
        session.close()

# The following tools turn a plan into actual traffic against the target service.
# Both are intentionally verbose so the agent can capture the full raw output and
# hand it back to the reporting stage.

@tool("execute_promptfoo_attack")
def promptfoo_tool(prompts_text: str) -> str:
    """Execute a Promptfoo-style attack against the target chatbot.

    The planner hands this tool a pipe-delimited string of prompts. This function
    can run in two modes:

    * a direct HTTP mode that posts prompts sequentially and polls the job API, or
    * an external Promptfoo CLI mode that generates a temporary config file and
      runs the real Promptfoo launcher.

    The direct mode is the default because it is more predictable in constrained
    environments and produces logs that are easier to read in the final report.
    """
    print(f"\n--> [Promptfoo] Attacking FastAPI Agent with dynamic payloads...")

    # Split the planner's pipe-delimited payload into individual prompts.
    malicious_prompts = [p.strip() for p in prompts_text.split('|') if p.strip()]

    if not malicious_prompts:
        return "Promptfoo execution aborted: no prompts were provided in prompts_text."

    # Never send attack traffic if the target service is already down.
    health_url = TARGET_HEALTH_URL
    try:
        health_response = requests.get(health_url, headers=_target_headers(), timeout=5)
        health_response.raise_for_status()
    except requests.RequestException as e:
        return (
            "Promptfoo execution aborted: target health preflight failed. "
            f"chat_url={TARGET_CHAT_URL}, health_url={health_url}, error={str(e)}"
        )

    # Use direct sequential POSTs with pacing by default. Set USE_PROMPTFOO=1 to run the external promptfoo tool instead.
    use_promptfoo = os.getenv("USE_PROMPTFOO", "0") == "1"

    if not use_promptfoo:
        # Direct mode keeps control inside Python and makes each request easier to trace.
        delay = float(ATTACK_STRATEGY.get("inter_prompt_delay", DEFAULT_ATTACK_STRATEGY["inter_prompt_delay"]))
        connect_timeout = int(ATTACK_STRATEGY.get("connect_timeout", DEFAULT_ATTACK_STRATEGY["connect_timeout"]))
        per_request_timeout = int(ATTACK_STRATEGY.get("request_timeout", DEFAULT_ATTACK_STRATEGY["request_timeout"]))
        poll_interval = float(ATTACK_STRATEGY.get("poll_interval", DEFAULT_ATTACK_STRATEGY["poll_interval"]))
        job_timeout = int(ATTACK_STRATEGY.get("job_timeout", DEFAULT_ATTACK_STRATEGY["job_timeout"]))
        max_retries = int(ATTACK_STRATEGY.get("max_retries", DEFAULT_ATTACK_STRATEGY["max_retries"]))
        timeout_multiplier = float(ATTACK_STRATEGY.get("retry_timeout_multiplier", DEFAULT_ATTACK_STRATEGY["retry_timeout_multiplier"]))
        retry_backoff = float(ATTACK_STRATEGY.get("retry_backoff", DEFAULT_ATTACK_STRATEGY["retry_backoff"]))
        timeout_threshold = int(ATTACK_STRATEGY.get("consecutive_timeout_threshold", DEFAULT_ATTACK_STRATEGY["consecutive_timeout_threshold"]))
        timeout_cooldown = float(ATTACK_STRATEGY.get("timeout_cooldown", DEFAULT_ATTACK_STRATEGY["timeout_cooldown"]))
        health_check_timeout = int(ATTACK_STRATEGY.get("health_check_timeout", DEFAULT_ATTACK_STRATEGY["health_check_timeout"]))
        retry_action_prompts = bool(ATTACK_STRATEGY.get("retry_action_prompts", DEFAULT_ATTACK_STRATEGY["retry_action_prompts"]))

        print(
            f"--> [Promptfoo-Mode] Strategy={ATTACK_STRATEGY.get('name', 'custom')}; "
            f"posting {len(malicious_prompts)} prompts sequentially with {delay}s delay, "
            f"{per_request_timeout}s read timeout, and up to {max_retries} retry/retries to {TARGET_CHAT_URL}"
        )
        results = []
        consecutive_timed_out_prompts = 0

        with requests.Session() as session:
            for idx, p in enumerate(malicious_prompts, start=1):
                request_kwargs = _build_request_kwargs(p)
                state_changing = _is_potentially_state_changing_prompt(p)
                allowed_retries = max_retries if retry_action_prompts or not state_changing else 0
                attempts = []
                final_entry = None

                for attempt_index in range(allowed_retries + 1):
                    attempt_number = attempt_index + 1
                    read_timeout = max(1, round(per_request_timeout * (timeout_multiplier ** attempt_index)))
                    try:
                        # A timeout tuple keeps connection failures distinct from slow target processing.
                        response = session.post(
                            TARGET_CHAT_URL,
                            timeout=(connect_timeout, read_timeout),
                            **request_kwargs,
                        )
                        response_body = _safe_response_body(response)
                        job_id = response_body.get("job_id") if isinstance(response_body, dict) else None
                        job_data = response_body

                        if job_id:
                            # Poll an accepted job without resubmitting it, avoiding duplicate actions.
                            job_url = _build_job_url(TARGET_CHAT_URL, job_id)
                            started_at = time.time()
                            while time.time() - started_at < job_timeout:
                                try:
                                    status_response = session.get(
                                        job_url,
                                        headers=_target_headers(),
                                        timeout=(connect_timeout, read_timeout),
                                    )
                                except (requests.ReadTimeout, requests.ConnectTimeout) as poll_exc:
                                    job_data = {
                                        "job_id": job_id,
                                        "status": "poll_timeout",
                                        "outcome": "TIMEOUT_INCONCLUSIVE",
                                        "error": str(poll_exc),
                                    }
                                    break
                                job_data = _safe_response_body(status_response)
                                if isinstance(job_data, dict) and job_data.get("status") in {"finished", "failed"}:
                                    break
                                time.sleep(poll_interval)

                        attempts.append({
                            "attempt": attempt_number,
                            "read_timeout_seconds": read_timeout,
                            "status_code": response.status_code,
                        })
                        final_entry = {
                            "prompt_index": idx,
                            "prompt": p,
                            "status_code": response.status_code,
                            "response": job_data,
                            "attempts": attempts,
                        }
                        consecutive_timed_out_prompts = 0
                        print(
                            f"--> [Promptfoo-Mode] Sent prompt {idx}/{len(malicious_prompts)} "
                            f"on attempt {attempt_number}: status={response.status_code}"
                        )
                        break
                    except requests.ReadTimeout as exc:
                        attempts.append({
                            "attempt": attempt_number,
                            "read_timeout_seconds": read_timeout,
                            "error_type": "read_timeout",
                            "error": str(exc),
                        })
                        if attempt_index < allowed_retries:
                            backoff = retry_backoff * (2 ** attempt_index)
                            print(
                                f"--> [Promptfoo-Mode] Prompt {idx} timed out after {read_timeout}s; "
                                f"waiting {backoff}s before retry {attempt_number + 1}."
                            )
                            time.sleep(backoff)
                            attempts[-1]["health_check"] = _probe_target_health(session, health_check_timeout)
                            continue

                        final_entry = {
                            "prompt_index": idx,
                            "prompt": p,
                            "error": str(exc),
                            "error_type": "read_timeout",
                            "outcome": "TIMEOUT_INCONCLUSIVE",
                            "attempts": attempts,
                        }
                        if state_changing and not retry_action_prompts:
                            final_entry["retry_skipped_reason"] = (
                                "Prompt may change server state; automatic retry could duplicate an action."
                            )
                        consecutive_timed_out_prompts += 1
                        print(f"--> [Promptfoo-Mode] Prompt {idx} exhausted its timeout attempts.")
                    except requests.ConnectTimeout as exc:
                        final_entry = {
                            "prompt_index": idx,
                            "prompt": p,
                            "error": str(exc),
                            "error_type": "connect_timeout",
                            "outcome": "TIMEOUT_INCONCLUSIVE",
                            "attempts": attempts + [{
                                "attempt": attempt_number,
                                "connect_timeout_seconds": connect_timeout,
                                "error_type": "connect_timeout",
                                "error": str(exc),
                            }],
                        }
                        consecutive_timed_out_prompts += 1
                        print(f"--> [Promptfoo-Mode] Could not connect for prompt {idx}: {exc}")
                        break
                    except requests.RequestException as exc:
                        final_entry = {
                            "prompt_index": idx,
                            "prompt": p,
                            "error": str(exc),
                            "error_type": "request_error",
                            "outcome": "ERROR",
                            "attempts": attempts,
                        }
                        consecutive_timed_out_prompts = 0
                        print(f"--> [Promptfoo-Mode] Error sending prompt {idx}: {exc}")
                        break

                results.append(final_entry)

                if timeout_threshold > 0 and consecutive_timed_out_prompts >= timeout_threshold:
                    print(
                        f"--> [Promptfoo-Mode] {consecutive_timed_out_prompts} consecutive prompts timed out; "
                        f"cooling down for {timeout_cooldown}s."
                    )
                    time.sleep(timeout_cooldown)
                    cooldown_health = _probe_target_health(session, health_check_timeout)
                    results[-1]["post_cooldown_health_check"] = cooldown_health
                    consecutive_timed_out_prompts = 0

                # Throttle every request boundary so a timed-out server task gets recovery time too.
                if idx < len(malicious_prompts):
                    time.sleep(delay)

        return json.dumps({"target": TARGET_CHAT_URL, "results": results}, ensure_ascii=False, indent=2)

    # External Promptfoo mode writes a temporary config file so the CLI can run.
    # This is useful when a user wants the actual Promptfoo output instead of the
    # simpler direct HTTP orchestration above.
    config_data = {
        "prompts": ["{{prompt}}"],
        "tests": [{"vars": {"prompt": p}} for p in malicious_prompts],
        "providers": [{
            "id": "http",
            "config": {
                "url": TARGET_CHAT_URL,
                "method": "POST",
                "headers": _target_headers({"Content-Type": "application/json"}),
                "body": _build_request_payload("{{prompt}}")
            }
        }]
    }

    temp_config_path = None
    try:
        print(f"--> [Promptfoo] Using target URL: {TARGET_CHAT_URL}")
        print(f"--> [Promptfoo] Prompt count: {len(malicious_prompts)}")

        # Save the generated config as JSON so the CLI can consume it.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as temp_config:
            json.dump(config_data, temp_config)
            temp_config_path = temp_config.name

        command = _build_promptfoo_command(temp_config_path)
        print(f"--> [Promptfoo] Command: {' '.join(command)}")

        env = os.environ.copy()
        # Keep the subprocess non-interactive so it cannot hang waiting for input.
        env.setdefault("CI", "1")
        env.setdefault("PROMPTFOO_DISABLE_TELEMETRY", "1")

        # Force UTF-8 so prompts and output are stable across Windows locales.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            encoding='utf-8',
            timeout=180,
            env=env,
        )

        output = result.stdout if result.stdout else result.stderr
        return (
            "Promptfoo execution complete. "
            f"return_code={result.returncode}, "
            f"target_url={TARGET_CHAT_URL}\n"
            f"Raw Output:\n{output}"
        )
    except subprocess.TimeoutExpired as e:
        partial_output = (e.stdout or "") + (e.stderr or "")
        return (
            "Promptfoo execution failed: timed out after 180 seconds. "
            f"target_url={TARGET_CHAT_URL}\n"
            f"Partial Output:\n{partial_output}"
        )
    except Exception as e:
        return f"Promptfoo execution failed: {str(e)}"
    finally:
        if temp_config_path and os.path.exists(temp_config_path):
            os.remove(temp_config_path)

