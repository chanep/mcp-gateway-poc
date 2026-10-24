import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_FILE = Path("logs/audit.jsonl")

def _truncate_str(val: Any, max_len: int = 140) -> str:
    s = json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val
    if len(s) > max_len:
        return s[:max_len] + "... [truncated]"
    return s

def log_gateway_request(
    action: str,
    target: str,
    arguments: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None
):
    """Prints incoming tool invocation or meta-tool request."""
    print(f"\n[GATEWAY REQUEST]  >> {action} | Target: {target}", flush=True)
    if arguments:
        args_str = _truncate_str(arguments, 160)
        print(f"    Arguments: {args_str}", flush=True)
    if extra:
        for k, v in extra.items():
            if v is not None:
                print(f"    {k}: {v}", flush=True)

def log_gateway_security(message: str):
    """Prints security interventions (e.g. PII redaction, policy rejection)."""
    print(f"[GATEWAY SECURITY]  {message}", flush=True)

def log_gateway_response(
    action: str,
    target: str,
    status: str,
    duration_ms: float,
    payload: Any,
    bytes_out: int = 0
):
    """Prints completed tool response with payload snippet and performance metrics."""
    dur_str = f"{duration_ms:.1f}ms"
    bytes_str = f"{bytes_out} bytes" if bytes_out > 0 else f"{len(str(payload).encode('utf-8'))} bytes"
    print(f"[GATEWAY RESPONSE] << {action} | Target: {target} | Status: {status} | Duration: {dur_str} | Size: {bytes_str}", flush=True)
    payload_str = _truncate_str(payload, 220)
    print(f"    Payload: {payload_str}", flush=True)

def log_audit_event(
    agent_id: str,
    server_name: str,
    tool_name: str,
    risk: str,
    duration_ms: float,
    status: str,
    bytes_out: int,
    error: Optional[str] = None
):
    """
    Records every interaction processed by the Data Plane into audit.jsonl (P3 - Observability).
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "server": server_name,
        "tool": tool_name,
        "risk": risk,
        "duration_ms": round(duration_ms, 2),
        "status": status,
        "bytes_out": bytes_out,
        "error": error
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
