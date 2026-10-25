import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Dict, Any, Annotated
from pydantic import Field
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from gateway.catalog import CatalogService

class QuietNoiseFilter(logging.Filter):
    """Suppresses raw HTTP 202/200 SSE access logs and internal MCP protocol messages."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "/catalog/messages" in msg or "/catalog/sse" in msg:
            return False
        if "Processing request of type" in msg or "Dispatching request of type" in msg:
            return False
        return True

# Apply at import time
_noise_filter = QuietNoiseFilter()
for _name in ("uvicorn.access", "mcp", "mcp.server.lowlevel.server"):
    logging.getLogger(_name).addFilter(_noise_filter)

# 1. Instantiate MCP Server with domain boundary instructions
mcp_server = FastMCP(
    "phonecentral-mcp-gateway",
    instructions=(
        "This MCP Gateway centralizes ONLY PhoneCentral internal engineering systems: "
        "ticket management (Jira / tickets.db), repositories and PRs (GitHub), "
        "and internal telephony APIs (UV/FST). It does not contain external tools, "
        "weather, news, or general world knowledge."
    )
)

catalog = CatalogService()

# 2. The 5 Dynamic Meta-Tools of the Unified Catalog
@mcp_server.tool()
def search_tools(
    query: Annotated[str, Field(description="Keywords describing the capability or domain to search for (e.g. 'call', 'ticket', 'issue')")],
    limit: Annotated[int, Field(default=5, description="Maximum number of matching tools to return")] = 5
) -> str:
    """
    Step 1 of Gateway workflow: Search available upstream tools across PhoneCentral internal engineering systems (Jira/tickets, GitHub repositories, telephony APIs).
    Returns matching server names, tool names, risk levels, and brief descriptions.
    Do not use for weather, news, or general world knowledge.
    """
    results = catalog.search_tools(query, limit)
    return json.dumps(results, ensure_ascii=False)

@mcp_server.tool()
def get_tool_schema(
    server: Annotated[str, Field(description="Name of the backend server returned by search_tools")],
    tool: Annotated[str, Field(description="Name of the tool returned by search_tools")]
) -> str:
    """
    Step 2 of Gateway workflow: Inspect the full JSON input schema and required arguments for a tool discovered via `search_tools` before invoking it.
    """
    try:
        schema = catalog.get_tool_schema(server, tool)
        return json.dumps(schema, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp_server.tool()
async def invoke_read(
    server: Annotated[str, Field(description="Name of the backend server")],
    tool: Annotated[str, Field(description="Name of the read-only tool on that server")],
    arguments: Annotated[Optional[Dict[str, Any]], Field(default=None, description="Input parameters dictionary matching the tool's schema")] = None,
    fields: Annotated[Optional[List[str]], Field(default=None, description="Response Projection: optional list of specific field names to extract from the response payload (e.g. ['id', 'status']). Always specify `fields` when the user only needs specific attributes from a record to minimize payload size and token usage.")] = None
) -> str:
    """
    Step 3 of Gateway workflow (Read): Execute a READ-ONLY upstream tool (risk: read).
    Automatically enforces PII Redaction and optional Response Projection (`fields`).

    Response Projection (Context Optimization):
    - When the query requires only specific attributes from the upstream response, pass those key names in `fields` (e.g. fields=['id', 'status']).
    - The Gateway filters the payload at the boundary and returns only the requested keys.
    - Omit `fields` only when the full record is needed.
    """
    result = await catalog.execute_tool(
        invoked_risk="read",
        server=server,
        tool=tool,
        args=arguments or {},
        fields=fields,
        agent_id="langgraph-agent"
    )
    return json.dumps(result, ensure_ascii=False)

@mcp_server.tool()
async def invoke_write(
    server: Annotated[str, Field(description="Name of the backend server")],
    tool: Annotated[str, Field(description="Name of the mutating tool on that server")],
    arguments: Annotated[Optional[Dict[str, Any]], Field(default=None, description="Input parameters dictionary matching the tool's schema")] = None
) -> str:
    """
    Step 3 of Gateway workflow (Write): Execute a MUTATING upstream tool (risk: write), such as creating issues or updating records.
    Triggers Human-in-the-loop approval before execution.
    """
    result = await catalog.execute_tool(
        invoked_risk="write",
        server=server,
        tool=tool,
        args=arguments or {},
        agent_id="langgraph-agent"
    )
    return json.dumps(result, ensure_ascii=False)

@mcp_server.tool()
async def invoke_destructive(
    server: Annotated[str, Field(description="Name of the backend server")],
    tool: Annotated[str, Field(description="Name of the destructive tool on that server")],
    arguments: Annotated[Optional[Dict[str, Any]], Field(default=None, description="Input parameters dictionary matching the tool's schema")] = None
) -> str:
    """
    Step 3 of Gateway workflow (Destructive): Execute a DESTRUCTIVE upstream tool (risk: destructive).
    Rejects execution if the tool is not classified as destructive in the registry.
    """
    result = await catalog.execute_tool(
        invoked_risk="destructive",
        server=server,
        tool=tool,
        args=arguments or {},
        agent_id="langgraph-agent"
    )
    return json.dumps(result, ensure_ascii=False)

# 3. Lifespan to suppress noisy HTTP access logs & discover dynamic MCP tools
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure filter is active even after Uvicorn initializes handlers
    for name in ("uvicorn.access", "mcp", "mcp.server.lowlevel.server"):
        l = logging.getLogger(name)
        l.addFilter(_noise_filter)
        l.setLevel(logging.WARNING)
    # Dynamically discover tools from upstream MCP servers (P5/P6 dynamic forwarding)
    await catalog.initialize()
    yield

# 4. FastAPI App with Observability endpoints and mounted MCP SSE sub-app
app = FastAPI(
    title="PhoneCentral MCP Gateway",
    description="Centralized tool gateway for AI coding agents (inspired by Uber).",
    lifespan=lifespan
)

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "mcp-gateway",
        "servers_configured": list(catalog.registry.config.servers.keys())
    }

@app.get("/catalog/tools")
def list_catalog_tools():
    """HTTP endpoint for human inspection of the complete tool catalog."""
    tools = []
    for s_name, server in catalog.registry.config.servers.items():
        for t_name, tool in server.tools.items():
            tools.append({
                "server": s_name,
                "tool": t_name,
                "risk": tool.risk,
                "redact_keys": tool.redact,
                "description": tool.description
            })
    return {"total_tools": len(tools), "tools": tools}

@app.get("/metrics")
def get_metrics():
    """Returns metrics aggregated from audit.jsonl (P3 - Observability)."""
    audit_path = Path("logs/audit.jsonl")
    if not audit_path.exists():
        return {"total_calls": 0, "status": "No audit records yet"}

    lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
    records = [json.loads(line) for line in lines if line.strip()]

    total_duration = sum(r.get("duration_ms", 0) for r in records)
    total_bytes = sum(r.get("bytes_out", 0) for r in records)

    return {
        "total_calls": len(records),
        "total_bytes_transferred": total_bytes,
        "avg_duration_ms": round(total_duration / len(records), 2) if records else 0,
        "recent_calls": records[-5:]
    }

# Mount MCP SSE sub-app
app.mount("/catalog", mcp_server.sse_app())
