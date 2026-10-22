import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["scripts/sqlite_mcp_server.py"]
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools disponibles en sqlite mcp:")
            for t in tools.tools:
                print(f"- {t.name}: {t.description}")
            
            res = await session.call_tool("read_query", arguments={"query": "SELECT id, title, call_id FROM tickets LIMIT 2"})
            print("\nResultado read_query:", [c.text for c in res.content])

if __name__ == "__main__":
    asyncio.run(main())

