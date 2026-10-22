# Autonomous Travel-Disruption Concierge — Build Specification
### Document purpose: this is a development handoff spec. It is written so that an AI coding agent (or a human developer) can read it top-to-bottom and build the system without needing clarification on scope, stack, APIs, or flow. Every section is intentionally explicit and self-contained.

---

## 1. Problem Statement

Flight cancellations and missed connections force travelers into manual, stressful rebooking: they must notice the disruption themselves, call or app-hunt for alternatives, separately fix their hotel timing, and get no unified confirmation that everything downstream has been handled. Existing tools either only *display* information (itinerary trackers) or require the traveler to *accept/decline* options manually (most airline and card-issuer rebooking tools) — none currently detect a disruption and autonomously execute the full flight + hotel + notification chain without a human in the loop.

**This project builds an agent that:**
1. Detects a live flight disruption (cancellation or missed connection) the moment it occurs.
2. Autonomously evaluates and selects a replacement flight (and adjusts the linked hotel booking) within a defined policy envelope.
3. Executes that rebooking without waiting for manual approval.
4. Notifies the traveler with a clear explanation of what was done and why, with a visible option to review or override.

**What this project explicitly does NOT attempt to solve** (state this boundary up front, do not silently expand scope later):
- Real monetary transactions / real airline ticket issuance (all booking *execution* is done against sandbox/test endpoints — see Section 6).
- Multi-passenger, group, or multi-city itineraries.
- Visa, baggage-transfer, or ground-transport rearrangement.
- A fully general "any airline, any fare rule" policy engine — implement a representative policy subset (Section 7.3) and document it as such.

---

## 2. Target Users (design for a primary persona, not an undifferentiated crowd)

### Primary target — "The Connecting Traveler" (design the default flow for this persona)
- Someone with a tight, connection-dependent itinerary (a layover, or a meeting/hotel check-in tied to arrival time).
- Wants speed and autonomy: the disruption should be resolved *before* they've finished reading the alert. Default UI/agent behavior = act first, confirm after.

### Secondary constraint — "The Cautious Traveler" (a UI/UX constraint layered onto the same flow, not a separate flow)
- Wants visibility into *why* a decision was made and an easy way to undo/override it.
- Implementation implication: every autonomous action must be paired with a visible, human-readable rationale and a one-tap "Revert" action on the same confirmation screen — do not build a second, separate "manual mode" UI for this persona.

### Do not design a third active end-user persona.
An "internal ops/support agent" view is optional/out of scope for the MVP. If time allows after the core deliverables are complete, a simple read-only admin log view may be added, but it is not a core deliverable.

---

## 3. Tech Stack (fixed — do not substitute without reason)

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** (Python) | Async-first, matches the event-driven nature of disruption handling |
| Agent orchestration | **LangChain** (with a tool-calling/agent-executor pattern) | Structures the "evaluate alternatives → check policy → execute" workflow as tool calls, not free-form text |
| Frontend | **React** (web app, responsive — a PWA, not native mobile) | Faster to build than React Native/Flutter for this scope; still demoable live via browser and web push |
| Auth | **JWT-based email/password auth** (FastAPI + `passlib`/bcrypt for hashing, `python-jose` for tokens) | Lightweight but genuinely functional — real hashed passwords, real signed tokens, no OAuth/social-login complexity needed |
| ORM / DB access | **SQLAlchemy** (or SQLModel, FastAPI-native) | All reads/writes (signup, poll logs, decision traces) are real SQL executed against Postgres via ORM models — not mocked data |
| Database | **PostgreSQL** | Stores user accounts, itinerary, booking, and event-log state |
| Event bus / pub-sub | **Redis** (pub/sub or simple queue) | Decouples the flight-status event source (self-built status generator or scenario trigger) from the agent pipeline |
| Containerization | **Docker** (separate containers for backend API, agent service, and frontend) | Clean architecture story for the presentation; also matches prior experience |
| Deployment target (optional, if deploying) | Render / Railway / a single small AWS EC2 instance | Free-tier friendly; do not over-invest in cloud infra for this project |

**Explicitly not used:** Sabre (closed/expensive access — do not attempt integration), any native mobile framework, any LLM used for the actual booking-execution decision (see Section 7.3 — that logic must be deterministic code, not an LLM call), any social-login/OAuth provider (adds setup overhead with no benefit to this project's goals).

---

## 4. User Onboarding, Registration & Authentication

This phase was previously unspecified and must be built as a real, functioning (if intentionally lightweight) flow — not skipped and not faked. It is also where the email address used for notifications (Section 7.5) actually comes from; it must never be hardcoded.

### 4.1 Why this exists and how deep to build it
This is not a production identity system, so do not over-invest in it (no password-reset-via-email flows, no 2FA, no social login) — but it must be **real**: real signup, real hashed password storage, a real login session, and a real logout. An interviewer should be able to sign up with their own email live and see it work, which is also a good live-demo moment in its own right ("watch — I sign up, and the itinerary and email I just entered are what the agent will use downstream").

### 4.2 Signup flow (`/signup`)
Since there is no real PNR/booking-import integration in this project's scope, signup doubles as "add your itinerary" — but it must capture the **complete booking record**, not just enough to identify a flight. The agent cannot evaluate policy, search alternatives, or execute a rebooking against a real reservation without these fields — treat this form as populating the agent's entire working knowledge of the trip; nothing it needs later can come from anywhere else.

- **Account fields:** full name (as it appears on the ticket — this matters for rebooking/passenger-matching), email (the real notification-recipient address), phone (optional, for SMS if implemented), password.
- **Flight booking fields (required):**
  - Airline / carrier code (e.g., "6E" for IndiGo, "AI" for Air India)
  - Flight number
  - PNR / booking reference (the record locator — this is the actual key the agent would use to identify "which reservation am I modifying")
  - E-ticket number, if the user has one (optional but store if available — some real rebooking flows key off this instead of the PNR)
  - Departure date and scheduled departure time
  - Origin and destination airport (IATA codes, e.g., DEL, BOM)
  - Cabin class booked (Economy/Premium Economy/Business/First)
  - Fare paid (numeric, in the booking's currency) — this is what `evaluate_policy()`'s fare-difference check (Section 7.3) actually compares against; without it, that rule cannot run for real
  - If the itinerary has a connection: repeat the above fields for each additional leg, plus the connection/layover time at the intermediate airport
- **Hotel booking fields (only if demonstrating the hotel-adjustment path):**
  - Hotel name, booking/confirmation reference, check-in date, check-out date, room rate (for any policy comparison on the hotel side), and hotel address or location (needed if you ever calculate proximity/transfer time to a new arrival airport)
- On submit: create the user record (password hashed with bcrypt), create the linked itinerary record with every field above, and automatically add the entered flight number to the real-time watch-list used by the poller (Section 7.1) if it's a real flight, or mark it as a demo-only itinerary if the user enters a placeholder/synthetic flight number for testing.
- Redirect to `/dashboard` on success, already logged in (issue the JWT immediately, no separate login step required right after signup).

**Production-reality note (say this explicitly if asked in an interview, don't gloss over it):** a real production system would not make the user hand-type all of this — it would call an airline/GDS **PNR-retrieval API** (Amadeus has one) with just the airline code + PNR + last name, and pull the full booking record automatically. This project uses manual entry only because no free/sandbox PNR-retrieval flow is reliably available for arbitrary real bookings — document this as a known, deliberate simplification, not something to hide.

### 4.3 Login / Logout (`/login`)
- Standard email + password form → verify against the hashed password → issue a JWT (short-lived access token; a refresh token is optional and not required for this project's scope).
- Store the token client-side (in memory or a secure cookie — do not use `localStorage` if this is ever built as a web artifact/sandboxed environment; a plain deployed React app may use `localStorage` safely).
- Every authenticated page (`/dashboard`, `/itinerary`, `/alerts`, `/confirmation`, `/activity-log`) must check for a valid token and redirect to `/login` if absent/expired.
- A visible **Logout** control must exist in the persistent navigation (Section 9) on every authenticated page — clears the token and redirects to `/login`. Because JWTs are stateless by design, logout is purely a client-side action (delete the stored token) — there is no server-side session to destroy. (A stricter version would maintain a short-lived token-blocklist in Redis, but that's unnecessary complexity for this project's scope.)

### 4.4 Where the registered data is used downstream
- The itinerary entered at signup is what the poller/agent monitors and acts on (Section 7.1 onward) — it is the single source of truth per user, not a separate hardcoded demo itinerary.
- The email entered at signup is the real recipient address used by `send_notification()` (Section 7.5) — this must be read from the user record at send-time, never hardcoded, so that if an interviewer signs up with their own email, they genuinely receive the notification.

### 4.5 Itinerary Data Schema — what the agent has in hand at all times

This is the concrete `itinerary` (and `flight_leg`, `hotel_booking`) table structure implied by Section 4.2. Every field here must exist in Postgres and be readable by the agent's tool functions — this is the single source of truth the agent queries before it does anything; it never infers or guesses a booking detail.

| Table | Key fields |
|---|---|
| `users` | id, name, email, phone, password_hash |
| `itinerary` | id, user_id (FK), created_at |
| `flight_leg` | id, itinerary_id (FK), leg_order (1, 2... for connections), airline_code, flight_number, pnr, eticket_number (nullable), origin, destination, departure_datetime, cabin_class, fare_paid, currency |
| `hotel_booking` | id, itinerary_id (FK), hotel_name, confirmation_reference, checkin_date, checkout_date, room_rate, currency, address (nullable) |
| `poll_log` | id, flight_leg_id (FK), status, checked_at |
| `decision_trace` | id, itinerary_id (FK), stage, input_snapshot, output_snapshot, timestamp |

`search_alternatives()`, `evaluate_policy()`, and `execute_rebooking()` (Section 7.2–7.4) must all read their inputs from these tables via the itinerary's foreign key — never from a hardcoded value, a request parameter the user didn't actually submit, or an assumption. If a field this logic needs isn't in this schema, that's a sign the signup form (Section 4.2) is missing it — add it there first, not as a workaround inside the agent logic.

### 4.6 Data layer — real SQL, not mocked storage
Every write described above and throughout Section 7 is a genuine SQL operation against Postgres, executed via the ORM (Section 3): `INSERT INTO users` on signup, `INSERT INTO poll_log` on every poll (routine or not), `INSERT INTO decision_trace` per pipeline stage. Dashboard and activity-log reads are `SELECT ... ORDER BY created_at DESC` queries. This must be inspectable live — opening `psql`/pgAdmin/DBeaver during a demo and watching rows land as `/simulate` is clicked is a legitimate, recommended demo moment.

### 4.7 Real-time log visibility — two distinct things, do not conflate
- **Product-facing, real-time log:** the `/activity-log` page (Section 9) subscribes over a **WebSocket** (or short-interval polling) to the backend, so new `poll_log`/`decision_trace` rows appear the instant they're written — no manual refresh. This is what a user or interviewer watches live during a demo.
- **Backend/server logs:** ordinary application logs (Python `logging`/`structlog`, written to stdout or a file), viewable via `docker logs <container>` or the terminal. These are for developer debugging only — not shown to end users and not the same thing as the `/activity-log` page.

### 4.8 Metrics — computed on demand, not stored separately
The latency and success-rate numbers in Section 11 are **not** pre-calculated or stored in their own table. They are computed by a `GET /metrics` endpoint that runs aggregate SQL (`AVG()`, `COUNT()` grouped by outcome) directly over the timestamped `decision_trace` rows each time it's called. This keeps the numbers always accurate to the real event history, with no separate value to keep in sync.

---

## 5. High-Level Architecture

```
[Flight-Status Source]  →  [Redis event channel]  →  [Detection Service]
   (self-built status generator                              │
    OR scenario trigger)                                    ▼
                                                    [Agent Orchestrator: LangChain]
                                                     │  tool: search_alternatives()
                                                     │  tool: evaluate_policy()
                                                     │  tool: execute_rebooking()
                                                     │  tool: adjust_hotel()
                                                     │  tool: send_notification()
                                                         ▼
                                              [PostgreSQL: users, itinerary, event log, decision trace]
                                                         ▼
                                              [FastAPI REST/WebSocket API (JWT-protected)]
                                                         ▼
                                              [React frontend — multi-page, see Section 9]
```

Key architectural rule for the agent to follow: **the LangChain agent orchestrates and explains; it does not itself decide fare/policy math in free-text reasoning.** `evaluate_policy()` and `execute_rebooking()` must be plain deterministic Python functions with unit-testable logic. The agent calls them as tools and uses an LLM only to (a) decide which tool to call next in ambiguous cases, and (b) generate the human-readable explanation shown to the user. This separation must be visible in the code structure (separate modules: `/agent/`, `/policy_engine/`, `/booking_execution/`, `/auth/`) — do not blend policy logic into prompt text.

---

## 6. Real vs. Sandboxed — explicit rule for every integration point

This is the most important constraint in this document. Follow it exactly:

| Capability | Real or Sandboxed | Detail |
|---|---|---|
| User accounts / auth | **REAL** | Real password hashing, real sessions — this is genuine, not mocked |
| Flight-status monitoring (detection) | **SANDBOXED (self-built)** *(current phase — see note below)* | No external flight-status API is used for now, to avoid any dependency on a free-tier quota. Implement a self-built status generator: a background process that, for each tracked (fictional or real-numbered) flight, holds a status in Postgres and changes it on a schedule or via the `/simulate-event` trigger — functionally identical to what a real poller would produce, just without an outbound API call. **Revisit this row later if you want genuinely live detection — swap the generator's internals for a real API call (e.g., AviationStack) without changing the function's interface or anything downstream (Redis event, Detection Service, Agent Orchestrator all stay the same).** |
| Alternative flight search | **SANDBOXED (self-built)** *(current phase — see note below)* | Amadeus's free self-service Flight Offers Search API was decommissioned in July 2026, and no comparable free/self-serve real flight-search API is currently available (Kiwi's Tequila API closed to new developers around the same time; Duffel's free tier is explicitly test/sandbox data, not real). Generate candidate alternatives with a self-built function that produces plausible flights around the original (a few time-shifted options, a small fare delta) — deterministic and documented as simulated. **Revisit this row the moment a real free/affordable flight-search API is found or access is obtained — swap the self-built generator for a real API call without changing anything else in the pipeline** (`search_alternatives()`'s interface and downstream consumers stay identical either way). |
| Policy evaluation | **REAL** (it's just code) | Deterministic logic, runs for real on whatever candidates the search step (real or sandboxed) returns. |
| Booking execution (the actual "book this flight" action) | **SANDBOXED (self-built)** | Amadeus's test "Flight Create Orders" endpoint is no longer accessible (self-service portal decommissioned). Implement a local mock function with a realistic confirmation-object response shape — charges nothing, books nothing real. |
| Hotel adjustment | **SANDBOXED (self-built)** | A self-built mock hotel-inventory/adjustment service returning realistic responses (no free hotel API/booking sandbox is reliably available either). |
| Notification | **REAL** | Genuinely send an email to the real address entered at signup (Section 4.4) — this is safe to do for real and makes the demo more convincing. |

Do not, under any circumstance, wire the booking-execution step to a production/paid endpoint. If the AI agent building this is unsure whether an API call is "test mode," it must default to a mocked function and flag that decision in code comments.

**Context note (as of build time):** Amadeus decommissioned its free self-service developer portal on July 17, 2026 — this is why flight search, booking execution, and hotel search are all sandboxed/self-built. Flight-status detection is also kept sandboxed/self-built for now (rather than using a real free-tier API like AviationStack) to remove any dependency on a shared quota or external rate limit while the core pipeline is being built — this is a deliberate, low-risk choice for the current phase, not an oversight. Every sandboxed piece in this table is built behind the same interface a real API call would have, so any of them (detection, search, booking, hotel) can be swapped for a real integration later — including bringing back AviationStack for detection — without changing anything downstream in the pipeline.

---

## 7. Core Logic to Implement

### 7.1 Disruption Detection
- **Status source is fully self-built for now (no external API call):** implement a background scheduler (e.g., `APScheduler` or an `asyncio` loop) that, for each tracked itinerary's flight leg, holds a current status value in Postgres and evaluates/updates it on an interval (e.g., every few minutes) — in the default case this just re-confirms `ON_TIME`, so nothing changes most of the time, exactly like a real poller would behave on an undisrupted flight. This removes any dependency on an external API's rate limit or quota while the core pipeline is being built.
- Every scheduled check, whether or not it finds a change, writes a lightweight log entry (`status: ON_TIME, checked_at: <timestamp>`) — this is what keeps the dashboard/activity feed populated even with no disruption (see Section 9's dashboard content).
- Also support a **manual scenario trigger**: an API endpoint (`POST /simulate-event`) that injects a synthetic status change (`CANCELLED`, `DELAYED`, `MISSED_CONNECTION`) directly onto the same Redis event channel the scheduled status source uses. This must use the exact same downstream pipeline as a scheduled status change — the only difference is what caused the update. This is what guarantees a working live demo on command.
- On any status change to `CANCELLED` or a delay long enough to break a configured connection window, publish a `disruption_detected` event.
- **Keep the interface ready for a real API later:** structure the status source as a single function/module (e.g., `get_flight_status(flight_leg)`) so that, if you later want genuinely live detection, you swap its internals for a real call (to AviationStack or similar) without touching the scheduler, Redis publishing, Detection Service, or anything downstream — the rest of the pipeline doesn't know or care where the status came from.

### 7.2 Alternative Evaluation
- On `disruption_detected`, call the `search_alternatives()` tool for candidates on the same route, same day (± reasonable window). Per Section 6, this is currently a **self-built, sandboxed generator** (produces a few plausible time-shifted flights with a small fare delta around the original), not a live search API — Amadeus's free flight-search tier no longer exists and no comparable free alternative is currently available. Keep the function's interface identical to what a real search call would return, so swapping in a real API later (Section 6's note) requires no changes to anything downstream.
- Return a ranked list of candidate flights to the policy engine — do not auto-pick the "best" one yet; ranking criteria should be visible/inspectable (delay vs. original, price difference, cabin match, direct vs. connecting).

### 7.3 Policy Engine (deterministic, testable, NOT an LLM call)
Implement as plain Python, e.g.:
```
def evaluate_policy(original_booking, candidate_flight) -> PolicyResult:
    # Example representative rules — implement exactly these, document as a subset:
    # 1. Cabin class must match original booking
    # 2. Fare difference must be <= configured threshold (e.g., ₹5,000 / $60)
    # 3. Arrival delay vs. original itinerary must be <= configured threshold (e.g., 3 hours)
    # Returns: APPROVED, REJECTED (with reason), or ESCALATE (no compliant option found)
```
- If no candidate passes policy, the correct behavior is to **escalate** (mark for manual review, notify the user that no autonomous option was found) — do not force a non-compliant booking. This escalate path must exist and be demoable; it proves the guardrail is real, not decorative.

### 7.4 Execution
- If a candidate is `APPROVED`, call the sandboxed booking-execution tool, then the sandboxed/mock hotel-adjustment tool (only if a hotel is linked to this itinerary and the new arrival time affects check-in).
- Write every step (detection → candidates found → policy result → execution result) to a `decision_trace` table in Postgres, linked to the user's itinerary. This trace is what the frontend displays for the "why this option" explanation and what you show in interviews as proof of the reasoning process.

### 7.5 Notification
- On successful execution (or on escalation), send a real notification (email) to the address on the user's account (Section 4.4), summarizing what changed, referencing the decision trace in plain language.

---

## 8. Free APIs and Tools to Integrate

| Purpose | API/Tool | Notes |
|---|---|---|
| Flight status monitoring | **Self-built status generator** (no external API for now) | Removes dependency on any external quota/rate limit while the pipeline is being built — see Section 6/7.1. A real API (e.g., AviationStack, free tier) can be swapped in later behind the same function interface if genuinely live detection is wanted. |
| Alternative flight search | **Self-built sandboxed generator** (no external API currently) | Amadeus's free Flight Offers Search API was decommissioned July 2026; no comparable free/self-serve real search API is currently available (Kiwi Tequila closed to new developers; Duffel's free tier is explicitly sandbox/test data). Build a small function producing plausible candidate flights instead — see Section 6 and 7.2. Revisit this row if a usable free API is found later. |
| Booking execution (sandboxed) | **Self-built mock function** | Amadeus's sandbox "Flight Create Orders" test endpoint is no longer accessible. A local function returning a realistic confirmation-object shape covers this step's requirements. |
| Hotel data/adjustment (sandboxed) | **Self-built mock "adjust booking" function** | No free hotel booking-execution sandbox is reliably available — mock this step explicitly and say so in documentation. |
| Email notification | **SendGrid free tier** or **Gmail SMTP via an app password** | Either is free and genuinely sends real email |
| SMS notification (optional) | **Twilio free trial credit** | Optional — email alone satisfies the "notification" requirement; add SMS only if time allows |
| Agent framework | **LangChain** (open source, no cost) | — |
| Auth | **passlib[bcrypt]**, **python-jose** (Python libraries, free/open source) | Password hashing and JWT signing |
| Maps/route context (optional, only if used for connection-time calculations) | **OpenStreetMap / Nominatim** (free) | Only needed if calculating ground-transfer time between terminals/hotels |

No external API signup is required to build the core pipeline in this phase — detection, search, booking, and hotel adjustment are all self-built/sandboxed, with email being the only genuinely external, real integration needed (Gmail SMTP requires no new account if you already have Gmail; just generate an app password).

---

## 9. Frontend — Design Direction and Page Structure

**Design direction — explicit constraints:**
- Do **not** use a glassmorphic or dark-themed aesthetic.
- Follow professional, enterprise SaaS UI conventions: clean typography hierarchy, a neutral light background, a defined color system used consistently (a primary brand color for actions/CTAs, a distinct alert color reserved only for disruption states, a success color reserved only for confirmations), generous whitespace, and a persistent navigation structure (sidebar or top nav, including the Logout control from Section 4.3) — the kind of visual language used in real fintech/travel-ops dashboards, not a marketing landing page.
- Use real typographic and spacing hierarchy (consistent heading scale, consistent spacing units) rather than one-off styling per component.

**Page structure — build as genuinely separate pages/routes, not one scrolling single-page app:**

1. **`/signup`** — Account + itinerary creation, per Section 4.2.
2. **`/login`** — Per Section 4.3.
3. **`/dashboard`** — Overview page (see "Dashboard content" below — must never be empty).
4. **`/itinerary`** — Full itinerary detail page. Flight legs, hotel booking, connection windows — the "before" state, viewable at any time independent of any disruption.
5. **`/alerts`** — Disruption alert page. Triggered/linked to when a disruption is detected. Shows: what was disrupted, the rebooking option the agent selected, and the plain-language rationale (pulled from the decision trace).
6. **`/confirmation`** — Post-action confirmation page. Shows the new itinerary clearly diffed against the old one (what changed and why), the "Revert" action, and confirmation that hotel + notification steps completed.
7. **`/activity-log`** — The full decision-trace and poll-history log: every check (even routine "ON_TIME" polls), every detection, every policy evaluation, every execution and notification. This page is what makes the "AI reasoning" visible and is the page to have open when explaining the system to an interviewer.
8. **`/simulate`** (dev/demo-only page, clearly labeled as such in the UI, e.g. with a small "Demo Tools" badge) — The manual scenario-trigger controls described in Section 7.1 (buttons: "Simulate Cancellation," "Simulate Missed Connection," "Simulate No-Compliant-Option"). This page should look distinct from the "real" traveler-facing pages (e.g., a clearly separate admin-style layout) so it doesn't read as part of the actual product UX.

Each page above is a separate route/component — do not collapse them into modal overlays or accordions on a single screen.

### Dashboard content (`/dashboard`) — must be populated at all times, never a blank/empty state

Answering directly: the dashboard should never look empty, because the system is genuinely doing something (polling) on a schedule whether or not a disruption exists. Build these widgets:

- **Itinerary summary card** — the user's registered flight (route, date, current status badge pulled live from the most recent real poll — e.g., a green "ON TIME" badge under normal conditions) and linked hotel, if any.
- **Live monitoring status widget** — "Agent monitoring since [signup time]," last-checked timestamp, and a visible countdown/indicator to the next scheduled poll. This is what proves to a viewer that a real background process is alive, not just a static page.
- **Connection buffer countdown** — if the itinerary has a connection, show time remaining until the connection window, updating live.
- **Recent activity preview** — the last 3–5 entries pulled from the activity log (Section 9, page 7), which will show routine "Checked flight status — ON_TIME" entries even with zero disruptions — this alone guarantees the dashboard always has real, fresh content to show.
- **Quick links** — to `/activity-log` (full history) and `/simulate` (labeled "Demo Tools," visually separated from the rest of the dashboard, e.g. in its own card with distinct styling).
- **Optional nice-to-have:** a destination-weather widget (free API, e.g. OpenWeather) — adds a legitimately useful, non-fabricated piece of live data to the dashboard with minimal effort, and reinforces that the page reflects real, current conditions.

### First-landing states (exact sequence right after signup — do not fake data here)

- **T+0 (immediately on landing, before the first poll runs):** itinerary card shows entered flight/hotel details with a neutral status badge like **"Monitoring starting..."**; monitoring widget shows "Agent monitoring since [now]," "Last checked: —," and a countdown to the first poll; connection countdown (if applicable) is already populated since it's calculated from entered dates, not polling; activity feed shows an honest empty state — *"No activity yet — your first status check will appear here shortly"* — never a fabricated placeholder row; weather widget (if built) populates immediately since it's independent of the flight poller.
- **T+~few minutes (after the first scheduled status check completes):** status badge updates from "Monitoring starting..." to a confirmed state (e.g., green "ON TIME") from the self-built status source's first check; "Last checked" updates to a real timestamp; the activity feed's empty state is replaced by the first genuine log row.
- **Metrics view (`/activity-log`) before any disruption has ever run:** show "No disruption events recorded yet" rather than a zero/blank chart — same honesty principle, since Section 11's aggregates are only meaningful after at least one full run.

---

## 10. Disruption Simulation Flow (the exact flow to implement for `/simulate`)

This is the flow the AI agent building this must implement precisely, since it is both the test harness and the guaranteed-to-work live demo path:

1. User (or interviewer, live) clicks a scenario button on `/simulate`, e.g. "Simulate Cancellation" for their registered flight.
2. Frontend calls `POST /simulate-event` with a payload: `{ flight_id, event_type: "CANCELLED" }`.
3. Backend publishes this event onto the same Redis channel used by the scheduled status generator — from this point forward, the synthetic event is indistinguishable from a scheduled one to the rest of the system.
4. Detection Service consumes the event, confirms it represents a disruption (cancellation or a delay breaking the connection window), and publishes `disruption_detected`.
5. Agent Orchestrator consumes `disruption_detected`, calls `search_alternatives()` — currently the self-built sandboxed generator (Section 6/7.2), not a live search API — for that route/date.
6. Candidates returned → `evaluate_policy()` runs deterministically on each → best compliant candidate selected (or escalation triggered if none qualify).
7. If approved: `execute_rebooking()` calls the sandboxed booking-execution endpoint/mock → on success, `adjust_hotel()` runs if a linked hotel exists and timing changed.
8. Every step's input/output is written to the `decision_trace` table with a timestamp, so latency between step 4 and step 7 can be measured and displayed (this is your Task 5 "detection speed" metric).
9. `send_notification()` fires a real email (to the address from Section 4.4) summarizing the change in plain language, generated from the decision trace.
10. Frontend, listening via WebSocket (or polling `/decision-trace/{itinerary_id}`), updates `/alerts` and then `/confirmation` live as each step completes — the interviewer should watch the UI update in real time as the pipeline runs, not just see a final static result.
11. If escalation occurred instead (no compliant candidate), the flow ends at step 6 with a clearly different UI state on `/alerts` ("No autonomous option met policy — flagged for review") rather than silently failing.

This same flow, with a real API swapped in behind Section 7.1's status-source interface later, becomes the genuinely-live version — the AI agent building this should implement the pipeline once, with two interchangeable event sources (Section 7.1), not two separate pipelines.

---

## 11. Metrics to Capture (for Task 5 — test and optimize)

Instrument and store, per simulated/real run:
- **Detection latency**: time from event publish to `disruption_detected`.
- **Decision latency**: time from `disruption_detected` to policy result.
- **End-to-end latency**: time from event publish to notification sent.
- **Rebooking success rate**: % of runs resulting in `APPROVED` execution vs. `ESCALATED`.
- **Notification clarity**: not fully automatable — track this qualitatively (a short rubric: does the message state what changed, why, and what action if any is needed) and note it as a manually-scored metric in documentation.

Expose these on a small metrics view (can be part of `/activity-log`) so numbers are ready to quote in a presentation or interview.

---

## 12. Build Order (for the agent/developer to follow sequentially)

1. Postgres schema (users, itinerary, booking, decision_trace tables) + FastAPI skeleton + Redis wired up, with a fake event flowing end-to-end doing nothing but logging.
2. Auth (Section 4): signup, login, JWT middleware protecting all itinerary/agent endpoints.
3. Self-built flight-status generator implemented per Section 7.1 (scheduled background process, no external API), publishing onto the same Redis channel the scenario trigger uses.
4. `/simulate-event` endpoint implemented, proven to trigger the same downstream path as the scheduled status generator.
5. Policy engine (Section 7.3) written and unit-tested independently of the agent framework.
6. LangChain agent orchestrator wired to call `search_alternatives`, `evaluate_policy`, `execute_rebooking`, `adjust_hotel`, `send_notification` as tools.
7. Decision-trace logging added at every step, including routine polls (needed for Section 9's dashboard activity feed).
8. Notification integration (email) wired for real, pulling the recipient address from the user's account.
9. Frontend pages built in this order: `/signup` and `/login` (needed to test everything downstream) → `/simulate` (dev tool) → `/dashboard` and `/itinerary` (static-ish views, but dashboard needs the activity feed from step 7) → `/alerts` and `/confirmation` (live-updating views) → `/activity-log`.
10. Metrics capture and display.
11. Run and record 10–20 scenario passes across both outcome types (approved, escalated) via `/simulate-event` for the numbers in Section 11.

Do not build the frontend before the backend pipeline in Section 7 is functional end-to-end via API calls/Postman — the UI should be the last thing wired to already-working logic, not built in parallel against a moving backend.
