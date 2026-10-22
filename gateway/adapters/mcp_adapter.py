import json
import sys
from typing import Any, Dict
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from gateway.adapters.base import BaseAdapter
from gateway.models import ServerDefinition

class McpAdapter(BaseAdapter):
    """
    Adapter that acts as an MCP Client consuming an upstream MCP server (P5 and P6).
    In this project, it connects to scripts/sqlite_mcp_server.py via stdio.
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
