"""
Demo Database Seeder for ReRoute.

Idempotently seeds:
- 1 Demo User (demo.traveler@reroute.travel with real bcrypt-hashed password)
- 1 Itinerary container (ACTIVE)
- 2 Flight Legs (Leg 1: DEL -> BOM 6E-204, Leg 2: BOM -> GOI 6E-512)
- 1 Linked Hotel Booking (Taj Exotica Resort Goa)
into PostgreSQL and prints all generated primary key IDs and credentials.
"""

import asyncio
from datetime import datetime, date, timezone
import os
import sys
import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Ensure backend root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.core.database import async_session_factory, init_db
from app.models.user import User
from app.models.itinerary import Itinerary
from app.models.flight_leg import FlightLeg
from app.models.hotel import HotelBooking

DEMO_EMAIL = "demo.traveler@reroute.travel"
DEMO_PASSWORD = "DemoPassword123!"


async def seed_demo():
    print("=== Initializing Database Schema ===")
    await init_db()

    print("=== Seeding Demo Data (Idempotent) ===")
    async with async_session_factory() as session:
        # Check if demo user already exists
        user_stmt = select(User).where(User.email == DEMO_EMAIL)
        demo_user = (await session.execute(user_stmt)).scalars().first()

        pw_bytes = DEMO_PASSWORD.encode("utf-8")
        salt = bcrypt.gensalt()
        pw_hash = bcrypt.hashpw(pw_bytes, salt).decode("utf-8")

        if not demo_user:
            demo_user = User(
                name="Demo Traveler",
                email=DEMO_EMAIL,
                phone="+919876543210",
                password_hash=pw_hash,
            )
            session.add(demo_user)
            await session.flush()
        else:
            # Update password hash to verified bcrypt
            demo_user.password_hash = pw_hash
            await session.flush()

        # Check existing itinerary for this user
        itin_stmt = (
            select(Itinerary)
            .where(Itinerary.user_id == demo_user.id)
            .options(
                selectinload(Itinerary.flight_legs),
                selectinload(Itinerary.hotel_bookings),
            )
            .order_by(Itinerary.id.asc())
        )
        itinerary = (await session.execute(itin_stmt)).scalars().first()

        if not itinerary:
            itinerary = Itinerary(
                user_id=demo_user.id,
                status="ACTIVE",
            )
            session.add(itinerary)
            await session.flush()

            # Flight Leg 1: DEL -> BOM (6E-204)
            leg1 = FlightLeg(
                itinerary_id=itinerary.id,
                leg_order=1,
                airline_code="6E",
                flight_number="204",
                pnr="PNR-DEMO-01",
                eticket_number="098-1002003001",
                origin="DEL",
                destination="BOM",
                departure_datetime=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc),
                arrival_datetime=datetime(2026, 10, 20, 12, 10, 0, tzinfo=timezone.utc),
                cabin_class="ECONOMY",
                fare_paid=4500.0,
                currency="INR",
                status="ON_TIME",
            )
            session.add(leg1)

            # Flight Leg 2: BOM -> GOI (6E-512)
            leg2 = FlightLeg(
                itinerary_id=itinerary.id,
                leg_order=2,
                airline_code="6E",
                flight_number="512",
                pnr="PNR-DEMO-02",
                eticket_number="098-1002003002",
                origin="BOM",
                destination="GOI",
                departure_datetime=datetime(2026, 10, 20, 14, 30, 0, tzinfo=timezone.utc),
                arrival_datetime=datetime(2026, 10, 20, 15, 45, 0, tzinfo=timezone.utc),
                cabin_class="ECONOMY",
                fare_paid=2800.0,
                currency="INR",
                status="ON_TIME",
            )
            session.add(leg2)

            # Hotel Booking: Taj Exotica Resort Goa
            hotel = HotelBooking(
                itinerary_id=itinerary.id,
                hotel_name="Taj Exotica Resort Goa",
                confirmation_reference="HTL-GOA-DEMO-88",
                checkin_date=date(2026, 10, 20),
                checkout_date=date(2026, 10, 23),
                room_rate=8500.0,
                currency="INR",
                address="Benaulim Beach, South Goa, 403716",
                status="CONFIRMED",
            )
            session.add(hotel)
            await session.commit()
        else:
            # Re-use existing itinerary and components
            legs = sorted(itinerary.flight_legs, key=lambda l: l.leg_order)
            leg1 = legs[0] if len(legs) > 0 else None
            leg2 = legs[1] if len(legs) > 1 else None
            hotel = itinerary.hotel_bookings[0] if itinerary.hotel_bookings else None
            await session.commit()

        print("\n========================================")
        print(" DEMO DATA READY (IDEMPOTENT)")
        print("========================================")
        print(f" Demo Email:         {DEMO_EMAIL}")
        print(f" Demo Password:      {DEMO_PASSWORD}")
        print(f" User ID:            {demo_user.id}")
        print(f" Itinerary ID:       {itinerary.id}")
        print(f" Flight Leg 1 ID:    {leg1.id if leg1 else 'N/A'} (6E-204: DEL -> BOM)")
        print(f" Flight Leg 2 ID:    {leg2.id if leg2 else 'N/A'} (6E-512: BOM -> GOI)")
        print(f" Hotel Booking ID:   {hotel.id if hotel else 'N/A'} (Taj Exotica Resort Goa)")
        print("========================================\n")


if __name__ == "__main__":
    asyncio.run(seed_demo())
