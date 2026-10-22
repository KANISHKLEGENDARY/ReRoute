# Autonomous Travel-Disruption Concierge — System Architecture

This document serves as the living technical blueprint and comprehensive interview reference for the **Autonomous Travel-Disruption Concierge** system. It details the system architecture, file/module responsibilities, data flow, and key design decisions made at each build step.

---

## 1. High-Level Architecture Diagram

```
                +-----------------------------------------------+
                |           Flight-Status Event Source          |
                | (Self-Built Background Poller / POST /simulate)|
                +-----------------------+-----------------------+
                                        |
                                        v  [JSON Event Payload]
                        +---------------+---------------+
                        |       Redis Event Bus         |
                        |   Channel: "flight_events"    |
                        +---------------+---------------+
                                        |
                                        v  [Pub/Sub Broadcast]
                        +---------------+---------------+
                        |   Redis Background Consumer   |
                        |     (FastAPI Lifespan Task)   |
                        +---------------+---------------+
                                        |
                 +----------------------+----------------------+
                 |                                             |
                 v                                             v
+-------------------------------+             +----------------------------------+
|      FastAPI REST Layer       |             |   Detection & Agent Pipeline     |
| - Health & Diagnostics        |             |   (Built in subsequent steps)    |
| - Auth (JWT)                  |             | - search_alternatives()          |
| - Itinerary CRUD              |             | - evaluate_policy()              |
| - WebSocket Log Feeds         |             | - execute_rebooking()            |
+---------------+---------------+             +----------------+-----------------+
                |                                              |
                +----------------------+-----------------------+
                                       |
                                       v
                    +------------------+------------------+
                    |        PostgreSQL Database          |
                    | - users                             |
                    | - itinerary                         |
                    | - flight_leg                        |
                    | - hotel_booking                     |
                    | - poll_log                          |
                    | - decision_trace                    |
                    +-------------------------------------+
```

---

## 2. Directory & Module Structure

```text
ReRoute/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── health.py        # Probes DB/Redis and provides test event dispatch
│   │   │       └── router.py        # Consolidates v1 API route namespaces
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings singleton with .env parsing
│   │   │   ├── database.py          # SQLAlchemy async engine, sessionmaker & get_db DI
│   │   │   └── redis.py             # Redis async client, pub/sub broadcaster & consumer
│   │   ├── models/                  # SQLAlchemy 2.0 Declarative ORM entities
│   │   │   ├── base.py              # Base DeclarativeBase and TimestampMixin
│   │   │   ├── user.py              # Traveler identity, email, hashed credentials
│   │   │   ├── itinerary.py         # Trip container linking legs, hotel, and traces
│   │   │   ├── flight_leg.py        # Flight segments, fare, cabin, PNR, status & poll_logs
│   │   │   ├── hotel.py             # Hotel bookings, confirmation ref, check-in dates
│   │   │   ├── trace.py             # Stage-by-stage AI & policy decision trace logs
│   │   │   └── __init__.py          # Export and metadata registration for all models
│   │   ├── schemas/
│   │   │   └── event.py             # Pydantic schemas for event validation & health
│   │   └── main.py                  # FastAPI application entrypoint with lifespan manager
│   ├── Dockerfile                   # Backend container definition (Python 3.11-slim)
│   ├── requirements.txt             # Direct Python dependencies
│   ├── .env.example                 # Template environment variables
│   └── .env                         # Active local environment configuration
├── docker-compose.yml               # Multi-container orchestration (Postgres, Redis, Backend)
├── travel-disruption-concierge-build-spec.md  # Original functional & technical specification
└── ARCHITECTURE.md                  # This file
```

---

## 3. Database Schema Reference

| Table Name | Primary Key | Foreign Keys | Key Columns | Purpose |
|---|---|---|---|---|
| `users` | `id` (int) | None | `name`, `email` (unique), `phone`, `password_hash`, `created_at` | Identity management and recipient address for genuine email notifications. |
| `itinerary` | `id` (int) | `user_id` -> `users.id` | `status`, `created_at` | Root trip container linking all segments, accommodations, and decision traces. |
| `flight_leg` | `id` (int) | `itinerary_id` -> `itinerary.id` | `leg_order`, `airline_code`, `flight_number`, `pnr`, `origin`, `destination`, `departure_datetime`, `cabin_class`, `fare_paid`, `currency`, `status` | Stores granular flight segment details. Enables connection tracking and fare delta comparison. |
| `hotel_booking` | `id` (int) | `itinerary_id` -> `itinerary.id` | `hotel_name`, `confirmation_reference`, `checkin_date`, `checkout_date`, `room_rate`, `currency`, `status` | Accommodations linked to the trip that may need autonomous date shifting. |
| `poll_log` | `id` (int) | `flight_leg_id` -> `flight_leg.id` | `status`, `checked_at` | Audit trail of every single scheduled flight-status check (including normal `ON_TIME`). Feeds dashboard activity stream. |
| `decision_trace` | `id` (int) | `itinerary_id` -> `itinerary.id` | `stage`, `input_snapshot` (JSON), `output_snapshot` (JSON), `timestamp` | Step-by-step explainability record for AI and policy decisions; source for dynamic metric calculation. |

---

## 4. Key Architectural Decisions & Interview Trade-offs

### Decision 1: Async-First Architecture (FastAPI + Async SQLAlchemy + Asyncpg)
* **Rationale**: Disruption handling and flight monitoring are inherently I/O-bound operations (network calls to databases, Redis streams, external webhooks/emails). Using async primitives ensures the web server can handle hundreds of concurrent requests without blocking Python's single-threaded event loop.
* **Why not synchronous Flask/Django?**: Synchronous frameworks require one worker process/thread per concurrent request, drastically increasing memory overhead and leading to thread starvation under load.

### Decision 2: Decoupled Redis Pub/Sub Event Backbone
* **Rationale**: The flight-status monitor (producer) and the agent/detection engine (consumer) operate on independent cadences. Emitting events to a Redis pub/sub channel decouples the ingestion layer from processing logic.
* **Why not direct in-memory function calls?**: In-memory function calls couple the producer directly to the consumer within the same process. Redis pub/sub allows scaling the API and the background workers independently across separate containers/nodes.
* **Why not Apache Kafka?**: Kafka introduces significant operational complexity (KRaft/ZooKeeper, JVM overhead, partition management) that is unjustified for low-to-medium throughput disruption events where sub-millisecond in-memory routing is sufficient.

### Decision 3: Explicit JSON Snapshots in `decision_trace`
* **Rationale**: Machine learning and autonomous agent decisions require transparent auditability ("Explainable AI"). By storing full `input_snapshot` and `output_snapshot` JSON payloads per pipeline stage (`DETECTION`, `POLICY_EVALUATION`, `EXECUTE_REBOOKING`), the frontend can reconstruct the exact rationale behind every action.

### Decision 4: FastAPI `lifespan` vs. Legacy `@app.on_event`
* **Rationale**: Python's `asynccontextmanager` pattern (`lifespan`) provides a structured, fail-safe mechanism for managing resource lifecycles. Connection pools and background listeners are initialized before request serving begins, and cleanly drained on SIGTERM/shutdown to prevent connection leaks.

---

## 5. Agentic Orchestration, Tracing & Fallback Architecture (Part 2)

### 5.1 LangGraph StateGraph Execution Pipeline

The disruption pipeline executes as a pure-function LangGraph state machine:
```text
[Parse Notice (if present)] -> [Detect Disruption]
                                     |
               (Disrupted)           v           (Not Disrupted)
            +------------------------+------------------------+
            |                                                 |
            v                                                 v
[Search Alternatives & Filter]                       [Notify & Explain]
            |                                                 ^
            v                                                 |
[Agentic Planning & Propose-Validate-Revise Loop]             |
            |                                                 |
            v                                                 |
[Deterministic Policy Verification (Code Guardrail)] ---------+
            | (Approved)                                      | (Escalated)
            v                                                 |
[Execute Sandboxed Rebooking]                                 |
            |                                                 |
            v                                                 |
[Adjust Linked Hotel Reservation]                             |
            |                                                 |
            +-------------------------------------------------+
```

### 5.2 Full List of Trace Stages
Every stage is persisted into `decision_trace` with an indexed `event_id`, its own real completion `timestamp`, and execution `latency_ms`:

1. `DETECTION`: Evaluates flight cancellation, delay threshold, or missed connection.
2. `SEARCH_AND_POLICY_FILTER`: Queries candidate flights; snapshot lists only policy-approved flight IDs and `total_candidates_found`.
3. `TOOL_CALL`: Records every agent tool invocation (`search_alternatives`, `check_hotel_options`, `check_policy`) with Pydantic argument validation.
4. `LLM_SELECTION`: Captures structured model output, rationale, token usage, and fallback flags.
5. `POLICY_VERIFICATION`: Deterministic code-level guardrail verifying that the proposed alternative strictly complies with policy.
6. `BOOKING_AND_RESERVATION`: Creates new synthetic PNR and ticket confirmation.
7. `HOTEL_ADJUSTMENT`: Adjusts linked hotel check-in/out dates and late-arrival notes.
8. `NOTIFICATION`: Generates email summary with fact verification against structured data.
9. `RESULT`: Final per-event audit record containing `action`, `policy_verdict`, `new_flight`, `fare_delta_inr`, `llm_fallback`, `llm_fallback_reason`, `agent_steps`, `revisions_used`, `tool_calls`, `first_proposal_valid`, `tokens_in`, `tokens_out`, `cost_usd`, `cost_inr`, `latency_ms`, and `error`.

### 5.3 Deterministic Fallback & Fallback Reasons
If any LLM failure occurs, the system seamlessly falls back to the deterministic heuristic (earliest arrival time, then lowest price delta) without crashing:
- `none`: Real model call succeeded without fallback.
- `no_key`: `GOOGLE_API_KEY` was not configured (single warning logged; 0 tokens, $0.00 cost recorded).
- `model_not_found`: Configured model returned 404 or "model no longer available" (logged cleanly without key leakage).
- `rate_limit`: Provider returned 429 ResourceExhausted or quota exceeded after retrying with exponential backoff and jitter.
- `budget`: Daily LLM budget (`DAILY_LLM_BUDGET_USD`) or daily call limit (`DAILY_LLM_CALL_LIMIT`) reached.
- `invalid_output`: Model returned malformed JSON or exhausted revisions with hallucinated flight IDs.
- `outage`: Upstream endpoint unreachable or 5xx server error.

### 5.4 Rate Limiting & Budget Guards
1. **Async Rate Limiter**: Global asynchronous limiter enforcing `LLM_MAX_CONCURRENCY` and `LLM_MIN_INTERVAL_MS` minimum delay between calls.
2. **Backoff**: Exponential backoff with random jitter up to `LLM_MAX_RETRIES` on 429/5xx, honoring `Retry-After` headers.
3. **Timeouts**: Per-call timeout `LLM_TIMEOUT_SECONDS` and whole-pipeline timeout `PIPELINE_TIMEOUT_SECONDS`.
4. **Persisted Budget Guard**: Evaluates daily spending directly from persisted `RESULT` rows in the database (not in-memory counters). The day boundary is determined strictly by `deps.clock`, ensuring accurate calendar day resets.

---

## 6. Evaluation Architecture & Invariant Quality Gate (Phase 3)

### 6.1 Evaluation Harness Overview
The concierge pipeline is evaluated using a comprehensive regression and invariant testing suite powered by **Promptfoo** (`promptfoo: 0.124.1`) connected via a custom Python provider (`eval/provider.py`) to an in-memory execution adapter (`backend/app/eval_adapter.py`).

```
+-------------------------------------------------------------------------------+
|                           Promptfoo Test Runner                               |
|                     (eval/promptfooconfig.yaml)                               |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       Custom Provider (eval/provider.py)                      |
|                call_api(prompt, options, context) -> JSON Result              |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                   In-Memory Adapter (backend/app/eval_adapter.py)             |
|          run_scenario(scenario) -> handle_disruption(event, state, deps)      |
|               (Zero external network, database, or Redis dependencies)        |
+-------------------+---------------------------------------+-------------------+
                    |                                       |
                    v                                       v
+---------------------------------------+   +-----------------------------------+
|     22 Zero-Tolerance Invariants      |   |        Soft Quality Metrics       |
|      (eval/asserts/invariants.py)     |   |      (eval/asserts/quality.py)    |
| - no_hallucinated_flight              |   | - best_option_chosen (>= 0.8)     |
| - price_cap_respected                 |   | - latency_budget                  |
| - connection_feasible_upstream        |   | - explanation_present             |
| - connection_feasible_downstream      |   | - explanation_clarity_rubric      |
| - hotel_dates_consistent              |   |   (LLM-rubric grader via          |
| - no_pii_or_secret_leak               |   |    gemini-3.1-flash-lite at temp 0)|
| - deterministic_replay (seed-fixed)   |   +-----------------------------------+
+---------------------------------------+
                    |
                    v
+-------------------------------------------------------------------------------+
|                         CI Quality Gate (pass_rate_gate.py)                   |
| - Overall Pass Rate >= 90.0%                                                  |
| - Zero Invariant Violations (100% adherence)                                  |
| - Critical Severity Pass Rate == 100.0%                                       |
+-------------------------------------------------------------------------------+
```

### 6.2 Scenario Corpus
The evaluation corpus spans **61 fake-mode scenarios** (13 categories) and **12 real-LLM scenarios**:
1. `cancellation` (8): Single-leg cancellations, multi-airline options, cabinet constraints.
2. `delay` (7): Minor delays (< 60m no action), major delays (> 120m rebooking), cross-midnight delays.
3. `missed_connection` (6): Upstream arrival feasibility, downstream departure feasibility, sequential cascades.
4. `no_inventory` (4): Zero available alternatives triggering deterministic escalation.
5. `budget` (5): Fare delta cap adherence, boundary delta tests, tight limits.
6. `hotel` (5): Date synchronization, late-night check-in notes, multi-night bookings.
7. `conflicting_constraints` (4): Impossible simultaneous criteria escalating cleanly.
8. `duplicate_noise` (3): Idempotent deduplication and out-of-order event handling.
9. `malformed` (4): Missing payload fields, invalid types, corrupted schemas.
10. `notice_parsing` (3): Unstructured email/SMS parsing (clean cancellation, noise, advisory).
11. `prompt_injection` (5): Adversarial text in notices/reasons (price override, prompt leak, SQLi, XSS). All critical severity.
12. `traveler_preferences` (3): Preference strings strictly subordinate to policy constraints.
13. `adversarial_llm` (4): Rejected-then-valid revisions, infinite loops, hallucinated ID exhaustion.
14. `real` (12): Live Gemini execution on `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`.

### 6.3 Shared Quota Counter & Pacing Protection
All real LLM calls route through `GeminiLLMClient` backed by `app/agent/llm_safety.py`:
- **Persistent Shared Counter (`.llm_usage`)**: Cross-process atomic tracking of call attempts per model per Pacific day.
- **80% Hard Stop**: Aborts real calls at 80% daily quota (400 for 500/day models), safely falling back to deterministic heuristic.
- **Concurrency 1 & Pacing**: Enforces minimum spacing between API calls ((60 / rpm) * 1.2 = 4.8s for 15 rpm models) to prevent 429 ResourceExhausted errors.
- **Zero API Calls in Fake Mode**: Verified via `.llm_usage` remaining unchanged before and after test runs.

---

## 7. Model Context Protocol (MCP) Interface
The MCP server (`mcp_server/server.py`) exposes ReRoute to external LLM clients like Claude Desktop and the MCP Inspector over standard input/output (`stdio`).
It serves as a thin wrapper calling existing FastAPI endpoints (`/api/v1/metrics`, `/api/v1/events`, `/api/v1/events/{id}`, `/api/v1/events/simulate`) via `httpx` with zero database or pipeline imports.
The server provides four tools:
1. `get_metrics()`: Returns aggregate disruption handling metrics, auto-resolution rates, and latencies.
2. `list_recent_events(limit)`: Lists recent disruption outcomes with action, flight leg, and latency.
3. `get_event_trace(event_id)`: Fetches the full stage-by-stage decision trace and final result snapshot.
4. `simulate_disruption(flight_leg_id, event_type, notice_text)`: Dispatches a disruption event through the existing simulation endpoint.
All simulated disruptions operate exclusively on sandbox inventory (no real airline/hotel APIs) and strictly adhere to the shared LLM call counter and rate-pacing guards.

