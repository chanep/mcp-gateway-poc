import asyncio
import os
import sys
import json
import time
from pathlib import Path
from multiprocessing import Process
import uvicorn

sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from agent.graph import build_gateway_agent
from gateway.server import app

def run_gateway_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

async def test_full_incident_triage():
    print("=" * 70)
    print("RUNNING E2E TEST: create_react_agent + MultiServerMCPClient")
    print("=" * 70)

    # 1. Start Gateway in background process
    proc = Process(target=run_gateway_server, daemon=True)
    proc.start()
    time.sleep(2)  # Wait for uvicorn to boot

    try:
        # 2. Initialize official LangGraph agent
        gateway_url = "http://127.0.0.1:8000/catalog/sse"
        checkpointer = MemorySaver()
        agent = await build_gateway_agent(gateway_url=gateway_url, checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "test-session-e2e"}}

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
                        print(f"  [LLM Requested]: {tc['name']} with {list(tc['args'].keys())}")
                elif isinstance(last_msg, ToolMessage):
                    content = str(last_msg.content)
                    print(f"  [Tool Response]: {content[:100]}...")
                    if "+1415****671" in content or "a****r@" in content:
                        pii_redacted_verified = True
                        print("     [VERIFIED]: Redacted PII detected in tool response!")

            state = await agent.aget_state(config)
            if state.tasks and any(task.interrupts for task in state.tasks):
                interruption_detected = True
                interrupt_val = state.tasks[0].interrupts[0].value
                print("\n  [HUMAN-IN-THE-LOOP DETECTED IN LANGGRAPH]:")
                print(f"     Reason: {interrupt_val.get('message')}")
                print(f"     Action: {interrupt_val.get('action')}")
                print("     Auto-approving for test run...\n")

                # Resume with official LangGraph Command
                current_input = Command(resume={"approved": True})
            else:
                break

        # Final assertions
        assert interruption_detected, "ERROR: LangGraph did not interrupt invoke_write."
        print("[OK] 1. Human-in-the-loop successfully interrupted and prompted.")

        assert pii_redacted_verified, "ERROR: PII Redaction was not detected in tool output."
        print("[OK] 2. PII Redaction verified at runtime.")

        # 3. Verify in audit.jsonl that the issue was created by the Gateway
        audit_file = Path("logs/audit.jsonl")
        assert audit_file.exists(), "ERROR: audit.jsonl not found."
        lines = audit_file.read_text(encoding="utf-8").strip().split("\n")
        records = [json.loads(line) for line in lines if line.strip()]

        issue_records = [r for r in records if r.get("tool") == "create_issue" and r.get("status") == "SUCCESS"]
        assert len(issue_records) > 0, "ERROR: Successful create_issue record not found in audit log."
        print(f"[OK] 3. Issue created and verified in Gateway audit log (Event: {issue_records[-1]['tool']} -> {issue_records[-1]['status']}).")

        # 4. Verify global audit trail
        assert len(records) >= 4, f"ERROR: Insufficient audit records ({len(records)})"
        print(f"[OK] 4. Audit trail verified in audit.jsonl ({len(records)} total events recorded).")

        print("\n" + "=" * 70)
        print("E2E TEST PASSED SUCCESSFULLY WITH OFFICIAL ARCHITECTURE")
        print("=" * 70)

    finally:
        proc.terminate()

if __name__ == "__main__":
    asyncio.run(test_full_incident_triage())
