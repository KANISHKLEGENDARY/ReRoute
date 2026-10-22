"""
Token Counting and Priority-Ordered Context Budgeter.

Enforces context limits per LLM call.
Priority order for truncation:
1. NEVER TRUNCATE (Critical): Trip Constraints, Candidates List, Original Booking core fields.
2. MEDIUM (Summarize/Compress): Hotel booking, Disruption event details.
3. LOW (Truncate First): Secondary itinerary legs, policy chunk text, raw audit logs.
"""

from typing import Any, Dict, List, Optional, Tuple
import json


def estimate_token_count(text: str) -> int:
    """
    Estimates token count for a string using a ~4 chars/token heuristic.
    Deterministic, fast, and does not require external network requests.
    """
    if not text:
        return 0
    # Approx 3.8 to 4 chars per token for English + JSON
    return max(1, len(text) // 4 + (1 if len(text) % 4 > 0 else 0))


def calculate_cost(
    tokens_in: int,
    tokens_out: int,
    price_in_per_mtok: Optional[float] = None,
    price_out_per_mtok: Optional[float] = None,
) -> float:
    """Calculates USD cost for token usage using configured per-million token prices."""
    if price_in_per_mtok is None or price_out_per_mtok is None:
        from app.core.config import get_settings
        settings = get_settings()
        if price_in_per_mtok is None:
            price_in_per_mtok = settings.LLM_PRICE_INPUT_PER_MTOK_USD
        if price_out_per_mtok is None:
            price_out_per_mtok = settings.LLM_PRICE_OUTPUT_PER_MTOK_USD

    in_cost = (tokens_in / 1_000_000.0) * price_in_per_mtok
    out_cost = (tokens_out / 1_000_000.0) * price_out_per_mtok
    return round(in_cost + out_cost, 6)


def usd_to_inr(cost_usd: float, rate: float = 85.0) -> float:
    """Converts internal USD token cost to INR for display and UI metrics."""
    return round(cost_usd * rate, 2)



class ContextBudgeter:
    """
    Builds context payloads within a specified token budget.
    Ensures critical sections (constraints, candidates) are never dropped.
    """

    def __init__(self, max_tokens: int = 2048):
        self.max_tokens = max_tokens

    def build_prompt_payload(
        self,
        critical_constraints: Dict[str, Any],
        candidate_flights: List[Dict[str, Any]],
        original_booking: Dict[str, Any],
        hotel_context: Optional[Dict[str, Any]] = None,
        retrieved_chunks: Optional[List[str]] = None,
        audit_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any], int, bool]:
        """
        Builds a structured dictionary payload fitting within `max_tokens`.
        
        Returns:
            (payload_dict, estimated_tokens, was_truncated)
        """
        was_truncated = False

        # Tier 1 (Critical) - always included
        tier1 = {
            "constraints": critical_constraints,
            "candidates": candidate_flights,
            "original_booking": {
                "flight_number": original_booking.get("flight_number"),
                "origin": original_booking.get("origin"),
                "destination": original_booking.get("destination"),
                "cabin_class": original_booking.get("cabin_class"),
                "fare_paid_inr": original_booking.get("fare_paid_inr"),
                "departure_time": str(original_booking.get("departure_time")),
                "arrival_time": str(original_booking.get("arrival_time")),
            },
        }

        base_tokens = estimate_token_count(json.dumps(tier1))
        remaining_budget = max(0, self.max_tokens - base_tokens)

        # Tier 2 (Medium) - Hotel and Disruption Context
        tier2_hotel = {}
        if hotel_context:
            hotel_summary = {
                "hotel_name": hotel_context.get("hotel_name"),
                "checkin_date": str(hotel_context.get("checkin_date")),
                "checkout_date": str(hotel_context.get("checkout_date")),
            }
            hotel_tokens = estimate_token_count(json.dumps(hotel_summary))
            if hotel_tokens <= remaining_budget:
                tier2_hotel = hotel_summary
                remaining_budget -= hotel_tokens
            else:
                was_truncated = True

        # Tier 3 (Low) - Retrieved Policy Chunks
        tier3_chunks = []
        if retrieved_chunks:
            for chunk in retrieved_chunks:
                c_tokens = estimate_token_count(chunk)
                if c_tokens <= remaining_budget:
                    tier3_chunks.append(chunk)
                    remaining_budget -= c_tokens
                else:
                    was_truncated = True
                    break

        # Tier 4 (Lowest) - Audit History
        tier4_history = []
        if audit_history:
            for item in audit_history:
                item_str = json.dumps(item)
                item_tokens = estimate_token_count(item_str)
                if item_tokens <= remaining_budget:
                    tier4_history.append(item)
                    remaining_budget -= item_tokens
                else:
                    was_truncated = True
                    break

        payload = {
            "critical": tier1,
            "hotel": tier2_hotel if tier2_hotel else None,
            "policy_citations": tier3_chunks,
            "recent_history": tier4_history,
        }

        total_tokens = estimate_token_count(json.dumps(payload))
        return payload, total_tokens, was_truncated
