# ReRoute — Autonomous Travel-Disruption Concierge

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_Loop-purple.svg)](https://github.com/langchain-ai/langgraph)
[![MCP](https://img.shields.io/badge/MCP-2.3.0_Stdio-orange.svg)](https://modelcontextprotocol.io/)
[![React](https://img.shields.io/badge/React-18.3-61DAFB.svg)](https://react.dev/)
[![Eval Pass Rate](https://img.shields.io/badge/Eval_Pass_Rate-100%25-brightgreen.svg)](#evaluation--benchmarks)

**ReRoute** is an enterprise-grade autonomous travel concierge that detects flight disruptions (cancellations, cascading delays, missed connections), evaluates alternatives using a cyclic agentic state machine, enforces hard business policy constraints, and atomically synchronizes linked hotel bookings without human intervention.

---

## Key Capabilities

- **Cyclic Agentic Decision Loop**: Built on **LangGraph** using a **propose-validate-revise** pattern powered by **Google Gemini Flash Lite** with structured output enforcement.
- **Deterministic Policy Guardrails**: Hard price caps (₹5,000 max fare delta), layover connection buffers, delay caps, and multi-entity date synchronization (flight + hotel).
- **Production Defense-in-Depth**:
  - Prompt-injection isolation on raw notices.
  - Explanation fact verification against structured records.
  - Pacing limiter and shared Pacific-day call counter (`.llm_usage`) enforcing an **80% daily budget circuit breaker**.
  - Sub-second deterministic fallback (<25 ms) on rate limits, budget caps, or network outages.
- **Model Context Protocol (MCP)**: Official stdio MCP server enabling **Claude Desktop** and the **MCP Inspector** to query real-time metrics, inspect stage execution traces, and dispatch sandbox simulations safely.
- **Real-Time Operations Dashboard**: Built with **React 18 + Vite**, streaming pipeline stages live over **WebSockets** with Recharts analytics.
- **100% Regression Suite**: 61-scenario evaluation corpus across 13 failure modes evaluated against 22 zero-tolerance invariants.

---

## System Architecture

```text
               +---------------------------------------------------+
               | Flight Event Source (Poller / POST /api/v1/simulate)|
               +-------------------------+-------------------------+
                                         | [JSON Event Payload]
                                         v
                         +---------------+---------------+
                         |        Redis Pub/Sub          |
                         |   Channel: "flight_events"    |
                         +---------------+---------------+
                                         |
                                         v
                         +---------------+---------------+
                         |   Redis Background Consumer   |
                         |     (FastAPI Lifespan Task)   |
                         +---------------+---------------+
                                         |
                  +----------------------+----------------------+
                  |                                             |
                  v                                             v
+-------------------------------+             +----------------------------------+
|      FastAPI REST Layer       |             |   Pure-Function Agent Pipeline   |
| - /api/v1/metrics             |             | handle_disruption(event, b, deps)|
| - /api/v1/events              |             | - LangGraph Propose/Revise       |
| - /api/v1/ws/activity (WS)    |             | - Policy Engine Guardrails       |
| - /api/v1/events/simulate     |             | - Atomic Hotel Date Adjustment   |
+---------------+---------------+             +----------------+-----------------+
                |                                              |
                +----------------------+-----------------------+
                                       |
                                       v
                    +------------------+------------------+
                    |       Database (Async SQLAlchemy)   |
                    |   PostgreSQL / SQLite Storage       |
                    | - itinerary / flight_leg / hotel    |
                    | - decision_trace audit logs         |
                    +-------------------------------------+
```

---

## Performance & Cost Metrics

| Metric | Measured Value | Description |
| :--- | :--- | :--- |
| **Eval Pass Rate** | **100.0%** (61/61) | Zero invariant failures across 13 disruption categories (up from 75.4% baseline) |
| **Deterministic Fallback Latency** | **< 25 ms** | Sub-second rule-based execution when LLM is unavailable or budget cap reached |
| **Full LLM Agent Latency** | **~4.0 seconds** | End-to-end multi-step agent loop with Gemini Lite structured tool calls |
| **Cost per Disruption Run** | **$0.00005 (~₹0.004)** | 472 prompt tokens / 56 output tokens using Gemini Flash Lite pricing |
| **Safety Invariants** | **22 Zero-Tolerance Checks** | 0 hallucinated flight IDs, 0 fare cap breaches, 0 PII leaks |
| **Daily Quota Safety** | **80% Circuit Breaker** | Atomic cross-process Pacific-day tracker halts API calls at 400 req/day |

---

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2.0 (Async), Pydantic v2, PostgreSQL / SQLite (`aiosqlite`), Redis Pub/Sub, `httpx`.
- **AI & Agentic Framework**: LangGraph, LangChain, Google Gemini API (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`).
- **Integrations**: Model Context Protocol (MCP 2.3.0) stdio server for Claude Desktop.
- **Frontend**: React 18, Vite, React Router v6, Recharts, Plain Vanilla CSS.
- **Testing & Evals**: Pytest, Pytest-Asyncio, Promptfoo LLM evaluation harness.

---

## Quickstart

### 1. Prerequisites & Environment Setup
Clone the repository and set up your Python environment:
```powershell
# Install backend dependencies
pip install -r backend/requirements.txt
pip install -r mcp_server/requirements.txt

# Copy example environment configuration
cp backend/.env.example backend/.env
```

### 2. Start the Backend Server
```powershell
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
API documentation is available at `http://localhost:8000/docs`.

### 3. Start the Frontend Dashboard
In a separate terminal:
```powershell
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` to access:
- **Overview**: Real-time KPI metric cards, action distributions, and latency charts.
- **Live Feed**: WebSocket activity feed streaming pipeline stages as disruptions occur.
- **Events & Traces**: Historical disruption outcomes with expandable JSON stage inspector.
- **Simulate**: Sandbox scenario injector (cancellations, delays, missed connections).
- **Evaluation**: Benchmark comparisons (baseline vs. fixed pass rates).

### 4. Connect Claude Desktop via MCP
Add the server to your Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "reroute": {
      "command": "python",
      "args": ["C:\\path\\to\\ReRoute\\mcp_server\\server.py"],
      "env": {
        "BACKEND_URL": "http://localhost:8000",
        "DEMO_API_KEY": ""
      }
    }
  }
}
```
Or debug interactively with the MCP Inspector:
```powershell
npx.cmd @modelcontextprotocol/inspector python mcp_server/server.py
```

---

## Running Tests

Run the backend test suite:
```powershell
python -m pytest backend/tests
```

Run the MCP server unit tests:
```powershell
python -m pytest tests/test_mcp_server.py
```

Build the production frontend bundle:
```powershell
cd frontend
npm run build
```

---

## Repository Structure

```text
ReRoute/
├── backend/
│   ├── app/
│   │   ├── agent/        # LangGraph loop, Gemini client, safety guards, budget tracking
│   │   ├── api/          # FastAPI routers (metrics, events, simulation, websockets)
│   │   ├── core/         # Config, database session factory, Redis pub/sub
│   │   ├── models/       # SQLAlchemy 2.0 async ORM models
│   │   ├── policy/       # Deterministic policy engine & business validation rules
│   │   ├── sandbox/      # In-memory flight inventory & mock airline datasets
│   │   └── services/     # Background poller, consumer, and trace sink
│   └── tests/            # Full async backend test suite
├── eval/                 # 61-scenario evaluation corpus, invariants, Promptfoo configs
├── frontend/             # React + Vite operational dashboard with Recharts & WebSockets
├── mcp_server/           # Stdio Model Context Protocol (MCP) server for Claude Desktop
├── tests/                # Root tests (MCP unit test suite)
├── ARCHITECTURE.md       # Detailed technical specification and architectural blueprint
└── README.md             # Project documentation and quickstart
```
