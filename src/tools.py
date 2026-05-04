"""
Red Teaming Tools Module

This module provides the CrewAI tools and helper functions for the red teaming framework:

CREWAI TOOLS (exposed to agents via @tool decorator):
1. tool_knowledge_rag: RAG-based knowledge lookup for red teaming strategies
2. discover_target_surface: Probes target endpoints to infer API schema and request format
3. promptfoo_tool: Runs HTTP-based attacks using the Promptfoo framework or direct HTTP
4. pyrit_tool: PyRIT-based automated red teaming for LLM-specific jailbreaks

HELPER FUNCTIONS (internal utilities):
- URL builders: _build_job_url, _build_health_url
- Probing: _safe_get_probe, _unique_urls, _split_target_url
- OpenAPI parsing: _extract_openapi_candidates, _infer_request_key, _score_candidate
- Prompt parsing: _coerce_prompts
- Process execution: _build_promptfoo_command

The module is designed to be flexible and extensible, supporting multiple attack frameworks
while maintaining a consistent interface through CrewAI's tool system.
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import textwrap
import time
import requests
from urllib.parse import urlparse
from crewai.tools import tool
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

# Target endpoint configuration (can be overridden via env var)
TARGET_CHAT_URL = os.getenv("TARGET_CHAT_URL", "http://127.0.0.1:8000/chat")


def _build_job_url(chat_url: str, job_id: str) -> str:
    """
    Constructs the job status polling URL from the chat endpoint and job ID.
    
    Given a chat URL like http://localhost:8000/chat, derives the root URL and
    appends the job ID to form the polling endpoint (e.g., /job/{job_id}).
    
    Args:
        chat_url: The main chat endpoint URL
        job_id: Unique job identifier returned by async endpoints
    
    Returns:
        Full URL for polling job status (e.g., http://localhost:8000/job/abc-123)
    """
    base_url = chat_url[:-5] if chat_url.endswith("/chat") else chat_url.rstrip("/")
    return f"{base_url}/job/{job_id}"


def _build_health_url(chat_url: str) -> str:
    """
    Derives the health check endpoint from the chat URL.
    
    Args:
        chat_url: The chat endpoint URL
    
    Returns:
        Health check endpoint URL (typically /health)
    """
    if chat_url.endswith("/chat"):
        return f"{chat_url[:-5]}/health"
    return f"{chat_url.rstrip('/')}/health"


def _unique_urls(urls: list[str]) -> list[str]:
    """
    Deduplicates a list of URLs while preserving order.
    
    Args:
        urls: List of URLs that may contain duplicates
    
    Returns:
        List of unique URLs in original order
    """
    seen = set()
    unique = []
    for url in urls:
        if url and url not in seen:
            unique.append(url)
            seen.add(url)
    return unique


def _split_target_url(target_url: str) -> tuple[str, str]:
    """
    Splits a target URL into root URL and path components.
    
    Args:
        target_url: Full target URL (e.g., http://localhost:8000/api/chat)
    
    Returns:
        Tuple of (root_url, path) where:
        - root_url is the scheme + netloc (e.g., http://localhost:8000)
        - path is the URL path (e.g., /api/chat)
    """
    parsed = urlparse(target_url.strip())
    root_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else target_url.rstrip("/")
    path = parsed.path.rstrip("/")
    return root_url, path


def _safe_get_probe(url: str, timeout: float = 4.0) -> dict:
    """
    Safely probes a URL for reachability and content type.
    
    Attempts a GET request to the URL with error handling. Returns both
    successful probes and failures so the caller can track which endpoints
    are reachable.
    
    Args:
        url: URL to probe
        timeout: Request timeout in seconds (default: 4.0)
    
    Returns:
        dict with keys:
        - ok: bool indicating success/failure
        - status_code: HTTP status code (if ok=True)
        - error: Exception message (if ok=False)
        - content_type: Content-Type header value
        - body_preview: First 500 chars of response body
        - json: Parsed JSON (if applicable)
    """
    try:
        response = requests.get(url, timeout=timeout)
        content_type = response.headers.get("content-type", "")
        body_preview = response.text[:500] if response.text else ""
        parsed_json = None
        if "application/json" in content_type.lower():
            try:
                parsed_json = response.json()
            except ValueError:
                parsed_json = None
        return {
            "url": url,
            "ok": True,
            "status_code": response.status_code,
            "content_type": content_type,
            "body_preview": body_preview,
            "json": parsed_json,
        }
    except requests.RequestException as exc:
        return {
            "url": url,
            "ok": False,
            "error": str(exc),
        }


def _infer_request_key(path: str, properties: dict | None) -> str:
    """
    Infers the field name for sending user input in HTTP requests.
    
    Uses heuristics based on URL path and OpenAPI schema properties:
    - Prefers standard keys: message, input, prompt, text, query, content, question
    - Falls back to first property key if available
    - Uses path analysis as last resort
    
    Args:
        path: URL path (e.g., /chat, /api/completion)
        properties: OpenAPI request body properties dict (if available)
    
    Returns:
        Inferred field name (e.g., "message", "input", "prompt")
    """
    preferred_keys = ["message", "input", "prompt", "text", "query", "content", "question"]
    if isinstance(properties, dict):
        for key in preferred_keys:
            if key in properties:
                return key
        if properties:
            return next(iter(properties.keys()))

    lowered_path = path.lower()
    if "chat" in lowered_path:
        return "message"
    if any(token in lowered_path for token in ["invoke", "run", "generate", "completion", "ask"]):
        return "input"
    return "message"


def _extract_openapi_candidates(openapi_doc: dict) -> list[dict]:
    """
    Extracts target-structure candidates from an OpenAPI document.
    
    Parses OpenAPI paths and operations to build candidate target-structure profiles,
    including:
    - Endpoint paths
    - HTTP methods
    - Request body templates
    - Polling requirements
    
    Args:
        openapi_doc: OpenAPI specification dict (e.g., from /openapi.json)
    
    Returns:
        List of candidate dicts, each containing:
        - endpoint_path: URL path
        - method: HTTP method
        - headers: Request headers
        - body_template: JSON template describing the request shape
        - poll: Polling configuration hint
        - notes: Operation description
    """
    candidates = []
    paths = openapi_doc.get("paths", {}) if isinstance(openapi_doc, dict) else {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"post", "put", "patch"} or not isinstance(operation, dict):
                continue

            request_body = operation.get("requestBody", {}) if isinstance(operation.get("requestBody"), dict) else {}
            content = request_body.get("content", {}) if isinstance(request_body.get("content"), dict) else {}
            json_content = content.get("application/json", {}) if isinstance(content.get("application/json"), dict) else {}
            schema = json_content.get("schema", {}) if isinstance(json_content.get("schema"), dict) else {}
            properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}

            request_key = _infer_request_key(path, properties)
            body_template: dict | list | str
            if "messages" in request_key.lower() or "chat/completions" in path:
                body_template = {"messages": [{"role": "user", "content": "{{prompt}}"}], "stream": False}
            else:
                body_template = {request_key: "{{prompt}}"}

            response_codes = operation.get("responses", {}) if isinstance(operation.get("responses"), dict) else {}
            response_schema_properties = {}
            for response in response_codes.values():
                if not isinstance(response, dict):
                    continue
                content = response.get("content", {}) if isinstance(response.get("content"), dict) else {}
                app_json = content.get("application/json", {}) if isinstance(content.get("application/json"), dict) else {}
                schema = app_json.get("schema", {}) if isinstance(app_json.get("schema"), dict) else {}
                response_schema_properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
                if response_schema_properties:
                    break

            poll_enabled = any(key in response_schema_properties for key in ["job_id", "status", "response", "result"])
            if any(token in path.lower() for token in ["job", "queue", "async", "task", "run"]):
                poll_enabled = True

            candidates.append({
                "endpoint_path": path,
                "method": method.upper(),
                "headers": {"Content-Type": "application/json"},
                "body_template": body_template,
                "poll": {
                    "enabled": poll_enabled,
                    "status_field": "status",
                    "response_field": "response",
                    "job_id_field": "job_id",
                },
                "notes": operation.get("summary") or operation.get("description") or "",
            })

    return candidates


def _score_candidate(candidate: dict) -> tuple[int, dict]:
    """
    Scores an OpenAPI candidate endpoint for suitability.
    
    Higher scores indicate endpoints more likely to be main AI/agent endpoints.
    Scoring criteria:
    - chat/completions endpoints: +50
    - chat in path: +25
    - invoke/generate/completion in path: +15
    - async/job/queue endpoints: +10
    - polling enabled: +5
    
    Args:
        candidate: Candidate dict from _extract_openapi_candidates
    
    Returns:
        Tuple of (score, candidate) for sorting
    """
    path = candidate.get("endpoint_path", "").lower()
    score = 0
    if "chat/completions" in path:
        score += 50
    if "chat" in path:
        score += 25
    if any(token in path for token in ["invoke", "generate", "completion", "respond", "ask"]):
        score += 15
    if any(token in path for token in ["job", "queue", "async", "task"]):
        score += 10
    if candidate.get("poll", {}).get("enabled"):
        score += 5
    return score, candidate


@tool("discover_target_surface")
def discover_target_surface(target_url: str) -> str:
    """
    Discovers and summarizes the target API surface for workflow planning.
    
    This tool probes the target endpoint to find:
    1. OpenAPI/Swagger documentation if available
    2. Health/status endpoints
    3. API root information
    4. Request and response schema
    5. Polling requirements for async targets
    
    Strategy:
    - Attempts multiple candidate URLs (OpenAPI, docs, health, etc.)
    - If OpenAPI found, extracts all POST/PUT/PATCH operations and scores them
    - Selects best candidate or falls back to heuristics
    - Returns a reusable target assessment with endpoint inventory and interface hints
    
    The returned JSON includes:
    - target_url: Original URL
    - root_url: Derived root URL
    - reachable_probes: Successful HTTP probes
    - failed_probes: Failed probes (for debugging)
    - openapi_detected: Whether OpenAPI was found
    - openapi_candidates: All candidates extracted from OpenAPI
    - target_assessment: Structured summary of the target surface
    - planning_context: Normalized entry point and request-shape hints for downstream planning
    
    Args:
        target_url: Target endpoint URL (e.g., http://localhost:8000/chat)
    
    Returns:
        JSON string with a reusable target assessment
    """
    if not target_url.strip():
        return json.dumps({"error": "No target_url was provided."}, ensure_ascii=False, indent=2)

    root_url, path = _split_target_url(target_url)
    probe_urls = _unique_urls([
        target_url.rstrip("/"),
        root_url,
        f"{root_url}/openapi.json",
        f"{root_url}/api/openapi.json",
        f"{root_url}/docs",
        f"{root_url}/redoc",
        f"{root_url}/health",
        f"{root_url}/api/docs",
        f"{root_url}/swagger.json",
    ])

    probes = [_safe_get_probe(url) for url in probe_urls]
    openapi_probe = next((probe for probe in probes if probe.get("ok") and isinstance(probe.get("json"), dict) and probe["json"].get("paths")), None)
    openapi_doc = openapi_probe.get("json") if openapi_probe else None
    openapi_candidates = _extract_openapi_candidates(openapi_doc) if isinstance(openapi_doc, dict) else []

    if openapi_candidates:
        scored_candidates = sorted((_score_candidate(candidate) for candidate in openapi_candidates), key=lambda item: item[0], reverse=True)
        best_candidate = scored_candidates[0][1]
    else:
        lowered_path = path.lower()
        if any(token in lowered_path for token in ["chat", "message"]):
            best_candidate = {
                "endpoint_path": path or "/chat",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body_template": {"message": "{{prompt}}"},
                "poll": {"enabled": False, "status_field": "status", "response_field": "response", "job_id_field": "job_id"},
                "notes": "Heuristic single-message chat endpoint",
            }
        else:
            best_candidate = {
                "endpoint_path": path or "/",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body_template": {"input": "{{prompt}}"},
                "poll": {"enabled": False, "status_field": "status", "response_field": "response", "job_id_field": "job_id"},
                "notes": "Heuristic generic HTTP endpoint",
            }

    entry_point = {
        "endpoint_path": best_candidate.get("endpoint_path"),
        "method": best_candidate.get("method", "POST"),
        "headers": best_candidate.get("headers", {"Content-Type": "application/json"}),
        "body_template": best_candidate.get("body_template", {"message": "{{prompt}}"}),
        "poll": best_candidate.get("poll", {"enabled": False, "status_field": "status", "response_field": "response", "job_id_field": "job_id"}),
        "notes": best_candidate.get("notes", ""),
    }

    target_assessment = {
        "target_url": target_url,
        "root_url": root_url,
        "path": path,
        "reachable_probes": [probe for probe in probes if probe.get("ok")],
        "failed_probes": [probe for probe in probes if not probe.get("ok")],
        "openapi_detected": bool(openapi_probe),
        "openapi_candidates": openapi_candidates,
        "interface_family": (
            "chat" if any(token in path.lower() for token in ["chat", "message"]) else
            "structured-http" if openapi_candidates else
            "generic-http"
        ),
        "entry_points": [entry_point],
        "planning_context": {
            "primary_entry_point": entry_point,
            "request_shape": entry_point["body_template"],
            "polling_required": bool(entry_point["poll"].get("enabled")),
        },
    }

    target_surface = {
        "target_url": target_url,
        "root_url": root_url,
        "assessment_summary": {
            "endpoint_count": len(openapi_candidates) if openapi_candidates else 1,
            "probe_count": len(probes),
            "polling_hint": bool(entry_point["poll"].get("enabled")),
        },
        "target_assessment": target_assessment,
        "planning_context": target_assessment["planning_context"],
    }
    return json.dumps(target_surface, ensure_ascii=False, indent=2)


def _coerce_prompts(raw_text: str) -> list[str]:
    """
    Parses prompts from various text formats.
    
    Supports:
    - Pipe-delimited strings: "prompt1|prompt2|prompt3"
    - JSON with "prompts" array: {"prompts": ["p1", "p2"]}
    - JSON with "prompts_text" field
    
    Args:
        raw_text: Raw prompt text in any supported format
    
    Returns:
        List of normalized prompt strings
    """
    stripped = raw_text.strip()
    if not stripped:
        return []

    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            prompts = parsed.get("prompts") or parsed.get("prompts_text") or []
            if isinstance(prompts, str):
                return [p.strip() for p in prompts.split("|") if p.strip()]
            if isinstance(prompts, list):
                return [str(p).strip() for p in prompts if str(p).strip()]

    return [p.strip() for p in stripped.split("|") if p.strip()]


def _build_promptfoo_command(config_path: str) -> list[str]:
    """
    Resolves the appropriate Promptfoo command for the current platform.
    
    Handles platform differences:
    - Unix: Uses promptfoo binary
    - Windows: Tries promptfoo.cmd, then promptfoo.ps1
    
    Args:
        config_path: Path to Promptfoo config file
    
    Returns:
        List of command arguments to pass to subprocess
    
    Raises:
        FileNotFoundError: If promptfoo is not found on PATH
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


# --- RAG Knowledge Base Initialization ---
# Loads Chroma vector database for red teaming knowledge retrieval
if os.path.exists("chroma_db"):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
    retriever = vector_store.as_retriever(search_kwargs={"k": 5})
else:
    retriever = None

@tool("query_red_teaming_tools_knowledge")
def tool_knowledge_rag(query: str) -> str:
    """
    Queries the RAG knowledge base for red teaming strategies and frameworks.
    
    This tool retrieves relevant documentation on red teaming approaches,
    frameworks like Promptfoo and PyRIT, and best practices for testing LLMs.
    
    The knowledge base is built from documentation in data/repos/ by ingest_knowledge.py
    and stored in a Chroma vector database.
    
    Args:
        query: Natural language question about red teaming techniques
               (e.g., "What are the best jailbreak techniques for Claude?")
    
    Returns:
        Formatted text with relevant sources and content excerpts
    
    Note:
        If chroma_db is not found, suggests running ingest_knowledge.py first.
    """
    if not retriever: return "Error: Chroma DB not found. Please run ingest_knowledge.py first."
    results = retriever.invoke(query)
    if not results: return "No relevant information found in the documentation."
    return "\n\n".join([f"Source: {doc.metadata.get('source', 'Unknown')}\nContent: {doc.page_content}" for doc in results])

# --- Execution Tools (With Windows/UTF-8 Fixes) ---

@tool("promptfoo_tool")
def promptfoo_tool(prompts_text: str) -> str:
    """
    Executes automated testing using Promptfoo framework against target endpoint.
    
    Promptfoo is a specialized LLM testing framework that can:
    - Send multiple payloads in parallel
    - Compare outputs across different models
    - Detect prompt injection vulnerabilities
    - Generate test reports
    
    This tool either:
    1. Uses the external Promptfoo CLI (if available and USE_PROMPTFOO=1)
    2. Implements direct sequential HTTP requests with proper job polling
    
    Args:
        prompts_text: Attack payloads in pipe-delimited format
                     (e.g., "payload1|payload2|payload3")
    
    Returns:
        JSON string with target URL and results array containing:
        - prompt_index: Sequential number
        - prompt: Actual payload sent
        - status_code: HTTP response code
        - response: Full response from target
        - error: Any error that occurred
    """
    print(f"\n--> [Promptfoo] Attacking FastAPI Agent with dynamic payloads...")

    malicious_prompts = _coerce_prompts(prompts_text)

    if not malicious_prompts:
        return "Promptfoo execution aborted: no prompts were provided in prompts_text."

    health_url = _build_health_url(TARGET_CHAT_URL)
    try:
        health_response = requests.get(health_url, timeout=5)
        health_response.raise_for_status()
    except requests.RequestException as e:
        return (
            "Promptfoo execution aborted: target health preflight failed. "
            f"chat_url={TARGET_CHAT_URL}, health_url={health_url}, error={str(e)}"
        )

    # Use direct sequential POSTs with pacing by default. Set USE_PROMPTFOO=1 to run the external promptfoo tool instead.
    use_promptfoo = os.getenv("USE_PROMPTFOO", "0") == "1"

    if not use_promptfoo:
        delay = float(os.getenv("INTER_PROMPT_DELAY", "1.0"))
        per_request_timeout = int(os.getenv("ATTACK_REQUEST_TIMEOUT", "15"))
        poll_interval = float(os.getenv("ATTACK_JOB_POLL_INTERVAL", "0.5"))
        job_timeout = int(os.getenv("ATTACK_JOB_TIMEOUT", "120"))

        print(f"--> [Promptfoo-Mode] Posting {len(malicious_prompts)} prompts sequentially with {delay}s delay to {TARGET_CHAT_URL}")
        results = []
        for idx, p in enumerate(malicious_prompts, start=1):
            try:
                payload = {"message": p}
                r = requests.post(TARGET_CHAT_URL, json=payload, timeout=per_request_timeout)
                response_body = r.json()
                job_id = response_body.get("job_id")
                job_data = response_body

                if job_id:
                    job_url = _build_job_url(TARGET_CHAT_URL, job_id)
                    started_at = time.time()
                    while time.time() - started_at < job_timeout:
                        status_response = requests.get(job_url, timeout=per_request_timeout)
                        job_data = status_response.json()
                        if job_data.get("status") in {"finished", "failed"}:
                            break
                        time.sleep(poll_interval)

                entry = {
                    "prompt_index": idx,
                    "prompt": p,
                    "status_code": r.status_code,
                    "response": job_data,
                }
                print(f"--> [Promptfoo-Mode] Sent prompt {idx}/{len(malicious_prompts)}: status={r.status_code}")
                results.append(entry)
            except requests.RequestException as e:
                results.append({"prompt_index": idx, "prompt": p, "error": str(e)})
                print(f"--> [Promptfoo-Mode] Error sending prompt {idx}: {str(e)}")
            # Throttle
            if idx < len(malicious_prompts):
                time.sleep(delay)

        return json.dumps({"target": TARGET_CHAT_URL, "results": results}, ensure_ascii=False, indent=2)

    # Build explicit test cases so each malicious prompt is guaranteed to be sent.
    config_data = {
        "prompts": ["{{prompt}}"],
        "tests": [{"vars": {"prompt": p}} for p in malicious_prompts],
        "providers": [{
            "id": "http",
            "config": {
                "url": TARGET_CHAT_URL,
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": {"message": "{{prompt}}"}
            }
        }]
    }

    temp_config_path = None
    try:
        print(f"--> [Promptfoo] Using target URL: {TARGET_CHAT_URL}")
        print(f"--> [Promptfoo] Prompt count: {len(malicious_prompts)}")

        # Save as a .json file, forcing utf-8
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as temp_config:
            json.dump(config_data, temp_config)
            temp_config_path = temp_config.name

        command = _build_promptfoo_command(temp_config_path)
        print(f"--> [Promptfoo] Command: {' '.join(command)}")

        env = os.environ.copy()
        # Disable interactive prompts/telemetry so subprocess cannot hang silently in CI-like runs.
        env.setdefault("CI", "1")
        env.setdefault("PROMPTFOO_DISABLE_TELEMETRY", "1")

        # Add encoding='utf-8' to prevent the Greek cp1253 crash
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


    

@tool("pyrit_tool")
def pyrit_tool(prompts_text: str) -> str:
    """
    Executes automated red teaming using Microsoft's PyRIT framework.
    
    PyRIT (Python Risk Identification Toolkit) is a specialized framework from
    Microsoft for automated jailbreak testing of LLMs. It:
    - Generates adversarial prompts
    - Manages attack orchestration
    - Scores and analyzes responses
    - Provides structured reporting
    
    This tool generates a temporary Python script that:
    1. Defines a FastAPITarget adapter for PyRIT
    2. Initializes PromptSendingOrchestrator
    3. Sends payloads asynchronously via aiohttp
    4. Prints results in real-time
    
    Note:
    - Requires PyRIT to be installed
    - Uses async/await for efficient concurrent requests
    - Automatically uses the current Python venv
    - Cleans up temporary scripts after execution
    
    Args:
        prompts_text: Attack payloads in pipe-delimited format
                     (e.g., "payload1|payload2|payload3")
    
    Returns:
        String with PyRIT execution status and raw output
    """
    print(f"\n--> [PyRIT] Attacking FastAPI Agent with dynamic payloads...")
    
    jailbreak_prompts = [p.strip() for p in prompts_text.split('|') if p.strip()]
    
    script_content = textwrap.dedent(f"""
    import asyncio
    import aiohttp
    from pyrit.prompt_target import PromptTarget
    from pyrit.orchestrator import PromptSendingOrchestrator

    class FastAPITarget(PromptTarget):
        def __init__(self, endpoint: str):
            super().__init__()
            self.endpoint = endpoint

        async def send_prompt_async(self, prompt_request):
            prompt_text = prompt_request.request_pieces[0].original_value
            async with aiohttp.ClientSession() as session:
                payload = {{"message": prompt_text}}
                async with session.post(self.endpoint, json=payload) as resp:
                    result = await resp.json()
                    print(f"\\n[PyRIT Payload]: {{prompt_text}}")
                    print(f"[Agent Response]: {{result.get('response', 'Error')}}")
                    return result

    async def run_attack():
        target = FastAPITarget(endpoint="{TARGET_CHAT_URL}")
        orchestrator = PromptSendingOrchestrator(objective_target=target)
        
        prompts_to_send = {jailbreak_prompts}
        print("Sending dynamic agentic jailbreak attempts...")
        await orchestrator.send_prompts_async(prompt_list=prompts_to_send)

    if __name__ == "__main__":
        asyncio.run(run_attack())
    """)
    
    try:
        # Force utf-8 on script creation
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_script:
            temp_script.write(script_content)
            temp_script_path = temp_script.name
        
        # Use sys.executable to stay inside the venv, and add utf-8 encoding
        result = subprocess.run([sys.executable, temp_script_path], capture_output=True, text=True, check=False, encoding='utf-8')
        
        os.remove(temp_script_path)
        output = result.stdout if result.stdout else result.stderr
        return f"PyRIT execution complete. Raw Output:\n{output}"
    except Exception as e:
        return f"PyRIT execution failed: {str(e)}"

# @tool("execute_agentic_radar_scan")
# def agentic_radar_tool(target_directory_or_url: str) -> str:
#     """Scans the target architecture using Agentic Radar. Input should be a local directory path."""
#     print(f"\n--> [Agentic Radar] Scanning architecture of: {target_directory_or_url}")
#     try:
#         result = subprocess.run(["agentic-radar", "scan", "-i", target_directory_or_url], capture_output=True, text=True, check=False)
#         output = result.stdout if result.stdout else result.stderr
#         return f"Agentic Radar scan complete. Raw Output:\n{output}"
#     except FileNotFoundError:
#         return "Error: 'agentic-radar' command not found. Is it installed in your virtual environment?"
#     except Exception as e:
#         return f"Agentic Radar scan failed: {str(e)}"