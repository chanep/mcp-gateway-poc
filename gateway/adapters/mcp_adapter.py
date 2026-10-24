import json
import sys
from typing import Any, Dict
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from gateway.adapters.base import BaseAdapter
from gateway.models import ServerDefinition, ToolDefinition, ToolArg

class McpAdapter(BaseAdapter):
    """
    Adapter that acts as an MCP Client consuming an upstream MCP server (P5 and P6).
    Discovers tools dynamically via `session.list_tools()` and proxies calls.
    """
    def __init__(self, server_name: str, server_def: ServerDefinition):
        super().__init__(server_name, server_def)
        cmd = server_def.command or sys.executable
        if cmd == "python":
            cmd = sys.executable
        self.server_params = StdioServerParameters(
            command=cmd,
            args=server_def.args or []
        )

    async def discover_tools(self) -> Dict[str, ToolDefinition]:
        """
        Dynamically queries upstream MCP server via `list_tools()` to forward
        all tools, descriptions, and argument schemas automatically.
        Applies governance policies (default_risk, risk_overrides, redact_overrides).
        """
        tools = {}
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()

                for t in response.tools:
                    # Parse input schema into ToolArg objects
                    args = {}
                    schema = t.inputSchema or {}
                    props = schema.get("properties", {})
                    req = schema.get("required", [])

                    for prop_name, prop_def in props.items():
                        args[prop_name] = ToolArg(
                            type=prop_def.get("type", "string"),
                            description=prop_def.get("description"),
                            required=(prop_name in req),
                            default=prop_def.get("default")
                        )

                    # Determine risk level from overrides or default
                    risk = self.server_def.risk_overrides.get(
                        t.name,
                        self.server_def.default_risk or "read"
                    )
                    redact = self.server_def.redact_overrides.get(t.name, [])

                    tools[t.name] = ToolDefinition(
                        name=t.name,
                        server_name=self.server_name,
                        risk=risk,
                        description=t.description or f"Tool '{t.name}' forwarded from {self.server_name}",
                        args=args,
                        redact=redact
                    )
        return tools

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Any:
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=args)

                if not result.content:
                    return None

                raw_text = result.content[0].text
                try:
                    return json.loads(raw_text)
                except Exception:
                    return raw_text
