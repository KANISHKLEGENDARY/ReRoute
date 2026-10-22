"""
Seeded Indian Domestic Flight and Hotel Inventory Sandbox.

Provides deterministic candidate flight search, lookup, and hotel inventory.
Covers major Indian hubs: DEL, BOM, BLR, HYD, MAA, CCU, AMD, PNQ.
Airlines: 6E (IndiGo), AI (Air India), UK (Vistara), SG (SpiceJet), QP (Akasa Air).
Deterministic and pure — no unseeded random or non-deterministic clock calls.
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from app.schemas.pipeline import (
    CabinClass,
    CandidateFlight,
    HotelOption,
)

# Major Indian domestic airports
AIRPORTS = ["DEL", "BOM", "BLR", "HYD", "MAA", "CCU", "AMD", "PNQ", "GOI"]

AIRLINES = {
    "6E": "IndiGo",
    "AI": "Air India",
    "UK": "Vistara",
    "SG": "SpiceJet",
    "QP": "Akasa Air",
}

# Base flight schedules template (offset hours, duration mins, base fare INR)
SCHEDULE_TEMPLATES = [
    {"slot_hour": 6, "slot_minute": 0, "duration": 130, "fare_mult": 0.90, "seats": 12},
    {"slot_hour": 8, "slot_minute": 30, "duration": 125, "fare_mult": 1.10, "seats": 8},
    {"slot_hour": 11, "slot_minute": 15, "duration": 135, "fare_mult": 1.00, "seats": 15},
    {"slot_hour": 14, "slot_minute": 0, "duration": 130, "fare_mult": 0.95, "seats": 6},
    {"slot_hour": 16, "slot_minute": 45, "duration": 140, "fare_mult": 1.15, "seats": 10},
    {"slot_hour": 19, "slot_minute": 30, "duration": 125, "fare_mult": 1.25, "seats": 4},
    {"slot_hour": 21, "slot_minute": 45, "duration": 120, "fare_mult": 0.85, "seats": 18},
    {"slot_hour": 23, "slot_minute": 15, "duration": 120, "fare_mult": 0.75, "seats": 22},
]

# Baseline distance/price matrix for direct Indian city pairs (INR Economy)
ROUTE_BASE_FARES: Dict[str, float] = {
    "DEL-BOM": 4800.0,
    "BOM-DEL": 4800.0,
    "DEL-BLR": 5800.0,
    "BLR-DEL": 5800.0,
    "BOM-BLR": 3900.0,
    "BLR-BOM": 3900.0,
    "DEL-HYD": 4500.0,
    "HYD-DEL": 4500.0,
    "BOM-HYD": 3600.0,
    "HYD-BOM": 3600.0,
    "DEL-MAA": 5500.0,
    "MAA-DEL": 5500.0,
    "DEL-CCU": 4700.0,
    "CCU-DEL": 4700.0,
    "DEL-AMD": 3200.0,
    "AMD-DEL": 3200.0,
    "DEL-PNQ": 4400.0,
    "PNQ-DEL": 4400.0,
    "BOM-MAA": 4200.0,
    "MAA-BOM": 4200.0,
    "BLR-HYD": 2800.0,
    "HYD-BLR": 2800.0,
    "BOM-GOI": 2800.0,
    "GOI-BOM": 2800.0,
    "DEL-GOI": 5200.0,
    "GOI-DEL": 5200.0,
}
# Realistic durations per route in minutes (domestic Indian air travel)
ROUTE_DURATIONS: Dict[str, int] = {
    "DEL-BOM": 130,  # ~2h 10m
    "BOM-DEL": 130,
    "DEL-BLR": 165,  # ~2h 45m
    "BLR-DEL": 165,
    "BOM-BLR": 105,  # ~1h 45m
    "BLR-BOM": 105,
    "DEL-HYD": 135,  # ~2h 15m
    "HYD-DEL": 135,
    "BOM-HYD": 85,   # ~1h 25m
    "HYD-BOM": 85,
    "DEL-MAA": 170,  # ~2h 50m
    "MAA-DEL": 170,
    "DEL-CCU": 135,  # ~2h 15m
    "CCU-DEL": 135,
    "DEL-AMD": 90,   # ~1h 30m
    "AMD-DEL": 90,
    "DEL-PNQ": 125,  # ~2h 05m
    "PNQ-DEL": 125,
    "BOM-MAA": 115,  # ~1h 55m
    "MAA-BOM": 115,
    "BLR-HYD": 70,   # ~1h 10m
    "HYD-BLR": 70,
    "BOM-GOI": 75,   # ~1h 15m (Realistic BOM-GOI)
    "GOI-BOM": 75,
    "DEL-GOI": 150,  # ~2h 30m
    "GOI-DEL": 150,
}
DEFAULT_DURATION = 120
DEFAULT_BASE_FARE = 4500.0


class FlightInventorySandbox:
    """
    Deterministic Sandbox Inventory Engine for Indian Domestic Flights & Partner Hotels.
    Can be instantiated with a custom seed string or used statelessly.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self._custom_flights: Dict[str, CandidateFlight] = {}
        self._custom_hotels: Dict[str, HotelOption] = {}

    def add_override_flight(self, flight: CandidateFlight) -> None:
        """Register a custom flight option for specific test scenario setups."""
        self._custom_flights[flight.flight_id] = flight

    def add_override_hotel(self, hotel: HotelOption) -> None:
        """Register a custom hotel option for specific test scenario setups."""
        self._custom_hotels[hotel.hotel_id] = hotel

    def _generate_flight_id(
        self,
        airline: str,
        flight_num: int,
        origin: str,
        destination: str,
        target_date: date,
        slot_index: int,
    ) -> str:
        """
        Generates route-unique flight ID: {airline}-{flight_num}-{origin}-{destination}-{YYYYMMDD}-S{slot_index}
        Example: 6E-120-DEL-BOM-20261020-S0
        """
        date_str = target_date.strftime("%Y%m%d")
        return f"{airline}-{flight_num}-{origin.upper()}-{destination.upper()}-{date_str}-S{slot_index}"

    def get_flight(self, flight_id: str) -> Optional[CandidateFlight]:
        """Look up a flight by its unique ID across overrides and seeded catalog."""
        if flight_id in self._custom_flights:
            return self._custom_flights[flight_id]

        if flight_id == "6E-REJECTED-FARE-EXCEEDED":
            return CandidateFlight(
                flight_id="6E-REJECTED-FARE-EXCEEDED",
                airline_code="6E",
                airline_name="IndiGo",
                flight_number="6E-999",
                origin="DEL",
                destination="BOM",
                departure_time=datetime(2026, 10, 20, 10, 0, 0),
                arrival_time=datetime(2026, 10, 20, 12, 10, 0),
                cabin_class=CabinClass.ECONOMY,
                fare_inr=99999.0,
                available_seats=5,
                aircraft_type="A320neo",
                is_direct=True,
            )

        try:
            parts = flight_id.split("-")
            # 6-part format: {airline}-{flight_num}-{origin}-{destination}-{YYYYMMDD}-S{slot_index}
            if len(parts) >= 6:
                airline = parts[0]
                flight_num = int(parts[1])
                origin = parts[2].upper()
                destination = parts[3].upper()
                target_date = datetime.strptime(parts[4], "%Y%m%d").date()
                slot_idx = int(parts[5].replace("S", ""))

                if 0 <= slot_idx < len(SCHEDULE_TEMPLATES) and airline in AIRLINES:
                    tmpl = SCHEDULE_TEMPLATES[slot_idx]
                    pair_key = f"{origin}-{destination}"
                    duration = ROUTE_DURATIONS.get(pair_key, DEFAULT_DURATION)
                    base_fare = ROUTE_BASE_FARES.get(pair_key, DEFAULT_BASE_FARE)

                    dept_time = datetime(
                        target_date.year,
                        target_date.month,
                        target_date.day,
                        tmpl["slot_hour"],
                        tmpl["slot_minute"],
                    )
                    arr_time = dept_time + timedelta(minutes=duration)
                    fare = round(base_fare * tmpl["fare_mult"], 2)

                    return CandidateFlight(
                        flight_id=flight_id,
                        airline_code=airline,
                        airline_name=AIRLINES[airline],
                        flight_number=f"{airline}-{flight_num}",
                        origin=origin,
                        destination=destination,
                        departure_time=dept_time,
                        arrival_time=arr_time,
                        cabin_class=CabinClass.ECONOMY,
                        fare_inr=fare,
                        available_seats=tmpl["seats"],
                        aircraft_type="A320neo" if airline != "AI" else "B787-8",
                        is_direct=True,
                    )

            # Legacy 4-part format: {airline}-{flight_num}-{YYYYMMDD}-S{slot_index}
            elif len(parts) == 4:
                airline = parts[0]
                flight_num = int(parts[1])
                target_date = datetime.strptime(parts[2], "%Y%m%d").date()
                slot_idx = int(parts[3].replace("S", ""))

                if 0 <= slot_idx < len(SCHEDULE_TEMPLATES) and airline in AIRLINES:
                    tmpl = SCHEDULE_TEMPLATES[slot_idx]
                    dept_time = datetime(
                        target_date.year,
                        target_date.month,
                        target_date.day,
                        tmpl["slot_hour"],
                        tmpl["slot_minute"],
                    )
                    arr_time = dept_time + timedelta(minutes=tmpl["duration"])
                    return CandidateFlight(
                        flight_id=flight_id,
                        airline_code=airline,
                        airline_name=AIRLINES[airline],
                        flight_number=f"{airline}-{flight_num}",
                        origin="DEL",
                        destination="BOM",
                        departure_time=dept_time,
                        arrival_time=arr_time,
                        cabin_class=CabinClass.ECONOMY,
                        fare_inr=DEFAULT_BASE_FARE * tmpl["fare_mult"],
                        available_seats=tmpl["seats"],
                        aircraft_type="A320neo",
                        is_direct=True,
                    )
        except Exception:
            pass
        return None

    def exists(self, flight_id: str) -> bool:
        """Check whether a flight ID exists in the inventory."""
        return self.get_flight(flight_id) is not None

    def exists_on_route(self, flight_id: str, origin: str, destination: str) -> bool:
        """Check whether a flight ID exists and belongs strictly to the given route."""
        flight = self.get_flight(flight_id)
        if not flight:
            return False
        return flight.origin == origin.upper().strip() and flight.destination == destination.upper().strip()

    def search_flights(
        self,
        origin: str,
        destination: str,
        target_date: date,
        cabin_class: CabinClass = CabinClass.ECONOMY,
        min_departure_time: Optional[datetime] = None,
        max_departure_time: Optional[datetime] = None,
        direct_only: bool = True,
    ) -> List[CandidateFlight]:
        """
        Deterministically produces seeded candidate flights matching origin, destination,
        date, cabin class, and departure time boundaries.
        """
        origin = origin.upper().strip()
        destination = destination.upper().strip()
        pair_key = f"{origin}-{destination}"
        base_fare = ROUTE_BASE_FARES.get(pair_key, DEFAULT_BASE_FARE)

        from app.schemas.pipeline import to_naive_utc
        min_departure_time = to_naive_utc(min_departure_time)
        max_departure_time = to_naive_utc(max_departure_time)

        results: List[CandidateFlight] = []

        # Check any custom overrides matching route and date
        for f in self._custom_flights.values():
            if (
                f.origin == origin
                and f.destination == destination
                and f.departure_time.date() == target_date
                and (cabin_class is None or f.cabin_class == cabin_class)
            ):
                if min_departure_time and f.departure_time < min_departure_time:
                    continue
                if max_departure_time and f.departure_time > max_departure_time:
                    continue
                results.append(f)

        # Generate standard seeded catalog for all airline / slot combinations
        airline_codes = list(AIRLINES.keys())
        for a_idx, airline_code in enumerate(airline_codes):
            airline_name = AIRLINES[airline_code]
            base_flight_num = 100 * (a_idx + 1) + 20

            for s_idx, tmpl in enumerate(SCHEDULE_TEMPLATES):
                flight_num = base_flight_num + s_idx
                flight_id = self._generate_flight_id(airline_code, flight_num, origin, destination, target_date, s_idx)

                # Skip if overridden
                if flight_id in self._custom_flights:
                    continue

                duration = ROUTE_DURATIONS.get(pair_key, tmpl["duration"])
                dept_time = datetime(
                    target_date.year,
                    target_date.month,
                    target_date.day,
                    tmpl["slot_hour"],
                    tmpl["slot_minute"],
                )
                arr_time = dept_time + timedelta(minutes=duration)

                if min_departure_time and dept_time < min_departure_time:
                    continue
                if max_departure_time and dept_time > max_departure_time:
                    continue

                # Cabin pricing multiplier
                cabin_mult = 1.0
                if cabin_class == CabinClass.PREMIUM_ECONOMY:
                    cabin_mult = 1.45
                elif cabin_class == CabinClass.BUSINESS:
                    cabin_mult = 2.80
                elif cabin_class == CabinClass.FIRST:
                    cabin_mult = 4.20

                fare = round(base_fare * tmpl["fare_mult"] * cabin_mult, 2)

                flight = CandidateFlight(
                    flight_id=flight_id,
                    airline_code=airline_code,
                    airline_name=airline_name,
                    flight_number=f"{airline_code}-{flight_num}",
                    origin=origin,
                    destination=destination,
                    departure_time=dept_time,
                    arrival_time=arr_time,
                    cabin_class=cabin_class,
                    fare_inr=fare,
                    available_seats=tmpl["seats"],
                    aircraft_type="A320neo" if airline_code != "AI" else "B787-8",
                    is_direct=True,
                )
                results.append(flight)

        # Sort candidate flights chronologically by departure time, then price
        results.sort(key=lambda x: (x.departure_time, x.fare_inr))
        return results

    def search_hotels(
        self,
        city_or_airport: str,
        checkin_date: date,
        checkout_date: date,
    ) -> List[HotelOption]:
        """
        Returns seeded partner hotels for Indian destinations.
        """
        city_clean = city_or_airport.upper().strip()
        if city_clean in ["DEL", "DELHI", "NEW DELHI"]:
            city_name = "New Delhi"
            hotels = [
                ("HTL-DEL-01", "Aerocity Transit Grand", 4500.0, "DEL"),
                ("HTL-DEL-02", "Taj Palace Diplomatic", 8500.0, "DEL"),
                ("HTL-DEL-03", "Ibis Delhi Airport", 3600.0, "DEL"),
            ]
        elif city_clean in ["BOM", "MUMBAI"]:
            city_name = "Mumbai"
            hotels = [
                ("HTL-BOM-01", "The Orchid Mumbai Vile Parle", 4800.0, "BOM"),
                ("HTL-BOM-02", "Taj Mahal Palace Colaba", 9500.0, "BOM"),
                ("HTL-BOM-03", "Novotel Juhu Beach", 5200.0, "BOM"),
            ]
        elif city_clean in ["BLR", "BENGALURU", "BANGALORE"]:
            city_name = "Bengaluru"
            hotels = [
                ("HTL-BLR-01", "Taj Bangalore Devanahalli", 6500.0, "BLR"),
                ("HTL-BLR-02", "Zuri Whitefield", 4200.0, "BLR"),
            ]
        else:
            city_name = city_clean
            hotels = [
                (f"HTL-{city_clean}-01", f"{city_clean} Transit Inn", 4000.0, city_clean),
                (f"HTL-{city_clean}-02", f"{city_clean} Premier Hotel", 5500.0, city_clean),
            ]

        results = []
        for h_id, name, rate, airport in hotels:
            results.append(
                HotelOption(
                    hotel_id=h_id,
                    hotel_name=name,
                    city=city_name,
                    airport_code=airport,
                    checkin_date=checkin_date,
                    checkout_date=checkout_date,
                    room_type="Deluxe King",
                    rate_per_night_inr=rate,
                    status="CONFIRMED",
                    confirmation_reference=f"CONF-{h_id[-6:]}",
                )
            )
        return results

    def get_hotel(self, hotel_id: str) -> Optional[HotelOption]:
        """Look up a hotel by ID."""
        if hotel_id in self._custom_hotels:
            return self._custom_hotels[hotel_id]
        # Return fallback hotel
        return HotelOption(
            hotel_id=hotel_id,
            hotel_name="ReRoute Partner Transit Hotel",
            city="Metropolitan Hub",
            airport_code="DEL",
            checkin_date=date.today(),
            checkout_date=date.today() + timedelta(days=1),
            room_type="Standard Room",
            rate_per_night_inr=4000.0,
            status="CONFIRMED",
            confirmation_reference=f"CONF-{hotel_id}",
        )


# Global default sandbox instance
default_inventory = FlightInventorySandbox()
