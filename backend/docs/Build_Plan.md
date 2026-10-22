# ReRoute: build plan (demo-ready, deployable, matched to the target job stack)

Target stack to demonstrate: LangGraph, LangChain, LLM APIs (structured outputs), MCP, RAG, FastAPI, Python, Next.js, NestJS (or Express), AWS, plus LLM evaluation and regression testing (promptfoo).

## Rules (apply to every phase)
1. Sandbox only for travel: flight status, search, booking and hotel are simulated. No real airline, payment or booking API.
2. Real email is sent only in the running app, to the registered user. Tests and evals use a fake notifier.
3. Secrets come from env vars or the host's secret manager only. Keep `.env.example` current. Never commit `.env`.
4. Check current official docs before using any library API (FastAPI, SQLAlchemy 2.0 async, LangGraph/LangChain, MCP SDK, promptfoo, Next.js, NestJS, AWS). Pin versions.
5. Token economy: ONE phase per session. Read only files you need. Write files in batches. Never reprint large files or full test output; report pass/fail counts and failures only. Don't re-run recon. Edit in place; don't rewrite files to tweak them.
6. Don't break what exists. State what you change in existing files and why. If something is missing or ambiguous, pick the smallest sensible option, state it, continue.
7. Every phase ends with a Checkpoint (max 15 lines): files created/changed, commands, test + eval results, assumptions, next phase. Then STOP.
8. Keep a running `docs/AI_WORKFLOW.md`: for each phase, one short entry on which AI coding tool/model was used, what it was good at, one thing it got wrong and how it was caught and fixed. (This documents real AI-assisted-coding experience; write only what actually happened.)

## Existing (done)
Python 3.11, FastAPI async, SQLAlchemy 2.0 async + asyncpg, Postgres, Redis pub/sub channel `flight_events`, docker-compose. Models: User, Itinerary, FlightLeg, HotelBooking, PollLog, DecisionTrace. Consumer runs in the FastAPI lifespan. Detection and agent pipeline NOT built.

## Architecture principles
- Pure-function core: `handle_disruption(event, state, deps) -> DecisionResult`. No FastAPI, Redis or DB session inside it. Routes and the Redis consumer are thin callers.
- Side effects go through `Deps`: `trace_sink`, `inventory`, `llm`, `notifier`, `clock`, `retriever`. Prod uses real ones; tests use in-memory fakes.
- No `datetime.now()` or unseeded randomness in pipeline logic. Sandbox inventory is seeded with `search(...)` and `exists(flight_id)`.
- Policy engine is pure: `evaluate_policy(candidate, constraints, config) -> {verdict: APPROVED|REJECTED|ESCALATE, reasons[]}`. Thresholds are config.
- LLM PROPOSES, POLICY DISPOSES: the LLM chooses only among candidate flight IDs via structured output at temperature 0. The choice is always re-validated by the policy engine before booking. Invalid, hallucinated or non-compliant output, or no approved candidate, means ESCALATE with `new_flight=null`. If the LLM is down or over budget, fall back to deterministic ranking (earliest arrival, then lowest price) and record `llm_fallback=true`.
- Token and context discipline: count tokens per call; enforce a per-call context budget (truncate or summarize low-priority context such as long itineraries or retrieved chunks in a defined priority order, never drop the constraints or candidate list); record tokens_in/out and cost_usd per run; per-day LLM budget guard falls back to deterministic mode.
- Untrusted text (airline notices, user notes, retrieved documents) goes to the LLM only inside delimited data blocks; actions never depend on LLM free text.
- Notification facts (flight id, times, fare delta, hotel dates) are injected from structured data and verified in the final text; on mismatch use the deterministic template.
- Idempotency: a duplicate event for the same leg and disruption never causes a second rebooking.
- `DecisionResult`: event_id, detected, disruption_type (CANCELLED|DELAYED|MISSED_CONNECTION|DIVERTED|NONE), alternatives_considered[], policy_verdict, policy_reasons[], action (REBOOKED|HOTEL_ONLY|REBOOKED_AND_HOTEL|ESCALATED|NO_ACTION), new_flight|null, hotel|null, fare_delta, explanation, citations[], notification{subject, body}, trace_stages[], metrics{latency_ms, tokens_in, tokens_out, cost_usd}, error|null.
- Service split: FastAPI (Python) owns data, auth, pipeline and MCP. NestJS is a thin gateway/BFF in front of it. Next.js is the frontend.

## PHASE 1: Core pipeline
Build:
(Iss phase me hum agent ko ek broken flight denge aur wo uss broken flight ka alternate dhundh ke hume dega.)
- Pydantic schemas and config (policy thresholds, LLM provider/model via env, token budgets, SMTP/SendGrid, JWT, poller interval).
- `sandbox/inventory.py`: seeded Indian domestic routes (DEL, BOM, BLR, HYD, MAA, CCU, AMD, PNQ), airlines, times, cabins, INR fares, seats, hub connections, hotel inventory.
- `policy/engine.py` with named reason codes: fare-delta limit, cabin match, arrival-delay limit, departure after disruption + airport buffer, route integrity (allowed same-city alternates), downstream-leg feasibility, seat availability. All hard rules pass = APPROVED; a hard rule fails = REJECTED; soft breach or no valid candidate = ESCALATE. Return ALL failing reasons.
- `agent/`: detection; tools (`search_alternatives`, policy wrapper, `execute_rebooking` with fake PNR, `adjust_hotel` for late arrival and multi-night shifts); a LangGraph orchestrator (detect, search, choose, policy-check, execute, hotel, explain, notify, with conditional ESCALATE/NO_ACTION edges); `FakeLLM` with scripted outputs (good, hallucinated ID, over-budget, invalid JSON); `handle_disruption`.
- Token counting + context budgeter module with unit tests (priority-ordered truncation keeps constraints and candidates).
Tests: inventory determinism; 40+ table-driven policy cases including boundaries; pipeline tests for cancellation, delay, missed connection, no inventory, hotel shift, duplicate event, hallucinated LLM ID, LLM outage, over-budget context.

## PHASE 2: Events, traces, live feed
- Poller (lifespan task) logs EVERY check to `poll_log` and publishes disruptions to Redis.
- `POST /api/v1/events/simulate` (CANCELLED / DELAYED(minutes) / MISSED_CONNECTION for a chosen leg).
- Consumer builds state from DB, builds real `Deps`, calls `handle_disruption`, persists results, handles errors without dying.
- One `decision_trace` row per stage with full JSON snapshots (redact secrets/PII).
- WebSocket `/api/v1/ws/activity` streaming poll results, detection, each stage, final action.
- `GET /api/v1/metrics`: disruptions handled, auto-resolution and escalation rate, avg and p95 latency, avg fare delta, LLM fallback rate, avg tokens and cost per run (computed, not hardcoded). `GET /api/v1/itinerary/{id}/trace`.
Tests: simulate payload, trace completeness, metrics math, WebSocket sequence.

## PHASE 3: promptfoo evaluation harness (the differentiator)
- `backend/app/eval_adapter.py`: `run_scenario(scenario, seed)` builds in-memory state, seeded inventory, in-memory trace sink, fake clock, FakeNotifier, and a `fake_good`/`fake_bad`/`real` LLM per scenario; calls the same `handle_disruption`; returns the result dict; catches exceptions. No Postgres or Redis.
- `eval/`: `package.json` (pinned promptfoo), `promptfooconfig.yaml`, `provider.py` (custom Python provider; verify signature in current docs), `scenarios/*.yaml`, `asserts/{invariants,quality,helpers}.py`, `scripts/{generate_scenarios.py, pass_rate_gate.py, summarize_results.py}`, `README.md`.
- Invariants (zero tolerance, applied to EVERY scenario via `defaultTest`, each returning `{pass, score, reason}` with offending values): no_hallucinated_flight, price_cap_respected, no_time_travel, route_integrity, connection_feasible, escalate_when_no_valid_option, no_action_when_no_disruption, hotel_dates_consistent, trace_complete, no_crash, idempotent_duplicate_event, policy_always_validated, notification_facts_match, no_pii_or_secret_leak, deterministic_replay, context_budget_respected (constraints and candidates always present in the final prompt).
- Soft quality (score >= 0.8): best_option_chosen, latency_budget, explanation_present; plus an `llm-rubric` check on explanation clarity in `real` mode (cheap grader model from env, temperature 0).
- 50+ scenarios generated by `generate_scenarios.py` and committed as readable YAML: cancellation 8, delay 7, missed connection 6, no inventory 4, budget 5, hotel 5, conflicting constraints 4, no-disruption/noise 3 (incl. duplicate), malformed 4, prompt injection 5 (adversarial text in airline notice/reason/user note; assert same action as the clean scenario, cap holds, no leak), LLM-adversarial 4 (hallucinated ID, over-budget flight, bad cabin, invalid JSON; system must stay safe).
- `promptfooconfig.models.yaml` compares 2-3 real models on real-LLM scenarios (accuracy, cost, latency).
- Gate: exit non-zero if overall pass rate < 0.90, ANY invariant fails, or critical-severity pass rate < 1.0. Print a per-category table.
- Baseline story: run on the first working pipeline and commit `eval/results/baseline.json`. Fix root causes in the pipeline, never weaken assertions. Fill a "Baseline vs. Fixed" table in the README (first-run pass rate, failures by category, fixes, final pass rate). Show once that the gate fails on a deliberately broken invariant, then revert.
- `.github/workflows/eval.yml`: runs on PRs touching `backend/**` or `eval/**`; deterministic path needs no secrets; real-LLM scenarios run only if the secret exists and not on forks; uploads results artifact.

## PHASE 4: Auth and email
- bcrypt + JWT (FastAPI owns auth). `POST /auth/signup` (user, flight legs, hotel in one transaction; fake PNRs; reject duplicate emails), `POST /auth/login` (rate-limited, generic errors), `GET /itinerary` and detail/trace, all scoped to the authenticated user. Protect simulate, metrics, WebSocket.
- `Notifier` interface: `SmtpNotifier`, `SendGridNotifier`, `FakeNotifier`. Multipart HTML+text email: what happened, what was done, new flight, fare delta, hotel change, next steps; an "escalated, a human will contact you" variant. Async with retry/backoff; failures never break the pipeline; send status goes in the trace.
Tests: auth flows, cross-user isolation, notifier contract, template rendering, failure isolation.

## PHASE 5: RAG policy knowledge base + MCP server + assistant
RAG (lean, measured):
- `rag/`: ingest a small corpus in `data/policies/` (public passenger-rights/airline-policy documents or synthetic policy docs I provide; never invent real regulations). Each chunk keeps source file and section. pgvector in existing Postgres (verify setup), hybrid retrieval (vector + keyword) with reranking.
- Used ONLY to cite rules in explanations/escalations and in `/ask-policy`. RAG never overrides the deterministic policy engine. Abstain when retrieval confidence is low.
- Eval `eval/suites/rag.yaml`: 30+ questions with known source sections; assert correct citation, faithfulness (no claim unsupported by retrieved chunks), abstention on out-of-corpus questions, injection text inside a document is ignored. Report retrieval hit-rate, faithfulness, abstention rate, and a table comparing 2-3 chunking/reranking settings.
MCP + assistant:
- `mcp_server/` (verify current MCP Python SDK): read-only tools `get_itinerary`, `get_decision_trace`, `search_alternatives`, `search_policy`, plus sandbox-only `simulate_disruption`. Tools receive the authenticated user id from the server, never from model output.
- A LangGraph assistant agent that uses these tools (as an MCP client) to answer questions about the user's own trips and decisions, citing the trace stage or policy source it used. It cannot book, cancel or change anything.
- Eval `eval/suites/assistant.yaml`: 30+ cases: answers must match trace values exactly, refusal of other users' data, decline write requests, injection and tool-misuse attempts, "I don't know" on unanswerable questions. Invariants: no_cross_user_data, no_write_actions.

## PHASE 6: NestJS gateway + Next.js frontend
NestJS (thin BFF, TypeScript; Express acceptable only if NestJS blocks progress):
- Proxies REST to FastAPI, verifies the JWT, validates request bodies (class-validator or zod), applies rate limiting and CORS, relays the WebSocket/SSE activity stream, serves the eval summary JSON, exposes OpenAPI docs and a health endpoint. Keep it thin: no business logic, no duplicate auth or DB.
- Tests: proxy and auth-guard tests, rate-limit test.
Next.js (App Router, TypeScript, Tailwind; verify current APIs):
- Clean, light, enterprise-style UI (consistent spacing scale, neutral palette with one accent, accessible contrast). Separate pages, typed API client, TanStack Query, protected routes, loading/error/empty states, responsive.
- Pages: `/signup`, `/login`, `/dashboard`, `/itinerary`, `/alerts`, `/confirmation` (before/after, fare delta, explanation with citations), `/activity-log` (live feed + expandable stage trace), `/simulate`, `/assistant` (chat UI for the MCP assistant; reuse or adapt `langchain-ai/agent-chat-ui` ideas or code if the license allows, and credit it in the README), `/evaluation` (promptfoo summary: scenario count, pass rate by category, invariant status, RAG metrics, latency, baseline vs. fixed).
- One happy-path end-to-end test: signup, simulate cancellation, see confirmation.

## PHASE 7: Ship on AWS (deployable and demo-ready)
- Production Dockerfiles (multi-stage, non-root) for backend, gateway and frontend; `docker-compose.prod.yml`; health checks; env-driven config; Alembic migrations on start; CORS locked to the frontend origin.
- `scripts/seed_demo.py`: demo user with a realistic multi-leg itinerary and hotel so the demo works in one click.
- AWS (pick one path, give exact steps, verify current service docs): ECS Fargate or App Runner for FastAPI and NestJS; RDS Postgres with pgvector; ElastiCache Redis; Next.js on Amplify Hosting or as a container; ALB/HTTPS; Secrets Manager; CloudWatch logs and alarms. Provide Terraform or CDK, a GitHub Actions CD workflow (build, eval gate, push, deploy) that blocks deploys when the eval gate fails, a post-deploy smoke test (health, login, simulate, metrics, assistant), a teardown script, and an estimated monthly cost. Include a cheaper single-host fallback (Render/Railway/Fly.io) documented for demo periods.
- Docs: README (one-paragraph pitch, architecture diagram including the eval path, 3-minute demo script, headline numbers from every eval suite, live-link placeholders, limitations and future work); `ARCHITECTURE.md` (pure-function core, LLM proposes/policy disposes, context budgeting, deterministic sandbox, Redis vs. Kafka, why a thin BFF); `INTERVIEW_NOTES.md` (20 likely questions on LLMs, context windows, tokens, hallucinations, RAG, structured outputs, evals, MCP, agents, with concise answers); `docs/AI_WORKFLOW.md` finalized.
- Final checks: lint, type check, all test suites green, `docker compose up` works from a clean clone, no secrets committed, no network calls in the eval path.

## Definition of done
- Full flow works in Docker and on the deployed URL: signup, simulate, pipeline, trace, live feed, real email, assistant, all pages.
- `cd eval && npx promptfoo eval` runs with no services; 100+ scenarios/cases across pipeline, RAG and assistant suites; all invariants on every scenario; gate passing; CI green.
- Baseline vs. fixed pass rates documented with real numbers.
- The LLM provably cannot cause an invalid booking; the assistant provably cannot write or leak other users' data.
- CI/CD on AWS blocks deploys when the eval gate fails.