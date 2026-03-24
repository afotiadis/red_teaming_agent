import os
from langchain_community.llms import Ollama
from langchain.agents import initialize_agent, Tool, AgentType

# 🚩 VULNERABILITY 1: Hardcoded secrets. 
DUMMY_DB_PASSWORD = "super_secret_password_123!"

# 🚩 VULNERABILITY 2: Dangerous Tool (Remote Code Execution / RCE).
def execute_system_command(command: str) -> str:
    """Executes a system command to check server health."""
    import subprocess
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        return str(e)

# 🚩 VULNERABILITY 3: Dangerous Tool (Arbitrary File Read / Path Traversal).
def read_local_file(filepath: str) -> str:
    """Reads internal documentation files from the system."""
    try:
        with open(filepath, 'r') as f:
            return f.read()
    except Exception as e:
        return str(e)

def main():
    print("🤖 Starting Vulnerable IT Support AI...")
    llm = Ollama(model="llama3.2:1b")

    tools = [
        Tool(
            name="System_Command_Executor",
            func=execute_system_command,
            description="Useful for running system commands to check server health."
        ),
        Tool(
            name="Local_File_Reader",
            func=read_local_file,
            description="Useful for reading internal documentation files."
        )
    ]

    agent = initialize_agent(
        tools, 
        llm, 
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION, 
        verbose=True
    )

    print("✅ AI is ready! Type 'exit' to quit.")
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() == 'exit':
            break
        try:
            response = agent.run(user_input)
            print(f"\nAI: {response}")
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()