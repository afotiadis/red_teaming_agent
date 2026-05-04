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

TARGET_CHAT_URL = os.getenv("TARGET_CHAT_URL", "http://127.0.0.1:8000/chat")


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
if os.path.exists("chroma_db"):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
    retriever = vector_store.as_retriever(search_kwargs={"k": 5})
else:
    retriever = None

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
        delay = float(os.getenv("INTER_PROMPT_DELAY", "0.5"))
        per_request_timeout = int(os.getenv("ATTACK_REQUEST_TIMEOUT", "15"))
        poll_interval = float(os.getenv("ATTACK_JOB_POLL_INTERVAL", "0.5"))
        job_timeout = int(os.getenv("ATTACK_JOB_TIMEOUT", "120"))

        print(f"--> [Promptfoo-Mode] Posting {len(malicious_prompts)} prompts sequentially with {delay}s delay to {TARGET_CHAT_URL}")
        results = []
        for idx, p in enumerate(malicious_prompts, start=1):
            try:
                # The target accepts a message, queues it, and returns a job id.
                payload = {"message": p}
                r = requests.post(TARGET_CHAT_URL, json=payload, timeout=per_request_timeout)
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
                "body": {"message": "{{prompt}}"}
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