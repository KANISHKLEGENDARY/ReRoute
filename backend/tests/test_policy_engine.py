"""
40+ Table-Driven Policy Engine Tests and Boundary Analysis.
"""

from datetime import datetime, timedelta
import pytest
from app.policy.engine import evaluate_policy
from app.schemas.pipeline import (
    CabinClass,
    CandidateFlight,
    OriginalBooking,
    PolicyResult,
    PolicyVerdict,
    ReasonCode,
    TripConstraints,
)


@pytest.fixture
def base_booking() -> OriginalBooking:
    return OriginalBooking(
        user_id=1,
        user_email="alex@reroute.travel",
        user_name="Alex Traveler",
        itinerary_id=101,
        flight_leg_id=501,
        airline_code="6E",
        flight_number="6E-204",
        pnr="PNR-6E-12345",
        origin="DEL",
        destination="BOM",
        departure_time=datetime(2026, 10, 15, 10, 0, 0),
        arrival_time=datetime(2026, 10, 15, 12, 10, 0),
        cabin_class=CabinClass.ECONOMY,
        fare_paid_inr=5000.0,
        status="CONFIRMED",
    )


# 40+ Table-Driven Test Matrix
POLICY_CASES = [
    # 1. Exact Compliant Baseline
    ("P01_exact_match", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    
    # 2-6. Fare Delta Boundaries (Threshold = +5000.0 INR)
    ("P02_fare_delta_zero", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P03_fare_cheaper", 4000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P04_fare_delta_exact_limit", 10000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P05_fare_delta_1_paisa_over", 10000.01, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.FARE_DELTA_EXCEEDED.value]),
    ("P06_fare_delta_extreme_high", 25000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.FARE_DELTA_EXCEEDED.value]),


    # 7-12. Arrival Delay Boundaries (Threshold = 3.0h / 180 min)
    ("P07_delay_zero", 5000.0, 60, 0, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P08_delay_60m", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P09_delay_120m", 5000.0, 60, 120, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P10_delay_exact_180m", 5000.0, 60, 180, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P11_delay_181m_over", 5000.0, 60, 181, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.ARRIVAL_DELAY_EXCEEDED.value]),
    ("P12_delay_300m_extreme", 5000.0, 60, 300, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.ARRIVAL_DELAY_EXCEEDED.value]),

    # 13-18. Cabin Class Parity & Mismatches
    ("P13_cabin_match_econ", 5500.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P14_cabin_mismatch_biz", 5500.0, 60, 60, CabinClass.BUSINESS, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.CABIN_MISMATCH.value]),
    ("P15_cabin_mismatch_premium_econ", 5500.0, 60, 60, CabinClass.PREMIUM_ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.CABIN_MISMATCH.value]),
    ("P16_cabin_mismatch_first", 5500.0, 60, 60, CabinClass.FIRST, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.CABIN_MISMATCH.value]),

    # 19-24. Seat Availability
    ("P17_seats_plenty_9", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 9, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P18_seats_exact_1", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 1, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P19_seats_zero_sold_out", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 0, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.NO_SEATS_AVAILABLE.value]),
    ("P20_seats_negative", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", -1, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.NO_SEATS_AVAILABLE.value]),

    # 25-28. Route & Airport Integrity
    ("P21_route_correct_del_bom", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P22_origin_mismatch_blr_bom", 5000.0, 60, 60, CabinClass.ECONOMY, "BLR", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.ROUTE_MISMATCH.value]),
    ("P23_dest_mismatch_del_hyd", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "HYD", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.ROUTE_MISMATCH.value]),
    ("P24_route_reverse_bom_del", 5000.0, 60, 60, CabinClass.ECONOMY, "BOM", "DEL", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.ROUTE_MISMATCH.value]),


    # 29-33. Departure Feasibility / Airport Buffer (Disruption at 09:00, Buffer = 45m -> Min Dep 09:45)
    # dep_offset_mins relative to disruption time 09:00 (10:00 is +60m)
    ("P25_dep_buffer_plenty_60m", 5000.0, 60, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P26_dep_buffer_exact_45m", 5000.0, 45, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P27_dep_buffer_too_tight_44m", 5000.0, 44, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.DEPARTURE_TOO_EARLY.value]),
    ("P28_dep_in_past_negative", 5000.0, -10, 60, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.DEPARTURE_TOO_EARLY.value]),

    # 34-38. Downstream Connection Buffer (Connection Dep at 15:00, Buffer = 45m -> Max Arr 14:15)
    # arr_offset_mins relative to original arr 12:10 (14:15 is +125m)
    ("P29_downstream_plenty_arr_1300", 5000.0, 60, 50, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 180, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P30_downstream_exact_arr_1415", 5000.0, 60, 125, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 170, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P31_downstream_tight_arr_1416", 5000.0, 60, 126, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 170, PolicyVerdict.REJECTED, [ReasonCode.DOWNSTREAM_INFEASIBLE.value]),

    # 39-45. Multi-Failure Compound Violations (Ensures ALL failing reasons are accumulated)
    ("P32_multi_fare_and_delay", 15000.0, 60, 240, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.FARE_DELTA_EXCEEDED.value, ReasonCode.ARRIVAL_DELAY_EXCEEDED.value]),
    ("P33_multi_cabin_and_seats", 5000.0, 60, 60, CabinClass.BUSINESS, "DEL", "BOM", 0, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.CABIN_MISMATCH.value, ReasonCode.NO_SEATS_AVAILABLE.value]),
    ("P34_multi_route_and_early", 5000.0, 20, 60, CabinClass.ECONOMY, "BLR", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.ROUTE_MISMATCH.value, ReasonCode.DEPARTURE_TOO_EARLY.value]),
    ("P35_multi_fare_cabin_delay", 18000.0, 60, 250, CabinClass.BUSINESS, "DEL", "BOM", 5, 0, 0, PolicyVerdict.REJECTED, [ReasonCode.FARE_DELTA_EXCEEDED.value, ReasonCode.CABIN_MISMATCH.value, ReasonCode.ARRIVAL_DELAY_EXCEEDED.value]),
    ("P36_multi_all_rules_fail", 20000.0, 10, 300, CabinClass.FIRST, "HYD", "MAA", 0, 0, 120, PolicyVerdict.REJECTED, [
        ReasonCode.NO_SEATS_AVAILABLE.value,
        ReasonCode.ROUTE_MISMATCH.value,
        ReasonCode.CABIN_MISMATCH.value,
        ReasonCode.FARE_DELTA_EXCEEDED.value,
        ReasonCode.ARRIVAL_DELAY_EXCEEDED.value,
        ReasonCode.DEPARTURE_TOO_EARLY.value,
        ReasonCode.DOWNSTREAM_INFEASIBLE.value,
    ]),
    ("P37_fare_under_limit_small_delta", 5100.0, 60, 10, CabinClass.ECONOMY, "DEL", "BOM", 5, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P38_fare_exact_same", 5000.0, 60, 20, CabinClass.ECONOMY, "DEL", "BOM", 3, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P39_arrival_same_time", 5000.0, 60, 0, CabinClass.ECONOMY, "DEL", "BOM", 8, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P40_arrival_earlier", 4900.0, 60, 0, CabinClass.ECONOMY, "DEL", "BOM", 12, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P41_delay_179m_just_under", 5000.0, 60, 179, CabinClass.ECONOMY, "DEL", "BOM", 4, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
    ("P42_fare_4999_just_under", 9999.0, 60, 30, CabinClass.ECONOMY, "DEL", "BOM", 6, 0, 0, PolicyVerdict.APPROVED, [ReasonCode.POLICY_COMPLIANT.value]),
]


@pytest.mark.parametrize(
    "case_id,fare,dep_offset_m,arr_delay_m,cabin,orig,dest,seats,dep_too_early_m,downstream_delay_m,expected_verdict,expected_reasons",
    POLICY_CASES,
)
def test_policy_engine_matrix(
    base_booking,
    case_id,
    fare,
    dep_offset_m,
    arr_delay_m,
    cabin,
    orig,
    dest,
    seats,
    dep_too_early_m,
    downstream_delay_m,
    expected_verdict,
    expected_reasons,
):
    disruption_time = datetime(2026, 10, 15, 9, 0, 0)
    
    cand_dep = disruption_time + timedelta(minutes=dep_offset_m)
    cand_arr = base_booking.arrival_time + timedelta(minutes=arr_delay_m)

    candidate = CandidateFlight(
        flight_id=f"CAND-{case_id}",
        airline_code="6E",
        airline_name="IndiGo",
        flight_number="6E-555",
        origin=orig,
        destination=dest,
        departure_time=cand_dep,
        arrival_time=cand_arr,
        cabin_class=cabin,
        fare_inr=fare,
        available_seats=seats,
        aircraft_type="A320neo",
        is_direct=True,
    )

    downstream_dep = None
    if downstream_delay_m > 0:
        downstream_dep = base_booking.arrival_time + timedelta(minutes=downstream_delay_m)

    constraints = TripConstraints(
        max_fare_delta_inr=5000.0,
        max_delay_hours=3.0,
        min_airport_buffer_minutes=45,
        min_connection_buffer_minutes=45,
        allowed_cabins=[CabinClass.ECONOMY],
        required_origin="DEL",
        required_destination="BOM",
        earliest_departure_time=disruption_time,
        original_arrival_time=base_booking.arrival_time,
        downstream_departure_time=downstream_dep,
    )

    result: PolicyResult = evaluate_policy(
        candidate=candidate,
        original_booking=base_booking,
        constraints=constraints,
        disruption_time=disruption_time,
    )

    assert result.verdict == expected_verdict, f"Case {case_id} failed verdict check"
    for reason in expected_reasons:
        assert reason in result.reasons, f"Case {case_id} missing reason '{reason}'. Got: {result.reasons}"
