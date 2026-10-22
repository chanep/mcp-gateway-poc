import httpx
from typing import Any, Dict
from gateway.adapters.base import BaseAdapter
from gateway.models import ServerDefinition

class HttpAdapter(BaseAdapter):
    """
    Adapter that declaratively maps tool calls to existing REST API endpoints (P6 - Existing APIs as tools).
    """
    def __init__(self, server_name: str, server_def: ServerDefinition):
        super().__init__(server_name, server_def)
        self.base_url = (server_def.base_url or "").rstrip("/")

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Any:
        tool_def = self.server_def.tools.get(tool_name)
        if not tool_def:
            raise ValueError(f"Tool '{tool_name}' not found on server '{self.server_name}'")

        method = (tool_def.method or "GET").upper()
        raw_path = tool_def.path or ""

        # Replace path variables (e.g., /api/calls/{call_id})
        url_path = raw_path
        query_params = {}
        body_payload = {}

        for k, v in args.items():
            token = f"{{{k}}}"
            if token in url_path:
                url_path = url_path.replace(token, str(v))
            else:
                if method in ("GET", "DELETE"):
                    query_params[k] = v
                else:
                    body_payload[k] = v

        full_url = f"{self.base_url}{url_path}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if method == "GET":
                    resp = await client.get(full_url, params=query_params)
                elif method == "POST":
                    resp = await client.post(full_url, json=body_payload, params=query_params)
                elif method == "PUT":
                    resp = await client.put(full_url, json=body_payload, params=query_params)
                elif method == "DELETE":
                    resp = await client.delete(full_url, params=query_params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                if resp.status_code >= 400:
                    return {
                        "error": f"HTTP {resp.status_code}",
                        "detail": resp.text
                    }
                return resp.json()
        except httpx.ConnectError:
            # In-memory fallback if the mock service on 8001 is not running in another terminal
            try:
                from mock_telephony.main import CALLS_DB, CUSTOMERS_DB
                if "call_id" in args:
                    call = CALLS_DB.get(args["call_id"])
                    if call:
                        return call
                    return {"error": "HTTP 404", "detail": f"Call {args['call_id']} not found"}
                if "customer_id" in args:
                    cust = CUSTOMERS_DB.get(args["customer_id"])
                    if cust:
                        return cust
                    return {"error": "HTTP 404", "detail": f"Customer {args['customer_id']} not found"}
            except Exception:
                pass
            return {"error": "CONNECTION_REFUSED", "detail": f"Could not connect to {full_url}"}
