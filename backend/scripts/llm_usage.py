#!/usr/bin/env python3
"""
CLI utility to display Gemini LLM usage metrics.
Prints today's call count, daily limit, hard stop threshold, and calls remaining per model.
Pacific day boundary (America/Los_Angeles).
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

from app.agent.llm_safety import (
    DEFAULT_MODEL_LIMITS,
    get_model_limits,
    get_model_call_count,
    get_pacific_date,
    get_usage_file_path,
    _read_usage_data,
)


def main():
    today = get_pacific_date()
    usage_file = get_usage_file_path()
    usage_data = _read_usage_data(usage_file)

    all_models = list(DEFAULT_MODEL_LIMITS.keys())
    for m in usage_data.keys():
        if m not in all_models:
            all_models.append(m)

    print("=" * 72)
    print(f" GEMINI LLM USAGE MONITOR (Pacific Day: {today} / America/Los_Angeles)")
    print(f" Shared Usage File: {usage_file}")
    print("=" * 72)
    print(f"{'Model':<25} | {'Today':<7} | {'RPD Limit':<10} | {'80% Cap':<8} | {'Left':<6} | {'RPM Pacing':<10}")
    print("-" * 72)

    for model in all_models:
        limits = get_model_limits(model)
        rpd = limits["rpd"]
        rpm = limits["rpm"]
        stop_thresh = limits["stop_threshold"]
        pacing_sec = limits["pacing_interval_sec"]

        calls_today = get_model_call_count(model, today)
        left = max(0, stop_thresh - calls_today)

        pacing_str = f"{rpm} rpm ({pacing_sec:.1f}s)"
        print(f"{model:<25} | {calls_today:<7} | {rpd:<10} | {stop_thresh:<8} | {left:<6} | {pacing_str:<10}")

    print("=" * 72)


if __name__ == "__main__":
    main()
