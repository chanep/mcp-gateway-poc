import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from multiprocessing import Process
import time
from langchain_mcp_adapters.tools import load_mcp_tools
from gateway.server import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

async def test_discovery():
    proc = Process(target=run_server, daemon=True)
    proc.start()
    time.sleep(2)  # esperar que levante

    try:
        connection = {
            "transport": "sse",
            "url": "http://127.0.0.1:8000/catalog/sse"
        }
        print("Conectando al Gateway vía MCP SSE y descubriendo tools dinámicamente...")
        tools = await load_mcp_tools(session=None, connection=connection)
        print(f"\n¡Tools descubiertas dinámicamente por protocolo MCP ({len(tools)})!:")
        for t in tools:
            print(f"- {t.name}: {t.description.strip().splitlines()[0]}")
            print(f"  params: {list(t.args.keys())}")
    finally:
        proc.terminate()

if __name__ == "__main__":
    asyncio.run(test_discovery())
