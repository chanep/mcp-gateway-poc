import sqlite3
import json
import os
import logging
from mcp.server.fastmcp import FastMCP

logging.getLogger("mcp").disabled = True
logging.getLogger("mcp.server.lowlevel.server").disabled = True

DB_PATH = os.getenv("SQLITE_DB_PATH", "./data/tickets.db")
mcp = FastMCP("sqlite-jira-mock")

@mcp.tool()
def read_query(query: str) -> str:
    """Execute a SELECT SQL query on the engineering tickets database (columns: id, title, description, status, priority, assigned_to, call_id)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return json.dumps(rows, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def write_query(query: str) -> str:
    """Execute an INSERT or UPDATE SQL mutation query."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(query)
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return json.dumps({"status": "SUCCESS", "rows_affected": affected})
    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run(transport="stdio")
