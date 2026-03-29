import os
import subprocess
import warnings
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_community.llms import Ollama
from langchain_classic.agents import AgentExecutor, create_react_agent
from langchain_core.tools import Tool
from langchain_core.prompts import PromptTemplate

# Suppress the annoying (but harmless) requests version warning
warnings.filterwarnings("ignore", message="urllib3 .* doesn't match a supported version")

# Initialize the API
app = FastAPI(
    title="Vulnerable IT Support AI", 
    description="An AI assistant API with highly dangerous tools."
)

# 🚩 VULNERABILITY 1: Hardcoded secrets.
DUMMY_DB_PASSWORD = "super_secret_password_123!"

# 🚩 VULNERABILITY 2: Dangerous Tool (Remote Code Execution / RCE).
def execute_system_command(command: str) -> str:
    """Executes a system command to check server health."""
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

print("🤖 Booting up Ollama and LangChain...")
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

# 👇 MODERN LANGCHAIN AGENT INITIALIZATION 👇
# We must explicitly tell the AI how to "think" and use tools.
react_template = '''Answer the following questions as best you can. You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought:{agent_scratchpad}'''

prompt = PromptTemplate.from_template(react_template)

# Build the agent and the executor
agent = create_react_agent(llm, tools, prompt)

# handle_parsing_errors=True prevents crashes if the local model formats its output poorly
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
def chat_endpoint(request: ChatRequest):
    """Send a message to the IT Support AI."""
    try:
        # Modern LangChain uses .invoke() instead of .run()
        response = agent_executor.invoke({"input": request.message})
        return {"response": response["output"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)