from typing import Any
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from agent.models import get_chat_model
from agent.tools import load_gateway_tools

AGENT_SYSTEM_PROMPT = """You are an autonomous engineering and incident triage assistant at PhoneCentral.

You have access to PhoneCentral's internal engineering systems (ticketing/Jira, telephony APIs and call logs, and GitHub repositories) via an MCP Gateway.
For general knowledge or questions unrelated to PhoneCentral's internal engineering systems (such as weather, news, or trivia), answer directly without invoking internal tools.
"""

async def build_gateway_agent(
    gateway_url: str = "http://127.0.0.1:8000/catalog/sse",
    checkpointer: Any = None,
    system_prompt: str = AGENT_SYSTEM_PROMPT
):
    """
    Builds the ReAct agent using LangChain's official `create_agent` and a real LLM.

    1. Discovers tools dynamically via `MultiServerMCPClient`.
    2. Wraps mutating tools with `interrupt()`.
    3. Initializes standard LangChain agent graph with persistence and configured LLM.
    """
    checkpointer = checkpointer or MemorySaver()

    # 1. Dynamic tools discovered via MCP protocol
    tools = await load_gateway_tools(gateway_url)

    # 2. Real LLM Model (Gemini or OpenAI configured in .env)
    model = get_chat_model()
    if model is None:
        raise ValueError(
            "No LLM API key configured. Please set GEMINI_API_KEY in .env file."
        )

    # 3. Official LangChain agent graph (replaces deprecated create_react_agent)
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer
    )
    return agent
