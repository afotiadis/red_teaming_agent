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
import markdown
import requests
from xhtml2pdf import pisa
from dotenv import load_dotenv

load_dotenv()

from crewai import Crew, Process
from src.agents import RedTeamingAgents
from src.tasks import RedTeamingTasks

TARGET_CHAT_URL = os.getenv("TARGET_CHAT_URL", "http://127.0.0.1:8000/chat")


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
    - `ARIADNE_API_TOKEN` so the custom LLM wrapper can reach the API.
    - A reachable target chatbot so the crew has a service to test.

    Failing fast here keeps the later agent steps from producing confusing errors
    that are really just environment setup problems.
    """
    missing = []
    if not os.getenv("ARIADNE_API_TOKEN"):
        missing.append("ARIADNE_API_TOKEN")

    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    health_url = _build_health_url(TARGET_CHAT_URL)
    try:
        response = requests.get(health_url, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Target chatbot is not reachable at {TARGET_CHAT_URL} (health check: {health_url}). "
            "Start target_app/vulnerable_chatbot.py first."
        ) from exc

def save_as_pdf(markdown_content, filename="Red_Team_Report.pdf"):
    """Render the reporter's Markdown output into a styled PDF file.

    The final agent stage emits Markdown because it is easy for the model to
    produce and easy for humans to inspect. This helper turns that Markdown into
    HTML and then into a PDF with simple print-oriented styling.
    """
    print(f"\n📄 Compiling and saving PDF report to {filename}...")
    
    # xhtml2pdf consumes HTML, so convert the Markdown output before rendering.
    html_body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
    
    # Keep the stylesheet conservative so long prompts, code blocks, and tables
    # remain readable when exported.
    html_content = f"""
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
    
    # Write the PDF directly to disk.
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

    # Each task consumes the output of the previous step.
    plan_task = tasks.plan_attack(planner, target_prompt)
    execute_task = tasks.execute_and_report(executor)
    report_task = tasks.generate_pdf_report(reporter)

    # Sequential execution keeps the planner, executor, and reporter in order.
    red_team_crew = Crew(
        agents=[planner, executor, reporter],
        tasks=[plan_task, execute_task, report_task],
        process=Process.sequential
    )

    print("\n🚀 Initiating Attack Sequence...\n")
    result = red_team_crew.kickoff()

    print("\n" + "="*50)
    print("📝 ATTACK COMPLETE. GENERATING REPORT...")
    print("="*50)
    
    # The reporter emits Markdown, so the final step is PDF rendering.
    save_as_pdf(result.raw)

if __name__ == "__main__":
    main()