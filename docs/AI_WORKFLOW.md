# AI Workflow Log

## Phase 1: Core Pipeline & Pure Disruption Engine

- **AI Coding Tool & Model**: Antigravity with Gemini 3.7 Flash.
- **What it was good at**: Rapidly architecting a clean, pure-function core (`handle_disruption`), implementing the LangGraph StateGraph with conditional edges, structured fallback mechanisms, deterministic policy guardrails with 7 distinct rule checks, and building comprehensive table-driven tests.
- **One thing it got wrong and how it was caught/fixed**: In the initial 42-case policy engine test matrix, the test parameter fixtures set departure time offset to 0 minutes relative to the disruption time for non-departure test cases. The policy engine correctly enforced the 45-minute airport departure buffer rule and rejected those candidates. Caught by pytest (`assert REJECTED == APPROVED`); fixed by adjusting the fixture's departure offset to 60 minutes so only the explicit buffer test cases probe the boundary condition.

## Phase 2: Events, Traces, Live Feed, and Metrics

- **AI Coding Tool & Model**: Antigravity with Gemini 3.7 Flash.
- **What it was good at**: Implementing the background flight poller lifespan task, building the Redis event consumer hydrating state from Postgres, implementing recursive PII and secrets scrubbing for decision trace snapshots, writing the dynamic metrics calculation endpoint, and broadcasting real-time activity events over WebSockets.
- **One thing it got wrong and how it was caught/fixed**: When executing the Phase 2 tests importing `app.main`, SQLAlchemy's async SQLite driver threw `ModuleNotFoundError: No module named 'aiosqlite'` because the library was listed in `requirements.txt` but had not yet been installed in the local Python environment. Caught during initial test collection; resolved by executing `pip install aiosqlite`.

## Part 1: Live Path Fix, Tracing, Metrics & Housekeeping

- **AI Coding Tool & Model**: Antigravity with Gemini 2.5 / 3.7 Flash.
- **What it was good at**: Diagnosing the root cause of the live consumer pipeline failure (offset-naive vs offset-aware datetime subtraction crash and missing BOM-GOI route fares in sandbox inventory), introducing indexed `event_id` across trace schemas, building event idempotency guards, and rewriting `/metrics` to aggregate per distinct `event_id` from `RESULT` rows.
- **One thing it got wrong and how it was caught/fixed**: In `redact_pii_and_secrets`, a naive substring match for `"token"` scrubbed numeric token metrics `tokens_in` and `tokens_out` into `"[REDACTED]"`, causing string/float casting errors in metrics math. Caught while testing the metrics endpoint; resolved by explicitly whitelisting token metric keys and using defensive float casting in `metrics.py`.

## Part 2: Real LLM Wiring and Agentic Upgrade

- **AI Coding Tool & Model**: Antigravity with Gemini 2.5 / 3.7 Flash.
- **What it was good at**: Integrating Google Gemini via `langchain-google-genai` at temperature 0 with async concurrency and interval rate limiting, implementing retired-model (404) and rate-limit (429) backoff safety, building the LangGraph propose-validate-revise loop with Pydantic tool argument validation, isolating untrusted notice text, ensuring route-unique flight IDs with realistic route durations, and writing `list_models.py` and `llm_smoke.py`.
- **One thing it got wrong and how it was caught/fixed**: In `FakeLLM.choose_alternative` for `propose_rejected_then_valid` mode, the initial proposal selected `candidate_ids[-1]`. Because `candidate_ids` contained only pre-approved candidates, the policy engine approved it immediately without triggering any revisions. Caught by `assert out["revisions_used"] >= 1` in pytest; resolved by having revision 1 propose an intentional policy-violating candidate (`6E-REJECTED-FARE-EXCEEDED`) so the revision loop is exercised and verified.

## Phase 3A: Promptfoo Evaluation Harness & Baseline Invariant Run

- **AI Coding Tool & Model**: Antigravity with Gemini 3.8 Flash (High).
- **What it was good at**: Architecting the in-memory evaluation adapter `eval_adapter.py` with multi-event state propagation, configuring Promptfoo with a custom Python provider (`call_api`) and 22 zero-tolerance invariant assertions via `defaultTest`, generating the first 20 YAML scenarios across 8 categories, and verifying the expected baseline failure of `connection_feasible_upstream` without touching PostgreSQL, Redis, or making real API calls.
- **One thing it got wrong and how it was caught/fixed**: When Promptfoo's YAML parser parsed unquoted flight numbers like `6E-204`, it interpreted them as scientific notation numbers (`6e-204`), causing a Pydantic `string_type` validation error in `DisruptionEvent`. Caught during the initial dry run; resolved by defensively converting `flight_number` to an uppercase string in `eval_adapter.py`.

## Phase 3B: Evaluation Expansion, Invariant Fixes, Real-LLM Grading & Model Comparison

- **AI Coding Tool & Model**: Antigravity with Gemini 3.8 Flash (High).
- **What it was good at**: Expanding the evaluation corpus to 61 fake scenarios across 13 categories plus 12 real-LLM scenarios; diagnosing and resolving the upstream connection feasibility gap in `engine.py` (Rule #8 `UPSTREAM_INFEASIBLE`); implementing continuous soft quality assertions and a live LLM-rubric grader at temperature 0; enforcing strict quota pacing and shared-counter tracking; demonstrating deliberate CI quality gate failure and recovery; and creating GitHub Actions CI workflow `.github/workflows/eval.yml`.
- **One thing it got wrong and how it was caught/fixed**: When the LLM-rubric grader first evaluated customer explanation clarity in live real mode, it scored 0.50 and failed with a hallucination warning because the grader prompt only received the input disruption event without the concierge's decision result (`new_flight`). The grader assumed the rebooked flight (`AI-220`) was fabricated by the explanation text. Caught by inspecting the failing component result in `models_comparison.json`; resolved by passing the full decision context (`disruption`, `action_taken`, `rebooked_flight`, and `hotel_adjustment`) into the grader prompt so it accurately judges factual fidelity.

