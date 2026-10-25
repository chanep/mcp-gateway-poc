from typing import List
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.types import interrupt

def wrap_tool_with_hitl(tool: BaseTool) -> BaseTool:
    """
    Wraps mutating tools (write/destructive) with native LangGraph Human-in-the-Loop.
    Read tools (read/search/schema) execute automatically without interruption.
    """
    orig_coroutine = tool.coroutine

    async def _guarded_coroutine(**kwargs):
        # Trigger native LangGraph interrupt
        user_approval = interrupt({
            "action": tool.name,
            "arguments": kwargs,
            "message": f"Security Review Required: Action '{tool.name}' requires human approval."
        })
        if isinstance(user_approval, dict) and user_approval.get("approved"):
            return await orig_coroutine(**kwargs)
        return "[OPERATION CANCELLED BY USER]: The action was denied."

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=_guarded_coroutine
    )

async def load_gateway_tools(
    gateway_url: str = "http://127.0.0.1:8000/catalog/sse"
) -> List[BaseTool]:
    """
    Dynamically discovers tools from the MCP Gateway using the official
    `langchain-mcp-adapters` (MultiServerMCPClient).

    Selectively wraps mutating/destructive tools with dynamic Human-in-the-Loop.
    """
    client = MultiServerMCPClient({
        "phonecentral_gateway": {
            "url": gateway_url,
            "transport": "sse"
        }
    })

    # Automated discovery via MCP wire protocol
    raw_tools = await client.get_tools()

    # Wrap only risky tools with HITL
    guarded_tools = []
    for t in raw_tools:
        if t.name in ("invoke_write", "invoke_destructive"):
            guarded_tools.append(wrap_tool_with_hitl(t))
        else:
            guarded_tools.append(t)

    return guarded_tools
