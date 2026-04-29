import os
import sys
import json
import shutil
import subprocess
import tempfile
import textwrap
import requests
from crewai.tools import tool
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

TARGET_CHAT_URL = os.getenv("TARGET_CHAT_URL", "http://127.0.0.1:8000/chat")


def _build_health_url(chat_url: str) -> str:
    if chat_url.endswith("/chat"):
        return f"{chat_url[:-5]}/health"
    return f"{chat_url.rstrip('/')}/health"


def _build_promptfoo_command(config_path: str) -> list[str]:
    """Resolves a working Promptfoo invocation on each platform."""
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


# --- RAG Setup (Restored!) ---
if os.path.exists("chroma_db"):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
    retriever = vector_store.as_retriever(search_kwargs={"k": 5})
else:
    retriever = None

@tool("query_red_teaming_tools_knowledge")
def tool_knowledge_rag(query: str) -> str:
    """Queries the RAG database to find documentation on Promptfoo or PyRIT."""
    if not retriever: return "Error: Chroma DB not found. Please run ingest_knowledge.py first."
    results = retriever.invoke(query)
    if not results: return "No relevant information found in the documentation."
    return "\n\n".join([f"Source: {doc.metadata.get('source', 'Unknown')}\nContent: {doc.page_content}" for doc in results])

# --- Execution Tools (With Windows/UTF-8 Fixes) ---

@tool("execute_promptfoo_attack")
def promptfoo_tool(prompts_text: str) -> str:
    """Executes an attack using Promptfoo against the FastAPI Agent endpoint."""
    print(f"\n--> [Promptfoo] Attacking FastAPI Agent with dynamic payloads...")

    malicious_prompts = [p.strip() for p in prompts_text.split('|') if p.strip()]

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

@tool("execute_pyrit_attack")
def pyrit_tool(prompts_text: str) -> str:
    """Executes an attack using PyRIT against the FastAPI Agent endpoint."""
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