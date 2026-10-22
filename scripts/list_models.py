"""
List generateContent-capable models for the configured Google Gemini API Key.
Exits 0 on success, non-zero if key is missing or request fails.
Never prints or logs the API key.
Enforces daily safety limit, shared persistent counter, and pacing.
"""

import os
import sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if (ROOT_DIR / "backend").exists():
    sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, "/app")

load_dotenv(ROOT_DIR / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env")
load_dotenv(".env")

api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
model = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite").strip()

if not api_key:
    print("[ERROR] GOOGLE_API_KEY is not configured in environment or .env file.")
    sys.exit(1)

try:
    from app.agent.llm_safety import check_call_safety, record_call_attempt, sync_pace_call

    # 1. Hard safety limit check
    allowed, reason = check_call_safety(model)
    if not allowed:
        print(f"[ERROR] LLM Safety Limit Reached: Model '{model}' has hit daily threshold ({reason}). Refusing real API call.")
        sys.exit(3)

    # 2. Record this call attempt in the shared persistent counter
    record_call_attempt(model)

    # 3. Pacing: wait at least (60 / rpm) * 1.2 seconds, concurrency 1
    sync_pace_call(model)

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    resp = httpx.get(url, timeout=20.0)
    resp.raise_for_status()
    data = resp.json()

    models = data.get("models", [])
    gen_models = [
        m.get("name")
        for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]

    print(f"=== Available generateContent Models ({len(gen_models)} found) ===")
    for m in gen_models:
        print(f"  • {m}")
    sys.exit(0)

except Exception as e:
    print(f"[ERROR] Failed to list Gemini models: {e}")
    sys.exit(2)
