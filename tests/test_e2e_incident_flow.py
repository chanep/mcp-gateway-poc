import asyncio
import os
import sys
import json
import time
import socket
import logging
import warnings
from pathlib import Path
from multiprocessing import Process
import uvicorn

sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

warnings.filterwarnings("ignore", category=UserWarning)

# Suppress noisy client-side library loggers
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from agent.graph import build_gateway_agent
from gateway.server import app as gateway_app
from mock_telephony.main import app as telephony_app

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

def run_gateway_server():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    uvicorn.run(gateway_app, host="127.0.0.1", port=8000, log_level="warning", access_log=False)

def run_telephony_server():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    uvicorn.run(telephony_app, host="127.0.0.1", port=8001, log_level="warning", access_log=False)

async def test_full_incident_triage():
    print("=" * 70, flush=True)
    print("RUNNING E2E TEST: Real LLM ReAct Agent + MCP Dynamic Proxy", flush=True)
    print("=" * 70, flush=True)

    # 0. Clean old audit log for pristine assertion
    audit_file = Path("logs/audit.jsonl")
    if audit_file.exists():
        audit_file.unlink()

    # 1. Start Telephony & Gateway if not already running
    proc_tel = None
    proc_gw = None

    if not is_port_in_use(8001):
        proc_tel = Process(target=run_telephony_server, daemon=True)
        proc_tel.start()

    if not is_port_in_use(8000):
        proc_gw = Process(target=run_gateway_server, daemon=True)
        proc_gw.start()

    time.sleep(2)  # Wait for services to be ready

    try:
        # 2. Initialize official LangGraph agent with real LLM
        gateway_url = "http://127.0.0.1:8000/catalog/sse"
        checkpointer = MemorySaver()
        agent = await build_gateway_agent(gateway_url=gateway_url, checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "test-session-e2e-real"}}

        user_query = (
            "Inspect ticket TICKET-101 in the ticketing system. "
            "If it references a failed call with call_id, retrieve call details "
            "from telephony and create an issue on GitHub alerting the team."
        )

        current_input = {"messages": [HumanMessage(content=user_query)]}
        interruption_detected = False
        pii_redacted_verified = False

        while True:
            async for event in agent.astream(current_input, config=config, stream_mode="values"):
                last_msg = event["messages"][-1]
                if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                    for tc in last_msg.tool_calls:
                        print(f"\n[AGENT DECISION] LLM selected tool: '{tc['name']}'", flush=True)
                elif isinstance(last_msg, AIMessage) and last_msg.content:
                    snippet = str(last_msg.content)[:220].replace("\n", " ")
                    print(f"\n[AGENT SUMMARY]: {snippet}...", flush=True)
                elif isinstance(last_msg, ToolMessage):
                    content = str(last_msg.content)
                    if "+1415****671" in content or "a****r@" in content:
                        pii_redacted_verified = True

            state = await agent.aget_state(config)
            if state.tasks and any(task.interrupts for task in state.tasks):
                interruption_detected = True
                interrupt_val = state.tasks[0].interrupts[0].value
                print("\n" + "#" * 60, flush=True)
                print("[HUMAN-IN-THE-LOOP CHECKPOINT TRIGGERED]:", flush=True)
                print(f"  Reason: {interrupt_val.get('message')}", flush=True)
                print(f"  Action: {interrupt_val.get('action')}", flush=True)
                print(f"  Payload: {interrupt_val.get('arguments')}", flush=True)
                print("  Status: AUTO-APPROVED BY SUPERVISOR", flush=True)
                print("#" * 60 + "\n", flush=True)

                # Resume with official LangGraph Command
                current_input = Command(resume={"approved": True})
            else:
                break

        # Final assertions
        assert interruption_detected, "ERROR: LangGraph did not interrupt invoke_write."
        print("\n[OK] 1. Human-in-the-loop successfully interrupted and prompted.", flush=True)

        assert pii_redacted_verified, "ERROR: PII Redaction was not detected in tool output."
        print("[OK] 2. PII Redaction verified at runtime.", flush=True)

        # 3. Verify in audit.jsonl that the issue was created by the Gateway
        assert audit_file.exists(), "ERROR: audit.jsonl not found."
        lines = audit_file.read_text(encoding="utf-8").strip().split("\n")
        records = [json.loads(line) for line in lines if line.strip()]

        issue_records = [r for r in records if r.get("tool") == "create_issue" and r.get("status") == "SUCCESS"]
        assert len(issue_records) > 0, "ERROR: Successful create_issue record not found in audit log."
        print(f"[OK] 3. Issue created and verified in Gateway audit log (Event: {issue_records[-1]['tool']} -> {issue_records[-1]['status']}).", flush=True)

        # 4. Verify global audit trail
        assert len(records) >= 3, f"ERROR: Insufficient audit records ({len(records)})"
        print(f"[OK] 4. Audit trail verified in audit.jsonl ({len(records)} total events recorded).", flush=True)

        print("\n" + "=" * 70, flush=True)
        print("DYNAMIC MCP FORWARDING & E2E TRIAGE COMPLETED SUCCESSFULLY")
        print("=" * 70, flush=True)

    finally:
        if proc_gw:
            proc_gw.terminate()
            proc_gw.join(timeout=2)
        if proc_tel:
            proc_tel.terminate()
            proc_tel.join(timeout=2)

if __name__ == "__main__":
    asyncio.run(test_full_incident_triage())
