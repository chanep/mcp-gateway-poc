import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gateway.catalog import CatalogService

async def run_tests():
    print("=== 1. Testing CatalogService & Discovery (P7) ===")
    catalog = CatalogService()

    # In-domain search
    res_jira = catalog.search_tools("engineering tickets")
    print(f"[OK] Search 'engineering tickets' found: {[r['tool'] for r in res_jira]}")
    assert any(r["tool"] == "read_query" for r in res_jira)

    res_call = catalog.search_tools("telephony call details")
    print(f"[OK] Search 'call' found: {[r['tool'] for r in res_call]}")
    assert any(r["tool"] == "get_call" for r in res_call)

    # Out-of-domain search
    res_weather = catalog.search_tools("current weather in buenos aires")
    print(f"[OK] Out-of-domain search ('weather') returned {len(res_weather)} results (expected 0).")
    assert len(res_weather) == 0

    print("\n=== 2. Testing Schemas ===")
    schema = catalog.get_tool_schema("jira_mock", "read_query")
    print(f"[OK] Schema retrieved for jira_mock.read_query: {schema['parameters']}")
    assert "query" in schema["parameters"]["properties"]

    print("\n=== 3. Testing SQLite Upstream Read (P5) ===")
    res_sql = await catalog.execute_tool(
        invoked_risk="read",
        server="jira_mock",
        tool="read_query",
        args={"query": "SELECT id, title, call_id FROM tickets WHERE id = 'TICKET-101'"}
    )
    print(f"[OK] SQLite read result: {res_sql}")
    assert len(res_sql) == 1
    assert res_sql[0]["id"] == "TICKET-101"
    assert res_sql[0]["call_id"] == "c-901"

    print("\n=== 4. Testing Risk Guard & Policy Enforcement (P2) ===")
    # Attempting to call a WRITE tool with invoke_read
    res_violation = await catalog.execute_tool(
        invoked_risk="read",
        server="github",
        tool="create_issue",
        args={"title": "Unauthorized Title", "body": "Bypass attempt"}
    )
    print(f"[OK] Attempt to run invoke_read on WRITE tool was blocked: {res_violation}")
    assert res_violation.get("error") == "SECURITY_POLICY_VIOLATION"

    print("\n=== 5. Testing CLI Wrapper (GitHub create_issue with invoke_write) ===")
    res_issue = await catalog.execute_tool(
        invoked_risk="write",
        server="github",
        tool="create_issue",
        args={"title": "Test SMS Bug", "body": "Reported during automated core test"}
    )
    print(f"[OK] Issue creation successful: {res_issue}")
    assert res_issue["status"] == "CREATED"

    print("\n=== 6. Testing Audit Logger (P3) ===")
    audit_file = Path("logs/audit.jsonl")
    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").strip().split("\n")
    print(f"[OK] Audit records generated: {len(lines)}")
    assert len(lines) >= 3

    print("\nALL GATEWAY CORE TESTS PASSED SUCCESSFULLY.")

if __name__ == "__main__":
    asyncio.run(run_tests())
