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
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
import markdown
import requests
from xhtml2pdf import pisa
from dotenv import load_dotenv

load_dotenv()

from crewai import Crew, Process
from src.agents import RedTeamingAgents
from src.tasks import RedTeamingTasks
from src.target_profiles import (
    build_target_headers,
    get_target_health_url,
    get_target_chat_url,
    get_target_auth_token,
    get_target_app,
    get_target_description,
    target_auth_is_required,
)

TARGET_CHAT_URL = get_target_chat_url()
TARGET_HEALTH_URL = get_target_health_url()
REPORT_FORMAT = os.getenv("REPORT_FORMAT", "pdf_default").strip().lower()
PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_OUTPUT_DIR = os.getenv("REPORT_OUTPUT_DIR", "reports")

REPORT_STYLES = {
    "pdf_default": {"kind": "pdf", "extension": "pdf"},
    "html_debug": {"kind": "html", "extension": "html"},
    "json_structured": {"kind": "json", "extension": "json"},
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
    if target_auth_is_required() and not target_auth:
        missing.append("TARGET_AUTH_TOKEN")

    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    health_url = TARGET_HEALTH_URL
    try:
        response = requests.get(health_url, headers=build_target_headers(), timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Target chatbot is not reachable at {TARGET_CHAT_URL} (health check: {health_url}). "
            f"Start the selected '{get_target_app()}' application and verify its profile/URL settings."
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


def _extract_json_dict(raw_text: str, required_key: str | None = None) -> dict | None:
    """Find a JSON object embedded in an agent's surrounding prose."""
    raw_text = raw_text or ""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw_text):
        try:
            candidate, _ = decoder.raw_decode(raw_text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and (required_key is None or required_key in candidate):
            return candidate
    return None


def _markdown_fence(value, language: str = "text") -> str:
    """Fence arbitrary evidence without breaking on backticks inside responses."""
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, indent=2)
    longest_backticks = max((len(run) for run in re.findall(r"`+", rendered)), default=0)
    fence = "`" * max(3, longest_backticks + 1)
    return f"{fence}{language}\n{rendered}\n{fence}"


def build_report_evidence(all_results: list) -> tuple[str, dict, list[str]]:
    """Create complete transcripts and compact statistics without using an LLM."""
    transcript_parts = []
    evidence_markers = []
    status_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    objective_counts: dict[str, int] = {}
    evidence_marker_counts: dict[str, int] = {}
    error_type_counts: dict[str, int] = {}
    representative_errors = []
    targets = set()
    total_prompt_results = 0

    for round_number, round_data in enumerate(all_results, 1):
        executor_raw = str(round_data.get("executor_raw", ""))
        analyzer_raw = str(round_data.get("analyzer_raw", ""))
        feedback_summary = round_data.get("feedback_summary")
        executor_payload = _extract_json_dict(executor_raw, required_key="results")
        analyzer_payload = feedback_summary if isinstance(feedback_summary, dict) else _extract_json_dict(analyzer_raw, required_key="results")
        executor_results = executor_payload.get("results", []) if executor_payload else []
        analyzer_results = analyzer_payload.get("results", []) if analyzer_payload else []

        if executor_payload and executor_payload.get("target"):
            targets.add(str(executor_payload["target"]))

        transcript_parts.append(f"### Round {round_number}")

        if not isinstance(executor_results, list) or not executor_results:
            marker = f"<!-- EVIDENCE:R{round_number}:RAW -->"
            evidence_markers.append(marker)
            transcript_parts.extend([
                marker,
                "Structured executor results could not be parsed; the complete raw executor evidence follows.",
                _markdown_fence(executor_raw, "text"),
            ])
            continue

        for result_index, result in enumerate(executor_results, 1):
            if not isinstance(result, dict):
                result = {"response": result}
            prompt_index = result.get("prompt_index", result_index)
            marker = f"<!-- EVIDENCE:R{round_number}:P{prompt_index} -->"
            evidence_markers.append(marker)
            total_prompt_results += 1

            transcript_parts.extend([
                marker,
                f"#### Round {round_number}, Prompt {prompt_index}",
                "**Payload Sent**",
                _markdown_fence(str(result.get("prompt", "")), "text"),
            ])

            status_code = result.get("status_code")
            if status_code is not None:
                status_key = str(status_code)
                status_counts[status_key] = status_counts.get(status_key, 0) + 1
                transcript_parts.append(f"**HTTP Status:** `{status_code}`")

            if "response" in result:
                transcript_parts.extend([
                    "**Target Response**",
                    _markdown_fence(result["response"], "json" if not isinstance(result["response"], str) else "text"),
                ])
                if isinstance(result["response"], dict) and result["response"].get("error"):
                    error_text = str(result["response"].get("details") or result["response"]["error"])
                    if error_text not in representative_errors and len(representative_errors) < 5:
                        representative_errors.append(error_text[:300])
            else:
                error_text = str(result.get("error", "No response was recorded."))
                transcript_parts.extend(["**Target Error**", _markdown_fence(error_text, "text")])
                if error_text not in representative_errors and len(representative_errors) < 5:
                    representative_errors.append(error_text[:300])

            error_type = result.get("error_type")
            if error_type:
                error_key = str(error_type)
                error_type_counts[error_key] = error_type_counts.get(error_key, 0) + 1

            if result.get("attempts"):
                transcript_parts.extend(["**Request Attempts**", _markdown_fence(result["attempts"], "json")])
            if result.get("retry_skipped_reason"):
                transcript_parts.append(f"**Retry note:** {result['retry_skipped_reason']}")

            analyzer_item = analyzer_results[result_index - 1] if result_index <= len(analyzer_results) else None
            if isinstance(analyzer_item, dict):
                outcome = str(analyzer_item.get("outcome", "UNKNOWN"))
                category = str(analyzer_item.get("category", "unknown"))
                objective = str(analyzer_item.get("objective", "unknown"))
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
                category_counts[category] = category_counts.get(category, 0) + 1
                objective_counts[objective] = objective_counts.get(objective, 0) + 1
                for evidence_marker in analyzer_item.get("evidence_markers", []) or []:
                    marker_key = str(evidence_marker)
                    evidence_marker_counts[marker_key] = evidence_marker_counts.get(marker_key, 0) + 1
                transcript_parts.append(f"**Analyzer Classification:** `{outcome}` (`{category}`, `{objective}`)")

    summary = {
        "targets": sorted(targets),
        "rounds_executed": len(all_results),
        "total_prompt_results": total_prompt_results,
        "http_status_counts": status_counts,
        "analyzer_outcome_counts": outcome_counts,
        "category_counts": category_counts,
        "objective_counts": objective_counts,
        "evidence_marker_counts": evidence_marker_counts,
        "transport_error_counts": error_type_counts,
        "representative_errors": representative_errors,
    }
    return "\n\n".join(transcript_parts), summary, evidence_markers


def assemble_complete_report(narrative_markdown: str, transcripts: str) -> str:
    """Insert deterministic transcripts before remediation recommendations."""
    narrative = (narrative_markdown or "").strip()

    # Discard any Section 4 the model generated despite its bounded task.
    section_four = re.search(r"(?im)^#{1,6}\s*4(?:\.|\s)", narrative)
    if section_four:
        later_section_five = re.search(r"(?im)^#{1,6}\s*5(?:\.|\s)", narrative[section_four.start():])
        if later_section_five:
            five_start = section_four.start() + later_section_five.start()
            narrative = narrative[:section_four.start()].rstrip() + "\n\n" + narrative[five_start:].lstrip()
        else:
            narrative = narrative[:section_four.start()].rstrip()

    section_five = re.search(r"(?im)^#{1,6}\s*5(?:\.|\s)", narrative)
    if not section_five:
        raise RuntimeError("Reporter output is incomplete: Section 5 Remediation Recommendations is missing.")

    analysis_sections = narrative[:section_five.start()].rstrip()
    remediation_section = narrative[section_five.start():].lstrip()
    return (
        f"{analysis_sections}\n\n"
        f"## 4. Detailed Attack Transcripts\n\n"
        f"The following evidence was rendered deterministically from executor results; it was not regenerated by an LLM.\n\n"
        f"{transcripts}\n\n"
        f"{remediation_section}\n\n"
        f"<!-- END OF REPORT -->\n"
    )


def validate_complete_report(report_markdown: str, evidence_markers: list[str]) -> None:
    """Reject semantically truncated reports before creating an archival PDF."""
    missing = []
    for section_number in (1, 2, 3, 4, 5):
        if not re.search(rf"(?im)^#{{1,6}}\s*{section_number}(?:\.|\s)", report_markdown):
            missing.append(f"Section {section_number}")
    for marker in evidence_markers:
        if marker not in report_markdown:
            missing.append(marker)
    if "<!-- END OF REPORT -->" not in report_markdown:
        missing.append("end-of-report marker")
    if missing:
        preview = ", ".join(missing[:10])
        raise RuntimeError(f"Report completeness validation failed; missing: {preview}")


def _resolve_report_output_dir(output_dir: str | os.PathLike | None = None) -> Path:
    """Resolve report storage relative to the repository, not the launch shell."""
    candidate = Path(output_dir or REPORT_OUTPUT_DIR).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _safe_filename_component(value: str) -> str:
    """Convert target/profile labels into portable filename components."""
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip().lower())
    return normalized.strip("_") or "generic"


def _build_unique_report_path(
    report_style: dict,
    output_dir: str | os.PathLike | None = None,
    generated_at: datetime | None = None,
) -> Path:
    """Build a timestamped, collision-resistant path for one report artifact."""
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    timestamp = generated_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    target_slug = _safe_filename_component(get_target_app())
    unique_suffix = uuid.uuid4().hex[:8]
    filename = f"red_team_report_{target_slug}_{timestamp}_{unique_suffix}.{report_style['extension']}"
    return _resolve_report_output_dir(output_dir) / filename


def save_report(
    markdown_content,
    report_format: str = REPORT_FORMAT,
    output_dir: str | os.PathLike | None = None,
) -> Path:
    """Save a uniquely named report and return its absolute path."""
    report_style = REPORT_STYLES.get(report_format, REPORT_STYLES["pdf_default"])
    report_path = _build_unique_report_path(report_style, output_dir=output_dir)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if report_style["kind"] == "json":
        print(f"\nSaving structured JSON report to {report_path.name}...")
        payload = {
            "report_format": report_format,
            "report_path": str(report_path),
            "content_markdown": markdown_content,
            "content_html": markdown.markdown(markdown_content, extensions=['tables', 'fenced_code']),
        }
        with report_path.open("x", encoding="utf-8") as report_file:
            json.dump(payload, report_file, ensure_ascii=False, indent=2)
        print(f"Success! Report saved as: {report_path}")
        return report_path

    html_content = _render_report_html(markdown_content)

    if report_style["kind"] == "html":
        print(f"\nSaving HTML report to {report_path.name}...")
        with report_path.open("x", encoding="utf-8") as report_file:
            report_file.write(html_content)
        print(f"Success! Report saved as: {report_path}")
        return report_path

    print(f"\nCompiling and saving PDF report to {report_path.name}...")
    with report_path.open("x+b") as result_file:
        pisa_status = pisa.CreatePDF(html_content, dest=result_file)

    if pisa_status.err:
        report_path.unlink(missing_ok=True)
        raise RuntimeError("Error generating PDF report.")

    print(f"Success! Report saved as: {report_path}")
    return report_path


def main():
    """Run the red-teaming pipeline from the command line.

    The function intentionally follows the same order a human would use to reason
    about the system: capture the target, validate the environment, create the
    planner/analyzer/reporter roles, execute the planned prompts, and export the result.
    """
    
    print("🛡️ Welcome to the CrewAI Red Teaming Agent 🛡️")
    parser = argparse.ArgumentParser(description="Run the local red-teaming crew")
    parser.add_argument("--target", dest="target_prompt", help="Target description for the planner")
    args = parser.parse_args()

    target_prompt = args.target_prompt or os.getenv("TARGET_PROMPT") or get_target_description()
    if not target_prompt:
        if sys.stdin.isatty():
            target_prompt = input("Describe the target you want to attack (e.g., 'A local python codebase in ./target_app using Ollama'):\n> ")
        else:
            raise RuntimeError("No target description provided. Use --target or set TARGET_PROMPT.")

    validate_runtime()

    agents = RedTeamingAgents()
    tasks = RedTeamingTasks()

    reporter = agents.reporter_agent()

    # The adaptive planner owns campaign state and objective coverage. The
    # CrewAI planner inside run_attack_loop owns each round's prompt batch.
    planner_util = agents.adaptive_planner(base_prompt=target_prompt)
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
    
    # Python owns the evidence section so long transcripts cannot be truncated,
    # summarized, or hallucinated by a single reporter LLM completion.
    transcripts, execution_summary, evidence_markers = build_report_evidence(all_results)

    coverage = planner_util.get_coverage_summary() if hasattr(planner_util, 'get_coverage_summary') else None
    report_task = tasks.generate_pdf_report(
        reporter,
        coverage_summary=coverage,
        execution_summary=execution_summary,
    )
    report_crew = Crew(
        agents=[reporter],
        tasks=[report_task],
        process=Process.sequential
    )
    final_result = report_crew.kickoff()

    complete_markdown = assemble_complete_report(final_result.raw, transcripts)
    validate_complete_report(complete_markdown, evidence_markers)
    save_report(complete_markdown)

if __name__ == "__main__":
    main()
