from typing import Any, List
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.runnables import Runnable
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from agent.models import get_chat_model
from agent.tools import load_gateway_tools

class SimulatedPlannerModel(Runnable):
    """
    Deterministic simulated planner for testing and demos without an external LLM API key.
    Implements LangChain's Runnable contract.
    """
    def __init__(self, tools: List[Any] = None):
        super().__init__()
        self.tools = tools or []

    def bind_tools(self, tools: List[Any], **kwargs):
        return SimulatedPlannerModel(tools)

    def invoke(self, input: Any, config: Any = None, **kwargs) -> AIMessage:
        if isinstance(input, list):
            messages = input
        elif isinstance(input, dict):
            messages = input.get("messages", [])
        else:
            messages = getattr(input, "messages", [])
        return self._get_step_response(messages)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs) -> AIMessage:
        return self.invoke(input, config, **kwargs)

    def _get_step_response(self, messages: List[BaseMessage]) -> AIMessage:
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        step = len(tool_msgs)

        if step == 0:
            return AIMessage(
                content="Searching for engineering ticket tools.",
                tool_calls=[{"id": "call_1", "name": "search_tools", "args": {"query": "engineering tickets"}}]
            )
        elif step == 1:
            return AIMessage(
                content="Discovered 'jira_mock.read_query'. Retrieving parameter schema.",
                tool_calls=[{"id": "call_2", "name": "get_tool_schema", "args": {"server": "jira_mock", "tool": "read_query"}}]
            )
        elif step == 2:
            return AIMessage(
                content="Querying ticket TICKET-101 in the ticketing system...",
                tool_calls=[{
                    "id": "call_3",
                    "name": "invoke_read",
                    "args": {
                        "server": "jira_mock",
                        "tool": "read_query",
                        "arguments": {"query": "SELECT id, title, call_id FROM tickets WHERE id = 'TICKET-101'"}
                    }
                }]
            )
        elif step == 3:
            return AIMessage(
                content="Ticket TICKET-101 mentions call 'c-901'. Searching for telephony tools.",
                tool_calls=[{"id": "call_4", "name": "search_tools", "args": {"query": "telephony call"}}]
            )
        elif step == 4:
            return AIMessage(
                content="Querying call 'c-901' with Response Projection to retrieve only necessary fields.",
                tool_calls=[{
                    "id": "call_5",
                    "name": "invoke_read",
                    "args": {
                        "server": "telephony_api",
                        "tool": "get_call",
                        "arguments": {"call_id": "c-901"},
                        "fields": ["call_id", "status", "phone_number", "customer_email", "error_code"]
                    }
                }]
            )
        elif step == 5:
            return AIMessage(
                content="Call c-901 failed with SIP_500. Creating GitHub issue to alert engineering team.",
                tool_calls=[{
                    "id": "call_6",
                    "name": "invoke_write",
                    "args": {
                        "server": "github",
                        "tool": "create_issue",
                        "arguments": {
                            "title": "Critical Bug in Call c-901 (Ticket TICKET-101)",
                            "body": "SIP_500 failure detected during SMS verification. Affected contact: enterprise client."
                        }
                    }
                }]
            )
        else:
            return AIMessage(
                content=(
                    "Triage and remediation successfully completed:\n"
                    "1. Identified ticket TICKET-101 associated with failed call c-901.\n"
                    "2. Retrieved telephony data with sensitive contact PII redacted by the Gateway.\n"
                    "3. Upon human approval, created a GitHub issue to alert engineering."
                )
            )

async def build_gateway_agent(
    gateway_url: str = "http://127.0.0.1:8000/catalog/sse",
    checkpointer: Any = None
):
    """
    Builds the ReAct agent using LangGraph's official `create_react_agent`.

    1. Discovers tools dynamically via `MultiServerMCPClient`.
    2. Wraps mutating tools with `interrupt()`.
    3. Initializes standard LangGraph ReAct agent with persistence.
    """
    checkpointer = checkpointer or MemorySaver()

    # 1. Dynamic tools discovered via MCP protocol
    tools = await load_gateway_tools(gateway_url)

    # 2. Model (Gemini, OpenAI, or SimulatedPlanner fallback)
    model = get_chat_model(tools)
    if model is None:
        model = SimulatedPlannerModel(tools)

    # 3. LangGraph out-of-the-box ReAct agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        checkpointer=checkpointer
    )
    return agent
