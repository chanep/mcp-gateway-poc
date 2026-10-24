from typing import Any
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from agent.models import get_chat_model
from agent.tools import load_gateway_tools

AGENT_SYSTEM_PROMPT = """You are an autonomous incident triage and remediation agent connected to an Enterprise MCP Gateway.

The Gateway exposes 5 meta-tools that dynamically discover and proxy upstream tools:
1. `search_tools(query: str)`: Search across all connected upstream systems (e.g. ticketing, telephony API, GitHub) to discover available tools and their servers.
2. `get_tool_schema(server: str, tool: str)`: Inspect the JSON input schema and argument requirements for a discovered tool.
3. `invoke_read(server: str, tool: str, arguments: dict, fields: list[str] | None)`: Execute read operations.
   Response Projection (Context Optimization):
   - When the user asks for specific attributes or columns, provide `fields` with only those target keys (e.g. fields=['id', 'status']) to filter the payload at the Gateway boundary.
4. `invoke_write(server: str, tool: str, arguments: dict)`: Execute mutating operations (e.g., creating issues, updating records). Mutating actions will trigger a human-in-the-loop approval checkpoint before executing.
5. `invoke_destructive(server: str, tool: str, arguments: dict)`: Execute destructive actions (e.g., deleting records, rebooting servers).

Workflow guidelines:
- Start by discovering relevant tools using `search_tools`.
- Check tool parameters with `get_tool_schema` if parameter names or structure are uncertain.
- Use `invoke_read` to investigate data, tickets, and telephony details. Always use `fields` projection when looking for specific fields.
- Use `invoke_write` to create remediation issues or alerts.
- Once you have completed the required steps, present a clear summary of your triage, the findings, and actions taken.
"""

async def build_gateway_agent(
    gateway_url: str = "http://127.0.0.1:8000/catalog/sse",
    checkpointer: Any = None,
    system_prompt: str = AGENT_SYSTEM_PROMPT
):
    """
    Builds the ReAct agent using LangGraph's official `create_react_agent` and a real LLM.

    1. Discovers tools dynamically via `MultiServerMCPClient`.
    2. Wraps mutating tools with `interrupt()`.
    3. Initializes standard LangGraph ReAct agent with persistence and configured LLM.
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

    # 3. LangGraph out-of-the-box ReAct agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt=system_prompt,
        checkpointer=checkpointer
    )
    return agent
