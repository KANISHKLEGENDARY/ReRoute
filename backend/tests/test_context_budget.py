"""
Unit Tests for Token Counting and Priority-Ordered Context Budgeter.
"""

import json
import pytest
from app.agent.context_budget import ContextBudgeter, calculate_cost, estimate_token_count


def test_token_estimation_and_cost():
    sample_text = "Flight 6E-204 from DEL to BOM has been cancelled."
    tokens = estimate_token_count(sample_text)
    assert tokens > 0

    cost = calculate_cost(tokens_in=1000, tokens_out=200)
    # (1000 / 1_000_000) * 0.075 + (200 / 1_000_000) * 0.30 = 0.000075 + 0.00006 = 0.000135
    assert cost == pytest.approx(0.000135, abs=1e-6)


def test_configured_pricing_real_call():
    """
    Validates that a real call with 472 tokens in and 56 out computes to ~0.00005
    using configured LLM_PRICE_INPUT_PER_MTOK_USD and LLM_PRICE_OUTPUT_PER_MTOK_USD,
    rather than the old hardcoded 0.0032.
    """
    cost = calculate_cost(tokens_in=472, tokens_out=56)
    assert 0.00005 <= cost <= 0.00006
    assert cost == pytest.approx(0.000052, abs=1e-6)


def test_context_budgeter_preserves_critical_constraints_and_candidates():
    budgeter = ContextBudgeter(max_tokens=300)

    constraints = {"origin": "DEL", "destination": "BOM", "max_fare_delta_inr": 5000.0}
    candidates = [
        {"flight_id": "6E-101", "fare_inr": 4800.0, "departure_time": "2026-10-15T11:00:00"},
        {"flight_id": "AI-202", "fare_inr": 5200.0, "departure_time": "2026-10-15T12:00:00"},
    ]
    original = {"flight_number": "6E-204", "origin": "DEL", "destination": "BOM", "fare_paid_inr": 4500.0}
    
    # Low-priority large chunks that should get truncated
    long_policy_chunks = ["Long legal text paragraph " * 30 for _ in range(5)]
    long_audit_history = [{"poll": i, "status": "ON_TIME", "log": "A" * 100} for i in range(20)]

    payload, est_tokens, was_truncated = budgeter.build_prompt_payload(
        critical_constraints=constraints,
        candidate_flights=candidates,
        original_booking=original,
        retrieved_chunks=long_policy_chunks,
        audit_history=long_audit_history,
    )

    # Assert critical sections are 100% preserved
    assert payload["critical"]["constraints"] == constraints
    assert payload["critical"]["candidates"] == candidates
    assert payload["critical"]["original_booking"]["flight_number"] == "6E-204"

    # Assert low-priority sections were truncated to keep budget
    assert was_truncated is True
    assert est_tokens <= 400
