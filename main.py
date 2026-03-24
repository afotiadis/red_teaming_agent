import os
import markdown
from xhtml2pdf import pisa
from dotenv import load_dotenv

load_dotenv()

from crewai import Crew, Process
from src.agents import RedTeamingAgents
from src.tasks import RedTeamingTasks

def save_as_pdf(markdown_content, filename="Red_Team_Report.pdf"):
    """Converts the Agent's Markdown output into a styled PDF."""
    print(f"\n📄 Compiling and saving PDF report to {filename}...")
    
    # Convert Markdown to HTML
    html_body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
    
    # Add CSS styling to make it look professional
    html_content = f"""
    <html>
    <head>
    <style>
        @page {{ size: A4; margin: 2cm; }}
        body {{ font-family: Helvetica, Arial, sans-serif; line-height: 1.5; color: #333; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #e74c3c; padding-bottom: 5px; }}
        h2 {{ color: #e74c3c; margin-top: 20px; }}
        h3 {{ color: #34495e; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #bdc3c7; padding: 10px; text-align: left; }}
        th {{ background-color: #ecf0f1; color: #2c3e50; }}
        pre {{ background-color: #f8f9fa; padding: 15px; border: 1px solid #e9ecef; border-radius: 5px; font-size: 12px; }}
        code {{ font-family: "Courier New", Courier, monospace; color: #c0392b; }}
    </style>
    </head>
    <body>
        {html_body}
    </body>
    </html>
    """
    
    # Generate the PDF
    with open(filename, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(html_content, dest=result_file)
        
    if pisa_status.err:
        print("❌ Error generating PDF.")
    else:
        print(f"✅ Success! Report saved as: {os.path.abspath(filename)}")


def main():
    print("🛡️ Welcome to the CrewAI Red Teaming Agent 🛡️")
    target_prompt = input("Describe the target you want to attack (e.g., 'A local python codebase in ./target_app using Ollama'):\n> ")

    agents = RedTeamingAgents()
    tasks = RedTeamingTasks()

    # 1. Initialize Agents
    planner = agents.planner_agent()
    executor = agents.executor_agent()
    reporter = agents.reporter_agent() # Added Reporter

    # 2. Initialize Tasks
    plan_task = tasks.plan_attack(planner, target_prompt)
    execute_task = tasks.execute_and_report(executor)
    report_task = tasks.generate_pdf_report(reporter) # Added Report Task

    # 3. Form the Crew
    red_team_crew = Crew(
        agents=[planner, executor, reporter], # Added Reporter
        tasks=[plan_task, execute_task, report_task], # Added Report Task
        process=Process.sequential
    )

    print("\n🚀 Initiating Attack Sequence...\n")
    result = red_team_crew.kickoff()

    print("\n" + "="*50)
    print("📝 ATTACK COMPLETE. GENERATING REPORT...")
    print("="*50)
    
    # 4. Save the final output as a PDF
    save_as_pdf(result.raw)

if __name__ == "__main__":
    main()