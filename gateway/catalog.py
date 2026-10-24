import time
from typing import Any, Dict, List, Optional
from thefuzz import fuzz
from gateway.registry import RegistryManager
from gateway.pipeline.guard import validate_risk_level, GuardException
from gateway.pipeline.redactor import redact_sensitive_data
from gateway.pipeline.projection import apply_response_projection
from gateway.pipeline.audit import (
    log_audit_event,
    log_gateway_request,
    log_gateway_response,
    log_gateway_security
)

class CatalogService:
    def __init__(self, registry_manager: Optional[RegistryManager] = None):
        self.registry = registry_manager or RegistryManager()

    async def initialize(self):
        """Asynchronously discover upstream MCP tools on startup."""
        await self.registry.initialize()

    def search_tools(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Intent-based tool discovery (P7 - Omni Catalog Discovery).
        Matches the query against tool name, server name, and description.
        If the query is out of domain (e.g., weather or sports), returns an empty list.
        """
        self.registry.ensure_tools_loaded()
        start_time = time.perf_counter()
        log_gateway_request(action="search_tools", target=f"query='{query}'", extra={"Limit": limit})

        scored_tools = []
        q = query.lower().strip()

        for s_name, server in self.registry.config.servers.items():
            for t_name, tool in server.tools.items():
                corpus = f"{s_name} {t_name} {tool.description} {server.description}".lower()

                # Token set ratio for flexible keyword matching in English and Spanish
                score = fuzz.token_set_ratio(q, corpus)

                # Minimum relevance threshold: filters out queries outside internal engineering domain
                if score >= 50:
                    scored_tools.append({
                        "score": score,
                        "server": s_name,
                        "tool": t_name,
                        "risk": tool.risk,
                        "summary": tool.description
                    })

        scored_tools.sort(key=lambda x: x["score"], reverse=True)
        results = [
            {
                "server": item["server"],
                "tool": item["tool"],
                "risk": item["risk"],
                "summary": item["summary"]
            }
            for item in scored_tools[:limit]
        ]

        duration_ms = (time.perf_counter() - start_time) * 1000
        summary_items = [f"{r['server']}.{r['tool']} ({r['risk']})" for r in results]
        log_gateway_response(
            action="search_tools",
            target=f"query='{query}'",
            status="SUCCESS",
            duration_ms=duration_ms,
            payload=summary_items if summary_items else "No matching tools in catalog."
        )

        return results

    def get_tool_schema(self, server: str, tool: str) -> Dict[str, Any]:
        """
        Returns JSON Schema and description for a specific tool in the catalog.
        """
        start_time = time.perf_counter()
        log_gateway_request(action="get_tool_schema", target=f"{server}.{tool}")

        tool_def = self.registry.get_tool(server, tool)

        properties = {}
        required = []

        for arg_name, arg_def in tool_def.args.items():
            prop: Dict[str, Any] = {"type": arg_def.type}
            if arg_def.description:
                prop["description"] = arg_def.description
            if arg_def.default is not None:
                prop["default"] = arg_def.default
            properties[arg_name] = prop

            if arg_def.required:
                required.append(arg_name)

        schema = {
            "name": f"{server}.{tool}",
            "server": server,
            "tool": tool,
            "risk": tool_def.risk,
            "description": tool_def.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

        duration_ms = (time.perf_counter() - start_time) * 1000
        param_summary = list(properties.keys())
        log_gateway_response(
            action="get_tool_schema",
            target=f"{server}.{tool}",
            status="SUCCESS",
            duration_ms=duration_ms,
            payload={"risk": tool_def.risk, "parameters": param_summary}
        )
        return schema

    async def execute_tool(
        self,
        invoked_risk: str,
        server: str,
        tool: str,
        args: Dict[str, Any],
        fields: Optional[List[str]] = None,
        agent_id: str = "langgraph-agent"
    ) -> Dict[str, Any]:
        """
        Full Data Plane pipeline:
        1. AuthZ & Risk Guard (P2)
        2. Execution via Adapter
        3. PII Redaction (P4)
        4. Response Projection (P7)
        5. Observability & Audit Logging (P3)
        """
        start_time = time.perf_counter()
        tool_def = self.registry.get_tool(server, tool)
        adapter = self.registry.get_adapter(server)

        # 1. Observability - Log incoming request
        extra_fields = {"Projection Fields": fields} if fields else None
        log_gateway_request(
            action=f"invoke_{invoked_risk}",
            target=f"{server}.{tool}",
            arguments=args,
            extra=extra_fields
        )

        # 2. Risk Guard
        try:
            validate_risk_level(invoked_risk, tool_def)
        except GuardException as ge:
            duration_ms = (time.perf_counter() - start_time) * 1000
            log_gateway_security(f"Policy Rejection: {ge}")
            log_gateway_response(
                action=f"invoke_{invoked_risk}",
                target=f"{server}.{tool}",
                status="FORBIDDEN_POLICY_VIOLATION",
                duration_ms=duration_ms,
                payload={"error": str(ge)},
                bytes_out=0
            )
            log_audit_event(
                agent_id=agent_id,
                server_name=server,
                tool_name=tool,
                risk=invoked_risk,
                duration_ms=duration_ms,
                status="FORBIDDEN_POLICY_VIOLATION",
                bytes_out=0,
                error=str(ge)
            )
            return {"error": "SECURITY_POLICY_VIOLATION", "detail": str(ge)}

        # 3. Execution via Adapter
        status = "SUCCESS"
        error_msg = None
        raw_result = None

        try:
            raw_result = await adapter.execute(tool, args)
        except Exception as e:
            status = "EXECUTION_ERROR"
            error_msg = str(e)
            raw_result = {"error": "ADAPTER_EXECUTION_FAILED", "detail": str(e)}

        # 4. PII Redaction
        redacted_result = redact_sensitive_data(raw_result, tool_def.redact)
        if tool_def.redact:
            log_gateway_security(f"PII Redaction applied to keys: {tool_def.redact}")

        # 5. Response Projection
        projected_result = apply_response_projection(redacted_result, fields)

        # 6. Observability - Log response & audit event
        duration_ms = (time.perf_counter() - start_time) * 1000
        bytes_out = len(str(projected_result).encode("utf-8"))

        log_gateway_response(
            action=f"invoke_{invoked_risk}",
            target=f"{server}.{tool}",
            status=status,
            duration_ms=duration_ms,
            payload=projected_result,
            bytes_out=bytes_out
        )

        log_audit_event(
            agent_id=agent_id,
            server_name=server,
            tool_name=tool,
            risk=invoked_risk,
            duration_ms=duration_ms,
            status=status,
            bytes_out=bytes_out,
            error=error_msg
        )

        return projected_result
