"""
Unit Tests for Seeded Flight & Hotel Inventory Sandbox.
"""

from datetime import date, datetime, timedelta
import pytest
from app.sandbox.inventory import FlightInventorySandbox
from app.schemas.pipeline import CabinClass, CandidateFlight


def test_inventory_determinism():
    inv1 = FlightInventorySandbox(seed=42)
    inv2 = FlightInventorySandbox(seed=42)

    target_date = date(2026, 10, 15)
    flights1 = inv1.search_flights("DEL", "BOM", target_date)
    flights2 = inv2.search_flights("DEL", "BOM", target_date)

    assert len(flights1) > 0
    assert len(flights1) == len(flights2)
    for f1, f2 in zip(flights1, flights2):
        assert f1.flight_id == f2.flight_id
        assert f1.fare_inr == f2.fare_inr
        assert f1.departure_time == f2.departure_time


def test_inventory_route_search():
    inv = FlightInventorySandbox()
    target_date = date(2026, 10, 15)

    del_bom = inv.search_flights("DEL", "BOM", target_date)
    assert all(f.origin == "DEL" and f.destination == "BOM" for f in del_bom)

    bom_blr = inv.search_flights("BOM", "BLR", target_date)
    assert all(f.origin == "BOM" and f.destination == "BLR" for f in bom_blr)


def test_inventory_cabin_class_pricing():
    inv = FlightInventorySandbox()
    target_date = date(2026, 10, 15)

    econ_flights = inv.search_flights("DEL", "BOM", target_date, cabin_class=CabinClass.ECONOMY)
    biz_flights = inv.search_flights("DEL", "BOM", target_date, cabin_class=CabinClass.BUSINESS)

    assert len(econ_flights) == len(biz_flights)
    for ef, bf in zip(econ_flights, biz_flights):
        assert bf.fare_inr > ef.fare_inr


def test_inventory_departure_window_filtering():
    inv = FlightInventorySandbox()
    target_date = date(2026, 10, 15)
    min_dep = datetime(2026, 10, 15, 14, 0, 0)
    max_dep = datetime(2026, 10, 15, 20, 0, 0)

    filtered = inv.search_flights(
        "DEL", "BOM", target_date,
        min_departure_time=min_dep,
        max_departure_time=max_dep
    )

    for f in filtered:
        assert min_dep <= f.departure_time <= max_dep


def test_inventory_hotel_search():
    inv = FlightInventorySandbox()
    hotels = inv.search_hotels("DEL", date(2026, 10, 15), date(2026, 10, 17))
    assert len(hotels) >= 3
    assert all(h.airport_code == "DEL" for h in hotels)
    assert all(h.rate_per_night_inr > 0 for h in hotels)
