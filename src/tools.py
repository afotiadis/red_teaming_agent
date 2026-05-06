"""Tools exposed to the red-teaming planner and executor agents.

This module is the operational bridge between the crew and the outside world.
It provides three kinds of capabilities:

* a retrieval tool that lets the planner consult the documentation knowledge base,
* a Promptfoo-based attack executor that can replay test prompts against the target,
* a PyRIT-based executor that can generate a separate attack harness when needed.

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
import textwrap
import time
import requests
from crewai.tools import tool
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_CHAT_URL = os.getenv("TARGET_CHAT_URL", "http://127.0.0.1:8000/chat")
TARGET_REQUEST_FORMAT = os.getenv("TARGET_REQUEST_FORMAT", "json_message")
KNOWLEDGE_BASE_PATH = os.getenv("KNOWLEDGE_BASE_PATH", os.path.join(PROJECT_ROOT, "chroma_db"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

ATTACK_STRATEGIES_PATH = os.getenv("ATTACK_STRATEGIES_PATH", os.path.join(PROJECT_ROOT, "config", "attack_strategies.json"))


DEFAULT_ATTACK_STRATEGY = {
    "inter_prompt_delay": float(os.getenv("INTER_PROMPT_DELAY", "0.5")),
    "request_timeout": int(os.getenv("ATTACK_REQUEST_TIMEOUT", "15")),
    "poll_interval": float(os.getenv("ATTACK_JOB_POLL_INTERVAL", "0.5")),
    "job_timeout": int(os.getenv("ATTACK_JOB_TIMEOUT", "120")),
}


def _load_attack_strategy() -> dict:
    """Load the selected attack pacing profile from disk, with env defaults."""
    strategy_name = os.getenv("ATTACK_STRATEGY", "local_fast")
    try:
        with open(ATTACK_STRATEGIES_PATH, "r", encoding="utf-8") as strategy_file:
            strategies = json.load(strategy_file)
        return strategies.get(strategy_name, DEFAULT_ATTACK_STRATEGY)
    except Exception:
        return DEFAULT_ATTACK_STRATEGY


ATTACK_STRATEGY = _load_attack_strategy()

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
    if TARGET_REQUEST_FORMAT == "plain_text":
        return prompt

    field_name = {
        "json_message": "message",
        "json_query": "query",
        "json_input": "input",
        "json_prompt": "prompt",
    }.get(TARGET_REQUEST_FORMAT, "message")

    return {field_name: prompt}


def _build_request_kwargs(prompt: str) -> dict:
    """Build the requests.post keyword arguments for the configured target contract."""
    payload = _build_request_payload(prompt)
    if TARGET_REQUEST_FORMAT == "plain_text":
        return {
            "data": payload,
            "headers": {"Content-Type": "text/plain"},
        }
    return {"json": payload}


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


# The planner agent expects a lightweight documentation retriever.
# If the vector database has not been built yet, the tool falls back to a clear
# error message instead of failing deep inside the agent stack.
if os.path.exists(KNOWLEDGE_BASE_PATH):
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vector_store = Chroma(persist_directory=KNOWLEDGE_BASE_PATH, embedding_function=embeddings)
    retriever = vector_store.as_retriever(search_kwargs={"k": 5})
else:
    retriever = None


@tool("discover_target_surface")
def discover_target_surface(target_url: str = "") -> str:
    """Probe a target service to discover its API surface and basic capabilities.

    This tool only sends harmless requests such as OPTIONS, GET, HEAD, and POST
    with an empty JSON object. It is intended to help the planner infer the
    target's endpoint shape before any attack prompts are generated.
    """
    target_url = (target_url or TARGET_CHAT_URL).rstrip("/")
    findings = [f"## Target Surface Discovery\n", f"**Target URL:** {target_url}\n"]

    try:
        options_response = requests.options(target_url, timeout=5)
        allow_header = options_response.headers.get("Allow")
        if allow_header:
            findings.append(f"**Allowed Methods:** {allow_header}\n")
    except requests.RequestException:
        pass

    try:
        get_response = requests.get(target_url, timeout=5)
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
        post_response = requests.post(target_url, json={}, timeout=5)
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

    for field_name in candidates:
        try:
            response = requests.post(target_url, json={field_name: "test"}, timeout=5)
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
def analyze_target_behavior(target_url: str = "", test_prompts: str = "hello|help|test|who are you|what can you do", field_name: str = "message") -> str:
    """Send benign prompts to characterize response shape, timing, and output style."""
    target_url = (target_url or TARGET_CHAT_URL).rstrip("/")
    prompts = [prompt.strip() for prompt in test_prompts.split("|") if prompt.strip()]
    report = [f"## Target Behavior Analysis\n", f"**Target URL:** {target_url}\n", f"**Field Name:** {field_name}\n"]

    response_times = []
    samples = []

    for prompt in prompts:
        try:
            start = time.time()
            response = requests.post(target_url, json={field_name: prompt}, timeout=15)
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
    base_url = target_url.rsplit("/", 1)[0] if "/" in target_url else target_url
    findings = [f"## Misconfiguration Scan\n", f"**Target:** {base_url}\n"]

    debug_paths = ["/debug", "/__debug__", "/_debug", "/admin", "/api/debug", "/metrics", "/prometheus"]
    exposed = []
    for path in debug_paths:
        try:
            response = requests.get(base_url + path, timeout=3)
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
        response = requests.options(base_url, headers={"Origin": "https://attacker.example.com"}, timeout=3)
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
    if not retriever: return "Error: Chroma DB not found. Please run ingest_knowledge.py first."
    results = retriever.invoke(query)
    if not results: return "No relevant information found in the documentation."
    return "\n\n".join([f"Source: {doc.metadata.get('source', 'Unknown')}\nContent: {doc.page_content}" for doc in results])

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
        # Direct mode keeps control inside Python and makes each request easier to trace.
        delay = float(ATTACK_STRATEGY.get("inter_prompt_delay", DEFAULT_ATTACK_STRATEGY["inter_prompt_delay"]))
        per_request_timeout = int(ATTACK_STRATEGY.get("request_timeout", DEFAULT_ATTACK_STRATEGY["request_timeout"]))
        poll_interval = float(ATTACK_STRATEGY.get("poll_interval", DEFAULT_ATTACK_STRATEGY["poll_interval"]))
        job_timeout = int(ATTACK_STRATEGY.get("job_timeout", DEFAULT_ATTACK_STRATEGY["job_timeout"]))

        print(f"--> [Promptfoo-Mode] Posting {len(malicious_prompts)} prompts sequentially with {delay}s delay to {TARGET_CHAT_URL}")
        results = []
        for idx, p in enumerate(malicious_prompts, start=1):
            try:
                # The target accepts a message, queues it, and returns a job id.
                request_kwargs = _build_request_kwargs(p)
                r = requests.post(TARGET_CHAT_URL, timeout=per_request_timeout, **request_kwargs)
                response_body = r.json()
                job_id = response_body.get("job_id")
                job_data = response_body

                if job_id:
                    # Poll the job endpoint until the background worker finishes.
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
                "headers": {"Content-Type": "application/json"},
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

@tool("execute_pyrit_attack")
def pyrit_tool(prompts_text: str) -> str:
    """Execute a PyRIT-driven attack against the target chatbot.

    PyRIT is handled through a temporary script because the project is designed to
    stay portable and easy to inspect. The generated script wraps the target in a
    small custom PromptTarget implementation and sends the planner-provided
    prompts through the orchestrator.
    """
    print(f"\n--> [PyRIT] Attacking FastAPI Agent with dynamic payloads...")
    
    # Split the planner payload into individual jailbreak attempts.
    jailbreak_prompts = [p.strip() for p in prompts_text.split('|') if p.strip()]
    
    # Generate a temporary self-contained script so PyRIT can be launched in the current virtual environment.
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
        # Write the temporary script with UTF-8 encoding to avoid locale issues.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_script:
            temp_script.write(script_content)
            temp_script_path = temp_script.name
        
        # Use the current Python interpreter so the script runs inside the same environment.
        result = subprocess.run([sys.executable, temp_script_path], capture_output=True, text=True, check=False, encoding='utf-8')
        
        os.remove(temp_script_path)
        output = result.stdout if result.stdout else result.stderr
        return f"PyRIT execution complete. Raw Output:\n{output}"
    except Exception as e:
        return f"PyRIT execution failed: {str(e)}"

# Agentic Radar support is intentionally left commented out. If the project grows
# to use it, this is the place to add a fourth tool without changing the planner
# and executor contracts above.