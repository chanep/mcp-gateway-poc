import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from multiprocessing import Process
import time
import uvicorn
from langchain_mcp_adapters.client import MultiServerMCPClient
from gateway.server import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

async def test_multiserver():
    proc = Process(target=run_server, daemon=True)
    proc.start()
    time.sleep(2)

    try:
        client = MultiServerMCPClient({
            "phonecentral_gateway": {
                "url": "http://127.0.0.1:8000/catalog/sse",
                "transport": "sse"
            }
        })
        tools = await client.get_tools()
        print(f"MultiServerMCPClient descubrió {len(tools)} tools:")
        for t in tools:
            print(f"- {t.name}: {t.description[:60]}...")
            
        search_t = [t for t in tools if t.name == "search_tools"][0]
        res = await search_t.ainvoke({"query": "tickets"})
        print("\nResultado search_tools vía MultiServerMCPClient:", res)
    finally:
        proc.terminate()

if __name__ == "__main__":
    asyncio.run(test_multiserver())

