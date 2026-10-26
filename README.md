# Enterprise MCP Gateway with Autonomous LangGraph Agent

A reference implementation and Proof of Concept (PoC) demonstrating an **Enterprise Model Context Protocol (MCP) Gateway** inspired by [Uber's MCP Gateway architecture](https://www.uber.com/us/en/blog/designing-mcp-gateway/). The gateway acts as a secure, observable intermediary between AI coding/incident triage agents and enterprise backend systems, consumed by an autonomous ReAct agent built with **LangChain / LangGraph** (`create_agent` + `MultiServerMCPClient`).

> [!NOTE]
> **Case Study Context**: *PhoneCentral* is a fictional cloud communications and telephony SaaS enterprise used throughout this project to model real-world microservices, telephony APIs, Jira ticketing, and developer workflows within a sanitized, reproducible environment.

---

## 🎯 Enterprise Challenges Addressed

As engineering teams adopt AI coding assistants (such as Claude Code, Cursor, or autonomous agents), ad-hoc integrations introduce severe security, governance, and cost challenges. This Gateway addresses the 7 fundamental enterprise pain points:

| # | Enterprise Challenge | Gateway Architectural Solution |
|---|---|---|
| **P1** | **Fragmented Local Setup** (N laptops × N tokens) | Agents connect to a **single endpoint** (`/catalog/sse`). Zero local database drivers or upstream API credentials required on developer machines. |
| **P2** | **Over-Privileged Human Credentials** | Risk-tiered execution (`read`, `write`, `destructive`). Write operations require Human-in-the-Loop (`interrupt()`); server-side guards reject destructive attempts disguised as reads. |
| **P3** | **Zero Central Observability** | Structured audit trail (`logs/audit.jsonl`), real-time console tracing (`[GATEWAY REQUEST]`, `[GATEWAY SECURITY]`, `[GATEWAY RESPONSE]`), and metrics (latency, payload size, HTTP status). |
| **P4** | **Raw PII Ingestion by Cloud LLMs** | **In-flight boundary redaction** (`redactor.py`). Customer phone numbers, emails, and identifiers are sanitized before responses enter the LLM context. |
| **P5** | **Transport & Tool Fragmentation** | Unifies dynamic upstream MCP servers (`tools/list` forwarding), local SQLite databases, and REST APIs under a standardized interface. |
| **P6** | **Internal APIs Without Agent Tooling** | **Declarative HTTP Mapping**: Internal REST endpoints are exposed as agent tools via simple YAML declarations in `registry.yaml` without modifying backend services. |
| **P7** | **Context Window Bloat & Giant Payloads** | **Unified 5 Meta-Tool Catalog** ($O(1)$ initial context) + **Response Projection** (GraphQL-style key extraction via `fields` parameter with failsafe fallback). |

---

## 🏗️ Architecture & Component Topology

```text
[ Developer CLI / Host Agent ]
             │
             ▼
[ Autonomous LangGraph Agent ] ──(Dynamic MCP SSE)──► [ Enterprise MCP Gateway (FastAPI + FastMCP) ]
  • LangChain v1.4+ create_agent                         │  • Control Plane: registry.yaml (Tool policies & schemas)
  • MultiServerMCPClient (SSE)                           │  • Data Plane: AuthZ Guard, PII Redactor, Projection, Audit
  • Native Human-in-the-Loop (interrupt on write)        │  • Noise Filter: Clean operational logs (--no-access-log)
  • Gemini 3.5 Flash Lite / OpenAI                       ├────────────────────────────┐
                                                         ▼                            ▼
                                               [ SQLite MCP Server ]       [ Mock Telephony REST API ]
                                                (tickets.db - Jira)       (Port 8001: Calls, SIP & PII)
```

### The 5 Dynamic Meta-Tools
Instead of injecting dozens of individual tool schemas into the agent's prompt, the Gateway exposes only 5 dynamic meta-tools:
1. `search_tools(query: str, limit: int)`: Discovers upstream tools across connected backends by semantic intent.
2. `get_tool_schema(server: str, tool: str)`: Inspects full JSON input/output schemas for a discovered tool on-demand.
3. `invoke_read(server: str, tool: str, arguments: dict, fields: list[str])`: Executes read operations with PII redaction and Response Projection.
4. `invoke_write(server: str, tool: str, arguments: dict)`: Executes mutating operations (triggers LangGraph HITL approval).
5. `invoke_destructive(server: str, tool: str, arguments: dict)`: Executes destructive operations, strictly validated against registry policies.

---

## 📊 Measured Impact & Key Results

* **~90% Reduction in Startup Tool Overhead**: Consolidates 80+ distributed tools across multiple MCPs and CLI manuals into **5 meta-tools**, bringing initial session tool overhead from `~25,000 tokens` to `<800 tokens`.
* **85% – 90% Payload Token Savings (Response Projection)**: By passing `fields=['error_code']` on telephony call records, response size drops from 407 bytes to 47 bytes (**88.5% reduction**), preventing context saturation in multi-turn triage sessions.
* **Zero PII Leakage**: 100% of declared sensitive fields (`phone_number`, `customer_email`) are masked prior to agent delivery.
* **Clean Separation of Concerns**: Zero tool mechanics hardcoded in the agent's system prompt; discovery and parameter semantics are communicated strictly over the MCP protocol (`tools/list`).

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (fast Python package and environment manager)

### 2. Environment Configuration
Create a `.env` file in the project root:
```ini
# Google Gemini (Recommended)
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3.5-flash-lite"

# Optional: OpenAI Alternative
# OPENAI_API_KEY="your-openai-api-key"
# OPENAI_MODEL="gpt-4o-mini"
```

### 3. Initialize the Sample Database
Generate the mock SQLite database (`data/tickets.db`) with sample Jira incident records:
```bash
uv run python scripts/seed_db.py
```

### 4. Automated End-to-End Verification
Run the self-contained E2E incident triage test suite (spawns background services, verifies dynamic tool discovery, PII redaction, audit logging, and Human-in-the-Loop checkpoints):
```bash
uv run python tests/test_e2e_incident_flow.py
```

---

## 💻 Interactive Agent CLI Execution

To run the live distributed system across decoupled terminals:

#### Terminal 1 — Telephony REST Service (Port 8001)
```bash
uv run uvicorn mock_telephony.main:app --port 8001 --reload
```

#### Terminal 2 — Enterprise MCP Gateway (Port 8000)
```bash
uv run uvicorn gateway.server:app --port 8000 --reload --no-access-log
```

#### Terminal 3 — Interactive LangGraph Agent
```bash
uv run python agent/cli.py
```

> [!TIP]
> **Quick Interactive Test**: Type `demo` in the agent CLI to trigger the incident triage investigation workflow, or enter custom prompts such as `"give me the error code for call c-901"` to watch Response Projection optimize the payload live.

> [!NOTE]
> **Windows Port Troubleshooting**: If a previous Uvicorn process retained port `8000` or `8001`, free the port in PowerShell:
> ```powershell
> Stop-Process -Id (Get-NetTCPConnection -LocalPort 8001).OwningProcess -Force
> ```

---

## 🔍 Observability & Live Inspection

When the Gateway is active, inspect endpoints directly via browser or `curl`:
* **`http://localhost:8000/catalog/sse`**: MCP SSE connection endpoint for any MCP client (Claude Code, Cursor, LangChain).
* **`http://localhost:8000/catalog/tools`**: Human-readable catalog inspection listing registered tools, upstream routes, risk tiers, and redaction policies.
* **`http://localhost:8000/metrics`**: Aggregated performance metrics (total invocations, transferred bytes, average latency) calculated from `logs/audit.jsonl`.

---

## 📂 Design Documentation

* [Architecture Analysis & Case Study (Spanish)](mcp-gateway-uber-vs-phonecentral.md): In-depth architectural analysis comparing Uber's MCP Gateway design with enterprise cloud communications platforms.
* [Project Plan & Specification](mcp-gateway-project-plan.md): Architectural roadmap, component specifications, and phased implementation criteria.
