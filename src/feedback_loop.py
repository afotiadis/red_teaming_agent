"""Multi-turn feedback loop for the red-teaming framework.

The loop remains intentionally simple: plan, execute, analyze, update coverage,
and report. Final-campaign stopping is objective-aware so the system keeps
harvesting findings until the selected target's priority objectives are covered
or the round budget is exhausted.
"""

import os
import json

from crewai import Crew, Process

from src.campaign_guidance import get_target_objectives
from src.execution_runner import build_round_result, execute_planner_output
from src.experiential_memory import ExperientialMemory
from src.response_analyzer import extract_feedback
from src.target_profiles import get_target_app
from src.tasks import RedTeamingTasks


def should_stop(feedback_summary: dict, coverage_summary: dict | None = None) -> bool:
    """Determine if the attack loop should terminate based on objective coverage."""
    if not isinstance(feedback_summary, dict):
        return False

    results = feedback_summary.get("results", [])
    if not results:
        return False

    target_app = feedback_summary.get("target_app") or get_target_app()
    expected_objectives = set(get_target_objectives(target_app))
    if coverage_summary and expected_objectives:
        vulnerable_objectives = set(coverage_summary.get("vulnerable_objectives", []))
        if expected_objectives.issubset(vulnerable_objectives):
            return True

    all_blocked = all(r.get("outcome") == "BLOCKED" for r in results)
    blocked_threshold = int(os.getenv("ALL_BLOCKED_STOP_THRESHOLD", "12"))
    if all_blocked and len(results) >= blocked_threshold:
        return True

    return False


def run_attack_loop(agents, target_prompt: str, planner_util) -> list:
    """Run the multi-turn attack loop and return all round results."""
    max_rounds = int(os.getenv("MAX_ATTACK_ROUNDS", "5"))
    tasks = RedTeamingTasks()

    planner = agents.planner_agent()
    analyzer = agents.analyzer_agent()

    all_results = []
    feedback_summary = None

    for round_num in range(1, max_rounds + 1):
        print(f"\nAttack Round {round_num}/{max_rounds}")

        if round_num == 1:
            plan_task = tasks.plan_attack(planner, target_prompt, planner_util)
        else:
            coverage = planner_util.get_coverage_summary() if hasattr(planner_util, "get_coverage_summary") else None
            plan_task = tasks.refine_attack(planner, target_prompt, feedback_summary, coverage_summary=coverage)

        planner_crew = Crew(
            agents=[planner],
            tasks=[plan_task],
            process=Process.sequential,
        )

        planner_result = planner_crew.kickoff()
        planner_raw = planner_result.raw if hasattr(planner_result, "raw") else str(planner_result)

        try:
            executor_raw, execution_plan = execute_planner_output(planner_raw)
        except Exception as exc:
            execution_plan = {}
            executor_raw = json.dumps(
                {
                    "target": None,
                    "results": [],
                    "execution_error": f"Planner output could not be executed: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )

        analyze_task = tasks.analyze_results(analyzer, raw_logs=executor_raw, execution_plan=execution_plan)
        analyzer_crew = Crew(
            agents=[analyzer],
            tasks=[analyze_task],
            process=Process.sequential,
        )
        analyzer_result = analyzer_crew.kickoff()
        analyzer_raw = analyzer_result.raw if hasattr(analyzer_result, "raw") else str(analyzer_result)

        round_result = build_round_result(planner_raw, executor_raw, analyzer_raw)

        feedback_summary = extract_feedback(round_result)

        all_results.append(
            {
                "executor_raw": executor_raw,
                "analyzer_raw": analyzer_raw,
                "feedback_summary": feedback_summary,
                "crew_output": round_result,
            }
        )

        if hasattr(planner_util, "update_coverage"):
            planner_util.update_coverage(feedback_summary)

        ExperientialMemory.extract_and_store_from_feedback(target_prompt, feedback_summary)

        coverage_summary = planner_util.get_coverage_summary() if hasattr(planner_util, "get_coverage_summary") else None
        if should_stop(feedback_summary, coverage_summary=coverage_summary):
            print("Sufficient target-objective coverage achieved or a full prompt batch was blocked. Terminating loop.")
            break

    return all_results
