from dotenv import load_dotenv
load_dotenv()

from crewai import Crew, Process
from src.agents import RedTeamingAgents
from src.tasks import RedTeamingTasks



def main():
    print("🛡️ Welcome to the CrewAI Red Teaming Agent 🛡️")
    target_prompt = input("Describe the target you want to attack (e.g., 'A local python codebase in ./target_app using Ollama'):\n> ")

    agents = RedTeamingAgents()
    tasks = RedTeamingTasks()

    planner = agents.planner_agent()
    executor = agents.executor_agent()

    plan_task = tasks.plan_attack(planner, target_prompt)
    execute_task = tasks.execute_and_report(executor)

    red_team_crew = Crew(
        agents=[planner, executor],
        tasks=[plan_task, execute_task],
        process=Process.sequential
    )

    print("\n🚀 Initiating Attack Sequence...\n")
    result = red_team_crew.kickoff()

    print("\n" + "="*50)
    print("📝 FINAL RED TEAM REPORT")
    print("="*50)
    print(result)

if __name__ == "__main__":
    main()