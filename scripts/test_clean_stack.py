import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from multiprocessing import Process
import time
import uvicorn
from langchain_core.tools import StructuredTool, BaseTool
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt
from gateway.server import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

def wrap_tool_with_hitl(tool: BaseTool) -> BaseTool:
    orig_coroutine = tool.coroutine

    async def _guarded_coroutine(**kwargs):
        approval = interrupt({
            "action": tool.name,
            "arguments": kwargs,
            "message": f"Acción de riesgo '{tool.name}' requiere aprobación humana."
        })
        if isinstance(approval, dict) and approval.get("approved"):
            return await orig_coroutine(**kwargs)
        return "[OPERACIÓN RECHAZADA POR EL USUARIO]"

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=_guarded_coroutine
    )

async def test_full_clean_stack():
    proc = Process(target=run_server, daemon=True)
    proc.start()
    time.sleep(2)

    try:
        # 1. MultiServerMCPClient oficial
        mcp_client = MultiServerMCPClient({
            "gateway": {
                "url": "http://127.0.0.1:8000/catalog/sse",
                "transport": "sse"
            }
        })
        raw_tools = await mcp_client.get_tools()
        print(f"1. Tools descubiertas por MultiServerMCPClient: {[t.name for t in raw_tools]}")

        # 2. Envolver solo las mutadoras con HITL dinámico
        tools = []
        for t in raw_tools:
            if t.name in ("invoke_write", "invoke_destructive"):
                tools.append(wrap_tool_with_hitl(t))
            else:
                tools.append(t)
        print("2. Tools de riesgo envueltas con HITL dinámico.")

        # 3. Probar ejecución de una tool segura directamente
        search_t = [t for t in tools if t.name == "search_tools"][0]
        res = await search_t.ainvoke({"query": "tickets"})
        print("3. Ejecución directa de tool segura search_tools:", res[:80], "...")

    finally:
        proc.terminate()

if __name__ == "__main__":
    asyncio.run(test_full_clean_stack())

