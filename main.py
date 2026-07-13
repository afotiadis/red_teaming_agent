"""Command-line entry point for the local red-teaming workflow.

The project is intentionally staged as a simple pipeline so a first-time reader
can understand the lifecycle quickly:
environment validation -> planning -> execution -> report generation.

This file shows how the rest of the modules fit together and is the best place
to start when learning the project structure.
"""

import os
import sys
import argparse
import time
import json
import markdown
import requests
from xhtml2pdf import pisa
from dotenv import load_dotenv

load_dotenv()

from crewai import Crew, Process
from src.agents import RedTeamingAgents
from src.tasks import RedTeamingTasks
from src.target_profiles import get_target_health_url, get_target_chat_url, get_target_auth_token

TARGET_CHAT_URL = get_target_chat_url()
TARGET_HEALTH_URL = get_target_health_url()
REPORT_FORMAT = os.getenv("REPORT_FORMAT", "pdf_default").strip().lower()

REPORT_STYLES = {
    "pdf_default": {"kind": "pdf", "filename": "Red_Team_Report.pdf"},
    "html_debug": {"kind": "html", "filename": "Red_Team_Report.html"},
    "json_structured": {"kind": "json", "filename": "Red_Team_Report.json"},
}


def _build_health_url(chat_url: str) -> str:
    """Map the configured chat endpoint to its corresponding health endpoint.

    The crew does not start unless it can confirm the target service is live.
    Rather than hard-coding a second URL, this helper derives `/health` from the
    chat URL so both values stay consistent when the environment changes.
    """
    if chat_url.endswith("/chat"):
        return f"{chat_url[:-5]}/health"
    return f"{chat_url.rstrip('/')}/health"


def validate_runtime() -> None:
    """Check the prerequisites that the crew depends on before any work starts.

    Two external dependencies matter here:
    - The configured LLM backend token so the custom LLM wrapper can reach the API.
    - A reachable target chatbot so the crew has a service to test.

    Failing fast here keeps the later agent steps from producing confusing errors
    that are really just environment setup problems.
    """
    missing = []
    llm_backend = os.getenv("LLM_BACKEND", "openrouter").strip().lower()
    if llm_backend == "ariadne":
        if not os.getenv("ARIADNE_API_TOKEN"):
            missing.append("ARIADNE_API_TOKEN")
    else:
        if not os.getenv("OPENROUTER_API_KEY"):
            missing.append("OPENROUTER_API_KEY")

    target_auth = get_target_auth_token()
    if os.getenv("TARGET_APP", "generic").strip().lower() == "zero_health" and not target_auth:
        missing.append("TARGET_AUTH_TOKEN (or ZERO_HEALTH_JWT)")

    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    health_url = TARGET_HEALTH_URL
    try:
        response = requests.get(health_url, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Target chatbot is not reachable at {TARGET_CHAT_URL} (health check: {health_url}). "
            "Start target_app/vulnerable_chatbot.py first."
        ) from exc

def _render_report_html(markdown_content: str) -> str:
    """Convert the Markdown report into the HTML shell used for exports."""
    html_body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])

    return f"""
    <html>
    <head>
    <style>
        @page {{ size: A4; margin: 1.5cm; }}
        body {{ font-family: Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; font-size: 10pt; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #e74c3c; padding-bottom: 5px; font-size: 18pt; margin: 15px 0 10px 0; }}
        h2 {{ color: #e74c3c; margin-top: 15px; margin-bottom: 10px; font-size: 14pt; }}
        h3 {{ color: #34495e; margin-top: 10px; margin-bottom: 8px; font-size: 12pt; }}
        p {{ margin: 5px 0; word-wrap: break-word; overflow-wrap: break-word; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 9pt; }}
        th, td {{ border: 1px solid #bdc3c7; padding: 8px; text-align: left; word-wrap: break-word; overflow-wrap: break-word; }}
        th {{ background-color: #ecf0f1; color: #2c3e50; font-weight: bold; }}
        pre {{ background-color: #f8f9fa; padding: 12px; border: 1px solid #e9ecef; border-radius: 4px; font-size: 8pt; overflow-x: auto; word-wrap: break-word; overflow-wrap: break-word; white-space: pre-wrap; margin: 10px 0; }}
        code {{ font-family: "Courier New", Courier, monospace; color: #c0392b; word-wrap: break-word; overflow-wrap: break-word; }}
        ul, ol {{ margin: 8px 0; padding-left: 20px; }}
        li {{ margin: 4px 0; }}
    </style>
    </head>
    <body>
        {html_body}
    </body>
    </html>
    """


def save_report(markdown_content, report_format: str = REPORT_FORMAT):
    """Save the reporter output in the configured format."""
    report_style = REPORT_STYLES.get(report_format, REPORT_STYLES["pdf_default"])
    filename = report_style["filename"]

    if report_style["kind"] == "json":
        print(f"\n📄 Saving structured JSON report to {filename}...")
        payload = {
            "report_format": report_format,
            "content_markdown": markdown_content,
            "content_html": markdown.markdown(markdown_content, extensions=['tables', 'fenced_code']),
        }
        with open(filename, "w", encoding="utf-8") as report_file:
            json.dump(payload, report_file, ensure_ascii=False, indent=2)
        print(f"✅ Success! Report saved as: {os.path.abspath(filename)}")
        return

    html_content = _render_report_html(markdown_content)

    if report_style["kind"] == "html":
        print(f"\n📄 Saving HTML report to {filename}...")
        with open(filename, "w", encoding="utf-8") as report_file:
            report_file.write(html_content)
        print(f"✅ Success! Report saved as: {os.path.abspath(filename)}")
        return

    print(f"\n📄 Compiling and saving PDF report to {filename}...")
    with open(filename, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(html_content, dest=result_file)

    if pisa_status.err:
        print("❌ Error generating PDF.")
    else:
        print(f"✅ Success! Report saved as: {os.path.abspath(filename)}")


def main():
    """Run the red-teaming pipeline from the command line.

    The function intentionally follows the same order a human would use to reason
    about the system: capture the target, validate the environment, create the
    planner/executor/reporter roles, execute the crew, and export the result.
    """
    
    print("🛡️ Welcome to the CrewAI Red Teaming Agent 🛡️")
    parser = argparse.ArgumentParser(description="Run the local red-teaming crew")
    parser.add_argument("--target", dest="target_prompt", help="Target description for the planner")
    args = parser.parse_args()

    target_prompt = args.target_prompt or os.getenv("TARGET_PROMPT")
    if not target_prompt:
        if sys.stdin.isatty():
            target_prompt = input("Describe the target you want to attack (e.g., 'A local python codebase in ./target_app using Ollama'):\n> ")
        else:
            raise RuntimeError("No target description provided. Use --target or set TARGET_PROMPT.")

    validate_runtime()

    agents = RedTeamingAgents()
    tasks = RedTeamingTasks()

    # The crew is split into distinct roles so each stage has one responsibility.
    planner = agents.planner_agent()
    executor = agents.executor_agent()
    reporter = agents.reporter_agent()

    # Adaptive planner instance for generating dynamic prompts, seeded with the original target description
    planner_util = agents.adaptive_planner(base_prompt=target_prompt)
    print(f"[Adaptive Planner] Next prompt preview: {planner_util.next_prompt()}", flush=True)
    from src.feedback_loop import run_attack_loop

    print("\n🚀 Initiating Multi-Turn Attack Sequence...\n")
    start_time = time.time()
    
    # Run the adaptive attack loop
    all_results = run_attack_loop(agents, target_prompt, planner_util)
    
    latency = time.time() - start_time
    
    # Record the planner usage (simple placeholder info)
    try:
        planner_util.record(
            prompt="[captured via plan_attack]",
            status="completed",
            latency=latency,
            raw_response="Multi-turn completed."
        )
    except Exception as e:
        print(f"[Planner] Recording failed: {e}")
        
    print("\n" + "="*50)
    print("📝 ATTACK COMPLETE. GENERATING REPORT...")
    print("="*50)
    
    # Compile all results for the reporter
    logs_list = []
    for idx, res in enumerate(all_results, 1):
        round_log = (
            f"=== ROUND {idx} ===\n"
            f"--- EXECUTOR RAW TERMINAL LOGS ---\n"
            f"{res['executor_raw']}\n\n"
            f"--- ANALYZER OUTCOME CLASSIFICATIONS ---\n"
            f"{res['analyzer_raw']}\n"
        )
        logs_list.append(round_log)
    combined_raw_logs = "\n\n".join(logs_list)
    
    coverage = planner_util.get_coverage_summary() if hasattr(planner_util, 'get_coverage_summary') else None
    report_task = tasks.generate_pdf_report(reporter, raw_logs=combined_raw_logs, coverage_summary=coverage)
    report_crew = Crew(
        agents=[reporter],
        tasks=[report_task],
        process=Process.sequential
    )
    final_result = report_crew.kickoff()
    
    # The reporter emits Markdown, so the final step is PDF rendering.
    save_report(final_result.raw)

if __name__ == "__main__":
    main()