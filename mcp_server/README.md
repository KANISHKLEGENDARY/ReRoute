# ReRoute MCP Server

A Model Context Protocol (MCP) server that exposes the ReRoute Autonomous Travel-Disruption Concierge to MCP clients like Claude Desktop and the MCP Inspector over standard I/O (`stdio`).

This server is a thin HTTP wrapper calling ReRoute's existing FastAPI backend endpoints via `httpx`. It contains no database or pipeline logic, maintaining strict separation of concerns.

---

## 1. Setup & Requirements

### Install Dependencies
```powershell
pip install -r mcp_server/requirements.txt
```

### Ensure the ReRoute Backend is Running
The MCP server forwards requests to the FastAPI backend:
```powershell
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 2. Configuration (Environment Variables)

- `BACKEND_URL`: ReRoute FastAPI base URL (default: `http://localhost:8000`).
- `DEMO_API_KEY`: Optional key sent as the `X-Demo-Key` header when triggering disruption simulations. *(Note: This key is never logged or printed).*

---

## 3. Running the Server

### Standalone (stdio)
```powershell
python mcp_server/server.py
```

### Testing with the MCP Inspector
Launch the official interactive MCP Inspector to test tools in your browser:
```powershell
npx.cmd @modelcontextprotocol/inspector python mcp_server/server.py
```
*(Or specify the absolute Python executable path if running outside active PATH):*
```powershell
npx.cmd @modelcontextprotocol/inspector "C:\Users\Kanishk Garg\AppData\Local\Programs\Python\Python311\python.exe" "C:\Users\Kanishk Garg\Downloads\ReRoute\mcp_server\server.py"
```

---

## 4. Claude Desktop Configuration (Windows)

To connect ReRoute to Claude Desktop on Windows, edit your configuration file:
`%APPDATA%\Claude\claude_desktop_config.json`

Add the `reroute` server block with absolute paths:

```json
{
  "mcpServers": {
    "reroute": {
      "command": "C:\\Users\\Kanishk Garg\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
      "args": [
        "C:\\Users\\Kanishk Garg\\Downloads\\ReRoute\\mcp_server\\server.py"
      ],
      "env": {
        "BACKEND_URL": "http://localhost:8000",
        "DEMO_API_KEY": ""
      }
    }
  }
}
```

Restart Claude Desktop. The ReRoute tools will appear with hammer icons in the chat composer.

---

## 5. Available Tools

1. `get_metrics()`: Returns aggregate system metrics (disruptions handled, auto-resolution rate, escalation rate, avg/p95 latency, average cost, LLM fallback rate).
2. `list_recent_events(limit=10)`: Returns recent disruption events with action taken, flight leg ID, policy verdict, and latency (max limit: 50).
3. `get_event_trace(event_id)`: Retrieves the stage-by-stage decision trace (`DETECTION`, `SEARCH_AND_POLICY_FILTER`, `LLM_SELECTION`, `POLICY_VERIFICATION`, `RESULT`) and final rationale.
4. `simulate_disruption(flight_leg_id, event_type, notice_text="")`: Triggers a sandbox disruption event (`CANCELLED`, `DELAYED`, or `MISSED_CONNECTION`) through the concierge pipeline.

---

## 6. Example Questions to Ask in Claude Desktop

1. *"What is our current auto-resolution rate and average pipeline latency across all handled disruptions?"*
2. *"List the 5 most recent flight disruption events, and pull the complete decision trace for the first one."*
3. *"Simulate a flight cancellation for flight leg 1 with notice 'Technical delay at DEL airport' and explain the rebooking result."*
