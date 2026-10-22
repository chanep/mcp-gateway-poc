import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from multiprocessing import Process
import time
import uvicorn
from langchain_mcp_adapters.tools import load_mcp_tools
from gateway.server import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

async def test_tool_execution():
    proc = Process(target=run_server, daemon=True)
    proc.start()
    time.sleep(2)

    try:
        connection = {
            "transport": "sse",
            "url": "http://127.0.0.1:8000/catalog/sse"
        }
        tools = await load_mcp_tools(session=None, connection=connection)
        tools_by_name = {t.name: t for t in tools}
        
        search_tool = tools_by_name["search_tools"]
        print("Llamando a search_tools dinámicamente a través de SSE...")
        res = await search_tool.ainvoke({"query": "tickets de ingenieria"})
        print("Resultado devuelto por el Gateway:", res)
    finally:
        proc.terminate()

if __name__ == "__main__":
    asyncio.run(test_tool_execution())

