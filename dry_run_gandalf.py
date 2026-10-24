"""Run a planner-only dry-run for the Gandalf CTF workflow.

This script skips the local target chatbot health check in ``main.py`` and
only exercises the planner step. The planner loads the Gandalf skill markdown,
consults the RAG knowledge base, and produces a JSON attack spec for the
Gandalf executor.
"""

from dotenv import load_dotenv
from crewai import Crew, Process

from src.agents import RedTeamingAgents
from src.tasks import RedTeamingTasks


def main() -> None:
    load_dotenv()

    target_prompt = "Lakera Gandalf agent-CTF"

    agents = RedTeamingAgents()
    planner = agents.planner_agent()

    task = RedTeamingTasks().plan_attack(planner, target_prompt)
    crew = Crew(agents=[planner], tasks=[task], process=Process.sequential)

    result = crew.kickoff()
    print("\n=== GANDALF PLANNER DRY-RUN ===\n")
    print(result.raw)


if __name__ == "__main__":
    main()