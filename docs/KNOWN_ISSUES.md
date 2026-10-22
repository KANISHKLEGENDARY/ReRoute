# Known Issues and Invariant Gaps

This document tracks known architectural and domain model gaps deferred to subsequent phases.

## 1. Sequential Multi-Leg Connection Invariant (RESOLVED in Phase 3B)

- **Issue**: The original policy engine (`app/policy/engine.py`) validated that an alternative replacement flight did not break downstream (*subsequent*) legs in an itinerary. However, it did not verify that a replacement leg departs after the *preceding* (upstream) leg has arrived plus the minimum connection time (MCT).
- **Reproduction**: Evaluated in baseline scenarios `multi_leg_02` and `multi_leg_03` where rebooking for connecting leg 2 attempted to select early morning flights departing prior to leg 1 arrival.
- **Resolution**: Resolved in Phase 3B. Added Rule #8 (`UPSTREAM_INFEASIBLE`) in `app/policy/engine.py`, populated `upstream_legs` / `upstream_arrival_time` in `TripConstraints`, and enforced with the zero-tolerance `connection_feasible_upstream` invariant assertion. All 6 sequential and multi-leg evaluation scenarios now pass with 100% compliance.

