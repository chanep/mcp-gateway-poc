# MCP Gateway Local con LangGraph (PoC Educativo)

Este proyecto es una Prueba de Concepto (PoC) que implementa la arquitectura de un **MCP Gateway empresarial** (inspirado en el [MCP Gateway de Uber](https://www.uber.com/us/en/blog/designing-mcp-gateway/) y la **Alternativa B** analizada para Dialpad), consumido por un agente inteligente construido con **LangGraph oficial** (`create_react_agent` + `MultiServerMCPClient`).

---

## 🎯 ¿Qué demuestra este proyecto?

Resuelve de forma práctica y local los **7 problemas clásicos** de la adopción descontrolada de agentes de IA:

| # | Problema Real | Solución en este Gateway |
|---|---|---|
| **P1** | **Setup frágil en cada laptop** | El agente solo se conecta a **1 URL** (`/catalog/sse`). No necesita tokens ni drivers de DB locales. |
| **P2** | **Credenciales humanas irrestrictas** | Separación estricta de riesgo (`read`, `write`, `destructive`). Si un LLM intenta borrar con `invoke_read`, el Gateway lo rechaza. |
| **P3** | **Cero observabilidad** | Registro estructurado en `logs/audit.jsonl` con métricas de duración, bytes y status por llamada. |
| **P4** | **PII cruda enviada al LLM** | Motor de **redacción en vuelo** (`redactor.py`). Teléfonos y emails son enmascarados antes de llegar al agente. |
| **P5** | **Fragmentación de herramientas** | Unifica un CLI wrapper (`gh`), un servidor MCP nativo (SQLite) y APIs REST bajo la misma interfaz. |
| **P6** | **APIs existentes sin tools** | **Declarative HTTP Mapping**: Endpoints REST existentes se exponen como tools con solo declararlos en YAML. |
| **P7** | **Contexto saturado ($O(1)$) y JSONs gigantes** | **Catálogo dinámico de 5 meta-tools** + **Response Projection** (parámetro `fields` para recortar campos innecesarios). |

---

## 🏗️ Arquitectura de Componentes

```text
[ Usuario / Terminal ]
         │
         ▼
[ Agente LangGraph Oficial ] ──(Descubrimiento dinámico)──► [ MCP Gateway (FastAPI + FastMCP) ]
  - create_react_agent                                         │  - Data Plane: Guard, Redactor, Projection, Audit
  - MultiServerMCPClient (SSE)                                 │  - Control Plane: registry.yaml
  - Human-in-the-loop selectivo (interrupt ante write)         ├──────────────────────────┐
                                                               ▼                          ▼
                                                      [ SQLite MCP Server ]     [ Mock Telephony REST API ]
                                                        (tickets.db - Jira)       (Calls & Customers con PII)
```

---

## 🚀 Guía Rápida de Uso

### 1. Requisitos Previos
Tener instalado Python 3.11+ y [`uv`](https://github.com/astral-sh/uv).

### 2. Inicializar la Base de Datos de Prueba
Genera la base SQLite `data/tickets.db` con tickets y datos de incidentes en inglés:
```bash
uv run python scripts/seed_db.py
```

### 3. Ejecutar el Test de Punta a Punta ("The Incident Triage")
Ejecuta el flujo completo automatizado levantando el Gateway en segundo plano y conectando el agente por HTTP SSE real:
```bash
uv run python tests/test_e2e_incident_flow.py
```

### 4. Modo Interactivo (Chat con el Agente)
Primero levanta el Gateway en una terminal:
```bash
uv run uvicorn gateway.server:app --port 8000 --reload
```
Y en otra terminal inicia la consola interactiva donde puedes chatear y autorizar (`[y/N]`) las mutaciones en vivo:
```bash
uv run python agent/cli.py
```
*Tip: Escribe `demo` para correr la consulta del incidente de llamadas o escribe tus propias preguntas.*

### 5. Inspeccionar Métricas y Catálogo
Con el servidor corriendo, puedes abrir en tu navegador o hacer `curl`:
- **`http://localhost:8000/catalog/sse`**: Endpoint oficial de SSE para cualquier cliente MCP (Claude Code, Cursor, LangChain).
- **`http://localhost:8000/catalog/tools`**: Vista humana del catálogo de tools disponibles.
- **`http://localhost:8000/metrics`**: Métricas de uso y tiempos de respuesta calculados a partir de `logs/audit.jsonl`.

---

## ⚙️ Configuración Opcional de LLM Real

Por defecto, si no configuras una API key, el agente corre con un **Planner Determinístico Educativo** que simula los pasos del LLM sin costo.

Para conectar un LLM real (Gemini u OpenAI), crea un archivo `.env`:
```ini
# Google Gemini
GEMINI_API_KEY="tu-api-key-de-gemini"
GEMINI_MODEL="gemini-2.5-flash"

# O OpenAI
# OPENAI_API_KEY="tu-api-key-de-openai"
# OPENAI_MODEL="gpt-4o-mini"
```

---

## 📂 Documentación Adicional

- [PLAN.md](PLAN.md): Plan de proyecto detallado con el diseño conceptual, analogía y equivalencias de Uber/Dialpad.
