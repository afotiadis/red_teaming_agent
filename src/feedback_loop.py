"""Multi-turn feedback loop for the red-teaming framework.

This module orchestrates the iterative attack cycle:
1. Plan (or Refine)
2. Execute
3. Analyze

The loop terminates when maximum rounds are reached or the analyzer determines
that the target has been fully compromised or no new vectors are viable.
"""

import os
from crewai import Crew, Process
from src.tasks import RedTeamingTasks
from src.response_analyzer import extract_feedback
from src.experiential_memory import ExperientialMemory

def should_stop(feedback_summary: dict) -> bool:
    """Determine if the attack loop should terminate based on feedback."""
    # A simple heuristic: if we achieved FULL_LEAK for all categories, stop.
    # In practice, we might also stop if we keep getting BLOCKED and run out of budget.
    if not isinstance(feedback_summary, dict):
        return False
        
    results = feedback_summary.get("results", [])
    if not results:
        return False
        
    # Example stopping condition: if we have multiple FULL_LEAKs, we might be done.
    full_leaks = sum(1 for r in results if r.get("outcome") == "FULL_LEAK")
    if full_leaks >= 3:
        return True
        
    # Another condition: all blocked
    all_blocked = all(r.get("outcome") == "BLOCKED" for r in results)
    if all_blocked and len(results) >= 10:
        return True
        
    return False

def run_attack_loop(agents, target_prompt: str, planner_util) -> list:
    """Run the multi-turn attack loop and return all round results."""
    MAX_ROUNDS = int(os.getenv("MAX_ATTACK_ROUNDS", "5"))
    tasks = RedTeamingTasks()
    
    planner = agents.planner_agent()
    executor = agents.executor_agent()
    analyzer = agents.analyzer_agent()
    
    all_results = []
    feedback_summary = None
    
    for round_num in range(1, MAX_ROUNDS + 1):
        print(f"\n🔄 Attack Round {round_num}/{MAX_ROUNDS}")
        
        # Step 1: Plan (or refine from previous feedback)
        if round_num == 1:
            plan_task = tasks.plan_attack(planner, target_prompt, planner_util)
        else:
            coverage = planner_util.get_coverage_summary() if hasattr(planner_util, 'get_coverage_summary') else None
            plan_task = tasks.refine_attack(planner, target_prompt, feedback_summary, coverage_summary=coverage)
        
        # Step 2: Execute
        execute_task = tasks.execute_and_report(executor)
        
        # Step 3: Analyze results
        analyze_task = tasks.analyze_results(analyzer)
        
        round_crew = Crew(
            agents=[planner, executor, analyzer],
            tasks=[plan_task, execute_task, analyze_task],
            process=Process.sequential
        )
        
        round_result = round_crew.kickoff()
        
        executor_raw = ""
        analyzer_raw = round_result.raw if hasattr(round_result, 'raw') else str(round_result)
        if hasattr(round_result, 'tasks_output') and len(round_result.tasks_output) > 1:
            executor_raw = round_result.tasks_output[1].raw
            
        all_results.append({
            "executor_raw": executor_raw,
            "analyzer_raw": analyzer_raw,
            "crew_output": round_result
        })
        
        # Step 4: Extract feedback for next round
        feedback_summary = extract_feedback(round_result)
        
        # Update coverage state
        if hasattr(planner_util, 'update_coverage'):
            planner_util.update_coverage(feedback_summary)
            
        # Log any successes to experiential memory
        ExperientialMemory.extract_and_store_from_feedback(target_prompt, feedback_summary)
        
        # Step 5: Check stopping criteria
        if should_stop(feedback_summary):
            print("✅ Sufficient coverage achieved or all prompts blocked. Terminating loop.")
            break
            
    return all_results
