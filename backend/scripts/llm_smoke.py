"""
Smoke Test for Configured Google Gemini Model.
Makes one real call, prints reply, token counts, and INR cost.
Exits 0 on success, non-zero on failure.
Never logs or prints the API key.
Enforces daily safety limit, shared persistent counter, and pacing.
"""

import os
import sys
from pathlib import Path
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
model = os.environ.get("LLM_MODEL", "").strip()
usd_to_inr = float(os.environ.get("USD_TO_INR", "85.0"))
price_in = float(os.environ.get("LLM_PRICE_INPUT_PER_MTOK_USD", "0.075"))
price_out = float(os.environ.get("LLM_PRICE_OUTPUT_PER_MTOK_USD", "0.30"))

if not api_key:
    print("[ERROR] GOOGLE_API_KEY is not configured.")
    sys.exit(1)

if not model:
    print("[ERROR] LLM_MODEL is not configured.")
    sys.exit(1)

try:
    from app.agent.llm_safety import check_call_safety, record_call_attempt, sync_pace_call

    # 1. Hard safety limit check (80% daily cap)
    allowed, reason = check_call_safety(model)
    if not allowed:
        print(f"[ERROR] LLM Safety Limit Reached: Model '{model}' has hit daily threshold ({reason}). Refusing real API call.")
        sys.exit(3)

    # 2. Record this call attempt in the shared persistent counter
    record_call_attempt(model)

    # 3. Pacing: wait at least (60 / rpm) * 1.2 seconds, concurrency 1
    sync_pace_call(model)

    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage

    chat = ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=0.0,
    )

    response = chat.invoke([HumanMessage(content="Hello! Respond strictly with 'PONG: ReRoute Gemini Concierge Online'.")])

    if isinstance(response.content, list):
        reply_text = "".join(str(part.get("text", part) if isinstance(part, dict) else part) for part in response.content).strip()
    else:
        reply_text = str(response.content).strip()

    usage = getattr(response, "usage_metadata", {}) or {}
    tokens_in = usage.get("input_tokens", 10)
    tokens_out = usage.get("output_tokens", 8)

    cost_usd = (tokens_in * price_in + tokens_out * price_out) / 1_000_000.0
    cost_inr = cost_usd * usd_to_inr

    print("========================================")
    print(" LLM SMOKE TEST: SUCCESSFUL")
    print("========================================")
    print(f" Model Configured:       {model}")
    print(f" Reply:                  {reply_text}")
    print(f" Tokens In:              {tokens_in}")
    print(f" Tokens Out:             {tokens_out}")
    print(f" Notional Cost (USD):    ${cost_usd:.6f}")
    print(f" Calculated Cost (INR):  ₹{cost_inr:.4f}")
    print("========================================")
    sys.exit(0)

except Exception as e:
    print(f"[ERROR] LLM Smoke Test failed for model '{model}': {e}")
    sys.exit(2)
