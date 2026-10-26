"""
Smoke test script for deployed or local ReRoute backend.

Checks:
1. GET /api/v1/health (verifies service liveness and database connection)
2. GET /api/v1/metrics (verifies analytics aggregation)
3. POST /api/v1/events/simulate (dispatches a test disruption with X-Demo-Key)
4. GET /api/v1/events/{event_id} (waits up to 90s for cold start and paced LLM processing)

Usage:
    python scripts/smoke_test.py [BASE_URL] [DEMO_KEY]
    python scripts/smoke_test.py --url https://reroute-api.onrender.com --key my-secret-key
"""

import argparse
import os
import sys
import time
import httpx


def parse_args():
    parser = argparse.ArgumentParser(description="ReRoute Production Smoke Test")
    parser.add_argument("pos_url", nargs="?", default=None, help="Base URL (positional)")
    parser.add_argument("pos_key", nargs="?", default=None, help="Demo API Key (positional)")
    parser.add_argument("--url", default=None, help="Backend base URL")
    parser.add_argument("--key", default=None, help="Demo API Key (X-Demo-Key)")
    args = parser.parse_args()

    base_url = args.url or args.pos_url or os.environ.get("BACKEND_URL", "http://localhost:8000")
    demo_key = args.key or args.pos_key or os.environ.get("DEMO_API_KEY", "")
    return base_url.rstrip("/"), demo_key


def run_smoke_test(base_url: str, demo_key: str) -> bool:
    print(f"\n=======================================================")
    print(f" ReRoute Deployment Smoke Test")
    print(f" Target: {base_url}")
    print(f" Demo Key: {'[Configured]' if demo_key else '[None]'}")
    print(f"=======================================================\n")

    client = httpx.Client(timeout=30.0)
    headers = {"X-Demo-Key": demo_key} if demo_key else {}

    # Step 1: Health Check
    try:
        resp = client.get(f"{base_url}/api/v1/health")
        if resp.status_code == 200:
            data = resp.json()
            print(f"[PASS] Step 1: /health -> 200 OK (status: {data.get('status', 'healthy')})")
        else:
            print(f"[FAIL] Step 1: /health returned HTTP {resp.status_code} ({resp.text})")
            return False
    except Exception as e:
        print(f"[FAIL] Step 1: /health connection error: {e}")
        return False

    # Step 2: Metrics Check
    try:
        resp = client.get(f"{base_url}/api/v1/metrics")
        if resp.status_code == 200:
            m = resp.json()
            print(f"[PASS] Step 2: /metrics -> 200 OK (events={m.get('total_events', 0)}, cost=INR {m.get('total_cost_inr', 0)})")
        else:
            print(f"[FAIL] Step 2: /metrics returned HTTP {resp.status_code} ({resp.text})")
            return False
    except Exception as e:
        print(f"[FAIL] Step 2: /metrics connection error: {e}")
        return False

    # Step 3: Trigger Disruption Simulation
    event_payload = {
        "flight_leg_id": 1,
        "event_type": "CANCELLED",
        "notice_text": "Flight 6E-204 cancelled due to operational disruption at Delhi airport.",
    }
    try:
        resp = client.post(f"{base_url}/api/v1/events/simulate", json=event_payload, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            event_id = data.get("event_id")
            if not event_id:
                print(f"[FAIL] Step 3: /events/simulate returned 200 but missing event_id: {data}")
                return False
            print(f"[PASS] Step 3: /events/simulate -> 200 OK (event_id={event_id})")
        elif resp.status_code == 401:
            print(f"[FAIL] Step 3: /events/simulate returned 401 Unauthorized. Check your DEMO_KEY.")
            return False
        else:
            print(f"[FAIL] Step 3: /events/simulate returned HTTP {resp.status_code} ({resp.text})")
            return False
    except Exception as e:
        print(f"[FAIL] Step 3: /events/simulate request error: {e}")
        return False

    # Step 4: Poll Event Detail (up to 90s for free tier wake-up + paced LLM loop)
    print("Waiting up to 90s for pipeline stages and final RESULT trace...")
    start_time = time.time()
    timeout_sec = 90.0

    while time.time() - start_time < timeout_sec:
        try:
            resp = client.get(f"{base_url}/api/v1/events/{event_id}")
            if resp.status_code == 200:
                detail = resp.json()
                result = detail.get("result")
                stages = [s.get("stage") for s in detail.get("stages", [])]
                if result:
                    elapsed = round(time.time() - start_time, 1)
                    action = result.get("action", "UNKNOWN")
                    verdict = result.get("policy_verdict", "UNKNOWN")
                    print(f"[PASS] Step 4: Event completed in {elapsed}s (action: {action}, verdict: {verdict})")
                    print(f"       Stages reached: {' -> '.join(stages)}")
                    return True
        except Exception:
            pass
        time.sleep(3.0)

    print(f"[FAIL] Step 4: Timed out waiting for event {event_id} after {timeout_sec}s.")
    return False


if __name__ == "__main__":
    url, key = parse_args()
    success = run_smoke_test(url, key)
    if success:
        print("\n>>> ALL SMOKE TESTS PASSED <<<\n")
        sys.exit(0)
    else:
        print("\n>>> SMOKE TEST FAILED <<<\n")
        sys.exit(1)
