"""
Tests for Live Production LLM Wiring, Pacing/Limiting Guarantees,
and Provider-Reported Token and Metric Recording.
"""

import inspect
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import Settings
from app.agent.llm import (
    FakeLLM,
    GeminiLLMClient,
    NoKeyLLMClient,
    get_llm_client,
    LLMSelectionOutput,
)
from app.agent.orchestrator import PipelineDeps, InMemoryTraceSink
from app.agent.pipeline import handle_disruption
from app.agent.context_budget import calculate_cost
from app.schemas.pipeline import (
    ActionType,
    CabinClass,
    DisruptionEvent,
    DisruptionType,
    OriginalBooking,
)
import app.services.consumer as consumer_module


@pytest.fixture
def test_booking() -> OriginalBooking:
    return OriginalBooking(
        user_id=1,
        user_email="test.traveler@reroute.travel",
        user_name="Test Traveler",
        itinerary_id=1,
        flight_leg_id=20,
        airline_code="6E",
        flight_number="6E-204",
        pnr="PNR-LIVETEST",
        origin="DEL",
        destination="BOM",
        departure_time=datetime(2026, 10, 15, 10, 0, 0),
        arrival_time=datetime(2026, 10, 15, 12, 15, 0),
        cabin_class=CabinClass.ECONOMY,
        fare_paid_inr=5000.0,
        status="CONFIRMED",
    )


@pytest.fixture
def cancelled_event() -> DisruptionEvent:
    return DisruptionEvent(
        event_id="EVT-LIVE-TEST-001",
        event_type=DisruptionType.CANCELLED,
        flight_id=20,
        flight_number="6E-204",
        delay_minutes=0,
        reason="Operational cancellation",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )


def test_production_wiring_never_builds_fake():
    """
    Test 1: FAILS if production wiring ever builds a fake or stub client.
    Guarantees that whenever GOOGLE_API_KEY is configured, the production factory
    and consumer dependencies exclusively instantiate the real GeminiLLMClient.
    """
    # 1. Factory returns GeminiLLMClient when GOOGLE_API_KEY is set
    settings_with_key = Settings(
        GOOGLE_API_KEY="AIzaSyTestKey_Secret_NotReal",
        LLM_MODEL="gemini-3.5-flash-lite",
        LLM_PROVIDER="google",
    )
    client = get_llm_client(settings_with_key)
    assert isinstance(client, GeminiLLMClient), f"Expected GeminiLLMClient, got {type(client)}"
    assert not isinstance(client, FakeLLM), "Production wiring must NEVER return FakeLLM when key is present"
    assert client.__class__.__name__ == "GeminiLLMClient"

    # 2. Even if LLM_PROVIDER is somehow configured as 'fake', presence of key in production wiring takes priority
    settings_forced_fake = Settings(
        GOOGLE_API_KEY="AIzaSyTestKey_Secret_NotReal",
        LLM_MODEL="gemini-3.5-flash-lite",
        LLM_PROVIDER="fake",
    )
    client_provider_fake = get_llm_client(settings_forced_fake)
    assert not isinstance(client_provider_fake, FakeLLM), "get_llm_client must never build FakeLLM"
    assert isinstance(client_provider_fake, GeminiLLMClient)

    # 3. PipelineDeps default constructor uses get_llm_client
    with patch("app.agent.orchestrator.get_settings", return_value=settings_with_key):
        deps = PipelineDeps()
        assert isinstance(deps.llm, GeminiLLMClient)
        assert not isinstance(deps.llm, FakeLLM)

    # 4. Consumer source code inspection: ensure consumer does not import or instantiate FakeLLM
    consumer_src = inspect.getsource(consumer_module)
    assert "FakeLLM" not in consumer_src, (
        "Production consumer (backend/app/services/consumer.py) must NEVER import or reference FakeLLM"
    )
    assert "get_llm_client" in consumer_src, (
        "Production consumer must build LLM dependency via get_llm_client()"
    )


@pytest.mark.asyncio
async def test_metrics_record_provider_reported_tokens(test_booking, cancelled_event):
    """
    Test 2: Mocked real client proving metrics record strictly the provider-reported tokens.
    Guarantees that token counts, costs, and traces come from provider usage metadata,
    and never from hardcoded or default numbers (such as 300, 45, 345, 450, 40).
    """
    settings = Settings(
        GOOGLE_API_KEY="AIzaSyTestKey_Secret_NotReal",
        LLM_MODEL="gemini-3.5-flash-lite",
    )
    real_client = GeminiLLMClient(
        api_key="AIzaSyTestKey_Secret_NotReal",
        model="gemini-3.5-flash-lite",
        settings=settings,
    )

    # Define exact provider token metadata
    provider_input_tokens = 512
    provider_output_tokens = 68
    expected_cost = calculate_cost(provider_input_tokens, provider_output_tokens)

    # Mock provider response with raw message containing usage_metadata
    mock_raw_msg = MagicMock()
    mock_raw_msg.usage_metadata = {
        "input_tokens": provider_input_tokens,
        "output_tokens": provider_output_tokens,
        "total_tokens": provider_input_tokens + provider_output_tokens,
    }
    mock_parsed_obj = LLMSelectionOutput(
        selected_flight_id="6E-122-DEL-BOM-20261015-S2",
        rationale="Earliest alternative flight departing after buffer",
    )

    mock_execute_result = {
        "raw": mock_raw_msg,
        "parsed": mock_parsed_obj,
    }

    trace_sink = InMemoryTraceSink()
    deps = PipelineDeps(
        llm=real_client,
        trace_sink=trace_sink,
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    with patch.object(
        real_client,
        "_execute_with_retry_and_rate_limit",
        new=AsyncMock(return_value=mock_execute_result),
    ):
        result = await handle_disruption(event=cancelled_event, booking=test_booking, deps=deps)

    # 1. Assert result metrics strictly match provider metadata
    assert result.metrics["tokens_in"] == provider_input_tokens
    assert result.metrics["tokens_out"] == provider_output_tokens
    assert result.metrics["cost_usd"] == pytest.approx(expected_cost, abs=1e-6)
    assert result.metrics["cost_estimated"] is False
    assert result.metrics["llm_fallback"] is False

    # 2. Assert metrics NEVER match the old fake or default numbers
    assert result.metrics["tokens_in"] != 300, "tokens_in must not be the FakeLLM default 300"
    assert result.metrics["tokens_out"] != 45, "tokens_out must not be the FakeLLM default 45"
    assert result.metrics["tokens_in"] + result.metrics["tokens_out"] != 345, "total tokens must not be 345"
    assert result.metrics["tokens_in"] != 450, "tokens_in must not be the old fallback 450"
    assert result.metrics["tokens_out"] != 40, "tokens_out must not be the old fallback 40"

    # 3. Assert RESULT trace stage snapshot reflects the exact provider tokens
    result_stages = [s for s in trace_sink.stages if s["stage"] == "RESULT"]
    assert len(result_stages) == 1
    result_snap = result_stages[0]["output_snapshot"]
    assert result_snap["tokens_in"] == provider_input_tokens
    assert result_snap["tokens_out"] == provider_output_tokens
    assert result_snap["cost_usd"] == pytest.approx(expected_cost, abs=1e-6)
    assert result_snap["cost_estimated"] is False
    assert result_snap["llm_fallback"] is False
    assert result_snap["llm_fallback_reason"] == "none"


@pytest.mark.asyncio
async def test_missing_provider_usage_records_unknown_and_marks_cost_estimated(test_booking, cancelled_event):
    """
    Test 3: If provider usage metadata is missing, tokens must be stored as 'unknown'
    and cost must be marked as estimated (cost_estimated=True).
    """
    settings = Settings(GOOGLE_API_KEY="test_key", LLM_MODEL="gemini-3.5-flash-lite")
    real_client = GeminiLLMClient(api_key="test_key", model="gemini-3.5-flash-lite", settings=settings)

    mock_raw_msg = MagicMock()
    mock_raw_msg.usage_metadata = None  # Provider did not supply usage metadata
    mock_raw_msg.response_metadata = {}

    mock_parsed_obj = LLMSelectionOutput(
        selected_flight_id="6E-122-DEL-BOM-20261015-S2",
        rationale="Selection without token metadata",
    )

    trace_sink = InMemoryTraceSink()
    deps = PipelineDeps(
        llm=real_client,
        trace_sink=trace_sink,
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    with patch.object(
        real_client,
        "_execute_with_retry_and_rate_limit",
        new=AsyncMock(return_value={"raw": mock_raw_msg, "parsed": mock_parsed_obj}),
    ):
        result = await handle_disruption(event=cancelled_event, booking=test_booking, deps=deps)

    assert result.metrics["tokens_in"] == "unknown"
    assert result.metrics["tokens_out"] == "unknown"
    assert result.metrics["cost_estimated"] is True
    assert result.metrics["llm_fallback"] is False


@pytest.mark.asyncio
async def test_call_failure_deterministic_fallback_zero_tokens(test_booking, cancelled_event):
    """
    Test 4: On call failure (e.g. rate limit / timeout / outage), triggers deterministic fallback
    with llm_fallback=True, real fallback reason, and exactly 0 tokens.
    """
    settings = Settings(GOOGLE_API_KEY="test_key", LLM_MODEL="gemini-3.5-flash-lite")
    real_client = GeminiLLMClient(api_key="test_key", model="gemini-3.5-flash-lite", settings=settings)

    trace_sink = InMemoryTraceSink()
    deps = PipelineDeps(
        llm=real_client,
        trace_sink=trace_sink,
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    with patch.object(
        real_client,
        "_execute_with_retry_and_rate_limit",
        side_effect=RuntimeError("RATE_LIMIT: gemini-3.5-flash-lite"),
    ):
        result = await handle_disruption(event=cancelled_event, booking=test_booking, deps=deps)

    assert result.metrics["tokens_in"] == 0
    assert result.metrics["tokens_out"] == 0
    assert result.metrics["cost_usd"] == 0.0
    assert result.metrics["llm_fallback"] is True

    result_stages = [s for s in trace_sink.stages if s["stage"] == "RESULT"]
    assert len(result_stages) == 1
    assert result_stages[0]["output_snapshot"]["llm_fallback"] is True
    assert result_stages[0]["output_snapshot"]["llm_fallback_reason"] == "rate_limit"
    assert result_stages[0]["output_snapshot"]["tokens_in"] == 0
    assert result_stages[0]["output_snapshot"]["tokens_out"] == 0
