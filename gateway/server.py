import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from gateway.catalog import CatalogService

# 1. Instantiate MCP Server with domain boundary instructions
mcp_server = FastMCP(
    "dialpad-mcp-gateway",
    instructions=(
        "This MCP Gateway centralizes ONLY Dialpad internal engineering systems: "
        "ticket management (Jira / tickets.db), repositories and PRs (GitHub), "
        "and internal telephony APIs (UV/FST). It does not contain external tools, "
        "weather, news, or general world knowledge."
    )
)

catalog = CatalogService()

# 2. The 5 Dynamic Meta-Tools of the Unified Catalog
@mcp_server.tool()
def search_tools(query: str, limit: int = 5) -> str:
    """
    Search tools in the Dialpad internal engineering catalog (Jira, GitHub, telephony).
    Do not use for weather, news, or general knowledge.
    """
    results = catalog.search_tools(query, limit)
    return json.dumps(results, ensure_ascii=False)

@mcp_server.tool()
def get_tool_schema(server: str, tool: str) -> str:
    """
    Get full JSON Schema and parameter descriptions for a discovered tool in the catalog.
    """
    try:
        schema = catalog.get_tool_schema(server, tool)
        return json.dumps(schema, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp_server.tool()
async def invoke_read(server: str, tool: str, arguments: Optional[Dict[str, Any]] = None, fields: Optional[List[str]] = None) -> str:
    """
    Execute a READ-ONLY tool (risk: read).
    Automatically applies PII Redaction (P4) and Response Projection (P7).
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
async def invoke_write(server: str, tool: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """
    Execute a MUTATING tool (risk: write).
    Triggers Human-in-the-loop review on the agent.
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
async def invoke_destructive(server: str, tool: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """
    Execute a DESTRUCTIVE tool (risk: destructive).
    Rejects execution if the tool was not declared destructive in the registry.
    """
    result = await catalog.execute_tool(
        invoked_risk="destructive",
        server=server,
        tool=tool,
        args=arguments or {},
        agent_id="langgraph-agent"
    )
    return json.dumps(result, ensure_ascii=False)

# 3. FastAPI App with Observability endpoints and mounted MCP SSE sub-app
app = FastAPI(
    title="Dialpad MCP Gateway",
    description="Centralized tool gateway for AI coding agents (inspired by Uber)."
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
