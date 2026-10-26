"""
Unit tests for LLM Safety, Hard Quota Limits, Rate Pacing, and Shared Counter.

Verifies:
1. Cap reached means zero API calls (mocked client) and fallback with reason `budget`.
2. Pacific day rollover (midnight America/Los_Angeles) resets the daily counter.
3. Retries are counted in the persistent counter (initial + each retry).
4. Per-event cap MAX_LLM_CALLS_PER_EVENT works and triggers deterministic fallback.
5. Pacing uses the model's rpm: (60 / rpm) * 1.2 seconds, concurrency 1.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agent.llm_safety import (
    check_call_safety,
    record_call_attempt,
    get_model_call_count,
    get_model_limits,
    get_pacific_date,
    _read_usage_data,
    _write_usage_data,
    get_usage_file_path,
    DEFAULT_MODEL_LIMITS,
)
from app.agent.llm import (
    GeminiLLMClient,
    AsyncRateLimiter,
    LLMSelectionOutput,
)
from app.schemas.pipeline import (
    CandidateFlight,
    OriginalBooking,
    TripConstraints,
    CabinClass,
    DisruptionEvent,
    DisruptionType,
)
from app.agent.orchestrator import ConciergeState, node_choose_alternative, PipelineDeps, InMemoryTraceSink


@pytest.fixture
def isolated_usage_file(tmp_path, monkeypatch):
    """Isolates the LLM usage file to a temporary file for unit testing."""
    test_file = tmp_path / ".test_llm_usage"
    test_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LLM_USAGE_FILE", str(test_file))
    return test_file


# --- 1. Cap Reached Means Zero API Calls (Mocked Client) ---
@pytest.mark.asyncio
async def test_cap_reached_zero_api_calls_and_fallback(isolated_usage_file, monkeypatch):
    """
    When a model hits its 80% daily limit (e.g. 16 for a 20-rpd model),
    choose_alternative makes ZERO API calls and falls back with reason 'budget'.
    """
    model = "gemini-3.6-flash"  # rpd = 20, 80% cap = 16
    today = get_pacific_date()

    # Pre-populate the counter to 16 (at cap)
    data = {model: {today: 16}}
    _write_usage_data(isolated_usage_file, data)

    client = GeminiLLMClient(
        api_key="mock-api-key",
        model=model,
    )

    mock_chat = MagicMock()
    mock_invoke = AsyncMock()
    mock_chat.with_structured_output.return_value.ainvoke = mock_invoke

    with patch("langchain_google_genai.ChatGoogleGenerativeAI", return_value=mock_chat):
        res = await client.choose_alternative(
            prompt_payload={"candidate_flights": [{"flight_id": "CAND-1"}]},
            candidate_ids=["CAND-1"],
        )

    # ZERO API calls made!
    assert mock_invoke.call_count == 0
    assert res["llm_fallback"] is True
    assert res["llm_fallback_reason"] == "budget"
    assert res["selected_flight_id"] == "CAND-1"


# --- 2. Pacific Day Rollover Resets the Counter ---
def test_pacific_day_rollover_resets_counter(isolated_usage_file):
    """
    Verifies Pacific Time (America/Los_Angeles) midnight rollover logic.
    A day at quota cap resets cleanly on the next calendar day in Pacific Time.
    """
    model = "gemini-3.6-flash"

    # Pacific day 1: 2026-10-13 (hit cap of 16)
    day1 = "2026-10-13"
    day2 = "2026-10-14"

    data = {model: {day1: 16, day2: 0}}
    _write_usage_data(isolated_usage_file, data)

    # Day 1 is capped
    allowed_d1, reason_d1 = check_call_safety(model, day1)
    assert allowed_d1 is False
    assert reason_d1 == "budget"

    # Day 2 has 0 calls -> permitted!
    assert get_model_call_count(model, day2) == 0
    allowed_d2, _ = check_call_safety(model, day2)
    assert allowed_d2 is True

    # Test exact midnight Pacific boundary using UTC times
    # 2026-10-14 06:59:59 UTC == 2026-10-13 23:59:59 PDT (before midnight Pacific)
    before_midnight = datetime(2026, 10, 14, 6, 59, 59, tzinfo=timezone.utc)
    assert get_pacific_date(before_midnight) == "2026-10-13"

    # 2026-10-14 07:00:01 UTC == 2026-10-14 00:00:01 PDT (after midnight Pacific)
    after_midnight = datetime(2026, 10, 14, 7, 0, 1, tzinfo=timezone.utc)
    assert get_pacific_date(after_midnight) == "2026-10-14"


# --- 3. Retries Are Counted in the Shared Counter ---
@pytest.mark.asyncio
async def test_retries_are_counted_in_shared_counter(isolated_usage_file):
    """
    Every attempt (initial call + retries) must increment the persistent counter.
    """
    model = "gemini-3.5-flash-lite"
    today = get_pacific_date()

    client = GeminiLLMClient(
        api_key="mock-api-key",
        model=model,
    )
    # Speed up backoff delay in tests
    client.rate_limiter.min_interval_seconds = 0.0

    call_count = 0

    async def flaky_api_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Simulate 429 Rate Limit error
            raise RuntimeError("429 ResourceExhausted: rate limit exceeded")
        return LLMSelectionOutput(
            selected_flight_id="6E-100",
            rationale="Success on retry",
        )

    # Initial count is 0
    assert get_model_call_count(model, today) == 0

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await client._execute_with_retry_and_rate_limit(flaky_api_call)

    assert result.selected_flight_id == "6E-100"
    assert call_count == 3

    # All 3 attempts were counted in the persistent counter!
    assert get_model_call_count(model, today) == 3


@pytest.mark.asyncio
async def test_retries_exhausted_fallback_reason_rate_limit(isolated_usage_file):
    """
    When all retries fail with 429, choose_alternative falls back with reason 'rate_limit'.
    """
    model = "gemini-3.5-flash-lite"
    client = GeminiLLMClient(
        api_key="mock-api-key",
        model=model,
    )
    client.rate_limiter.min_interval_seconds = 0.0

    async def persistent_429():
        raise RuntimeError("429 ResourceExhausted quota exceeded")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with patch.object(client, "_execute_with_retry_and_rate_limit", side_effect=RuntimeError("RATE_LIMIT: gemini-3.5-flash-lite")):
            res = await client.choose_alternative(
                prompt_payload={},
                candidate_ids=["CAND-1"],
            )

    assert res["llm_fallback"] is True
    assert res["llm_fallback_reason"] == "rate_limit"


# --- 4. Per-Event Cap MAX_LLM_CALLS_PER_EVENT Works ---
@pytest.mark.asyncio
async def test_per_event_cap_works():
    """
    When event_llm_calls reaches MAX_LLM_CALLS_PER_EVENT (6),
    the agent loop halts LLM calls and falls back deterministically with reason 'budget'.
    """
    booking = OriginalBooking(
        user_id=1,
        user_email="test@traveler.com",
        user_name="Test Traveler",
        itinerary_id=1,
        flight_leg_id=1,
        airline_code="6E",
        flight_number="6E-204",
        pnr="PNR-123",
        origin="DEL",
        destination="BOM",
        departure_time=datetime(2026, 10, 20, 10, 0),
        arrival_time=datetime(2026, 10, 20, 12, 10),
        cabin_class=CabinClass.ECONOMY,
        fare_paid_inr=5000.0,
    )

    candidate = CandidateFlight(
        flight_id="6E-CAND-DEL-BOM",
        airline_code="6E",
        airline_name="IndiGo",
        flight_number="6E-205",
        origin="DEL",
        destination="BOM",
        departure_time=datetime(2026, 10, 20, 11, 0),
        arrival_time=datetime(2026, 10, 20, 13, 10),
        cabin_class=CabinClass.ECONOMY,
        fare_inr=5200.0,
        fare_delta_inr=200.0,
        seats_available=5,
    )

    mock_llm = MagicMock()
    mock_llm.choose_alternative = AsyncMock()

    deps = PipelineDeps(llm=mock_llm, trace_sink=InMemoryTraceSink())

    # State already at cap (event_llm_calls = 6)
    state: ConciergeState = {
        "event": DisruptionEvent(event_id="EVT-CAP-TEST", event_type=DisruptionType.CANCELLED, flight_id=1, flight_number="6E-204"),
        "booking": booking,
        "constraints": TripConstraints(
            required_origin="DEL",
            required_destination="BOM",
            earliest_departure_time=datetime(2026, 10, 20, 10, 0),
            original_arrival_time=datetime(2026, 10, 20, 12, 10),
        ),
        "deps": deps,
        "approved_candidates": [candidate],
        "candidates": [candidate],
        "event_llm_calls": 6,
    }

    result = await node_choose_alternative(state)

    # Zero LLM calls made!
    assert mock_llm.choose_alternative.call_count == 0
    assert result["llm_fallback"] is True
    assert result["llm_fallback_reason"] == "budget"
    assert result["selected_candidate"].flight_id == candidate.flight_id


# --- 5. Pacing Uses the Model's RPM ---
def test_pacing_uses_model_rpm():
    """
    Verifies that pacing is calculated per model:
    wait at least (60 / rpm) * 1.2 seconds, concurrency 1.
    - gemini-3.5-flash-lite (15 rpm) -> 4.8s
    - gemini-3.1-flash-lite (15 rpm) -> 4.8s
    - gemini-3.6-flash (5 rpm) -> 14.4s
    - gemini-3.7-flash (5 rpm) -> 14.4s
    - gemini-3.8-flash (5 rpm) -> 14.4s
    - gemini-3-flash (5 rpm) -> 14.4s
    - Unknown model (5 rpm) -> 14.4s
    """
    # 15 RPM models: (60 / 15) * 1.2 = 4.8s
    lite_35 = get_model_limits("gemini-3.5-flash-lite")
    assert lite_35["rpm"] == 15
    assert lite_35["rpd"] == 500
    assert lite_35["stop_threshold"] == 400
    assert lite_35["warn_threshold"] == 300
    assert round(lite_35["pacing_interval_sec"], 2) == 4.80

    lite_31 = get_model_limits("gemini-3.1-flash-lite")
    assert lite_31["rpm"] == 15
    assert round(lite_31["pacing_interval_sec"], 2) == 4.80

    # 5 RPM models: (60 / 5) * 1.2 = 14.4s
    for m in ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-3-flash"]:
        lim = get_model_limits(m)
        assert lim["rpm"] == 5
        assert lim["rpd"] == 20
        assert lim["stop_threshold"] == 16
        assert lim["warn_threshold"] == 12
        assert round(lim["pacing_interval_sec"], 2) == 14.40

    # Unknown model default: 5 rpm and 20 rpd
    unknown = get_model_limits("gemini-custom-future-99")
    assert unknown["rpm"] == 5
    assert unknown["rpd"] == 20
    assert unknown["stop_threshold"] == 16
    assert round(unknown["pacing_interval_sec"], 2) == 14.40

    # AsyncRateLimiter paces according to model rpm
    limiter_lite = AsyncRateLimiter(model="gemini-3.5-flash-lite")
    assert round(limiter_lite.min_interval_seconds, 2) == 4.80

    limiter_5rpm = AsyncRateLimiter(model="gemini-3.6-flash")
    assert round(limiter_5rpm.min_interval_seconds, 2) == 14.40


@pytest.mark.asyncio
async def test_db_usage_store_caps_calls(monkeypatch):
    """
    When LLM_USAGE_STORE=db, call counts are tracked in database table llm_usage
    and the 80% daily stop threshold still stops real calls.
    """
    from app.core.database import init_db
    await init_db()

    monkeypatch.setenv("LLM_USAGE_STORE", "db")
    model = "gemini-3.6-flash"  # rpd = 20, 80% cap = 16
    today = get_pacific_date()

    # Initial count should be 0
    assert get_model_call_count(model, today) == 0

    # Record 15 attempts -> under cap
    for _ in range(15):
        record_call_attempt(model, today)
    assert get_model_call_count(model, today) == 15
    allowed, _ = check_call_safety(model, today)
    assert allowed is True

    # 16th attempt hits 80% threshold (16 / 20)
    record_call_attempt(model, today)
    assert get_model_call_count(model, today) == 16
    allowed, reason = check_call_safety(model, today)
    assert allowed is False
    assert reason == "budget"
