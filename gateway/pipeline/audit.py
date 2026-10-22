from typing import Optional
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("logs/audit.jsonl")

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
