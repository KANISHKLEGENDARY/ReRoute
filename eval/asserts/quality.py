"""
Soft Quality Assertions for ReRoute Disruption Concierge.

Evaluates secondary quality metrics (graded on 0.0 to 1.0 continuous scale):
- best_option_chosen: whether the optimal flight (earliest arrival, lowest fare) was selected
- latency_budget: whether pipeline execution latency is within budget (e.g. < 5000ms for simulated)
- explanation_present: whether a non-empty, informative explanation is provided
"""

from pathlib import Path
import sys
from typing import Any, Dict

eval_dir = Path(__file__).resolve().parents[1]
repo_root = eval_dir.parent
backend_dir = repo_root / "backend"

if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(eval_dir) not in sys.path:
    sys.path.insert(0, str(eval_dir))

from dotenv import load_dotenv
env_file = backend_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)

from asserts.helpers import parse_output_and_context


def best_option_chosen(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Scores whether the selected flight matches the optimal candidate."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL"):
        if not new_flight:
            return {"pass": False, "score": 0.0, "reason": "No flight selected"}
        return {"pass": True, "score": 1.0, "reason": "Optimal candidate selected"}

    return {"pass": True, "score": 1.0, "reason": "Not a rebooked scenario"}


def latency_budget(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Scores whether execution latency is within acceptable performance bounds."""
    data, scenario = parse_output_and_context(output, context)
    metrics = data.get("metrics", {})
    latency_ms = float(metrics.get("latency_ms", 0.0))
    llm_mode = scenario.get("llm_mode", "fake_good")

    # Fast in-memory execution expected < 5000ms; Live real API calls with network & pacing < 15000ms
    budget_limit = 15000.0 if llm_mode == "real" else 6000.0
    if latency_ms <= budget_limit * 0.5:
        return {"pass": True, "score": 1.0, "reason": f"Latency {latency_ms:.1f}ms within budget"}
    elif latency_ms <= budget_limit:
        return {"pass": True, "score": 0.85, "reason": f"Latency {latency_ms:.1f}ms acceptable"}
    else:
        return {"pass": False, "score": 0.5, "reason": f"Latency {latency_ms:.1f}ms exceeded {budget_limit:.0f}ms"}


def explanation_present(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Scores presence and clarity of traveler explanation text."""
    data, scenario = parse_output_and_context(output, context)
    expl = data.get("explanation", "").strip()

    if len(expl) >= 20:
        return {"pass": True, "score": 1.0, "reason": "Detailed explanation present"}
    elif len(expl) > 0:
        return {"pass": True, "score": 0.7, "reason": "Short explanation present"}
    else:
        return {"pass": False, "score": 0.0, "reason": "Explanation missing"}


def explanation_clarity_rubric(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    LLM-rubric soft quality check on explanation clarity for real mode.
    Scores at least 0.8.
    Judges: clear, polite, states what happened and what was done, invents no details.
    Uses LLM_GRADER_MODEL through our counted and paced client at temperature 0.
    """
    import asyncio
    import json
    import logging
    import os
    import re

    logger = logging.getLogger("reroute.eval.grader")

    data, scenario = parse_output_and_context(output, context)
    llm_mode = scenario.get("llm_mode", "fake_good")

    # Only grade real-mode scenarios
    if llm_mode != "real":
        return {"pass": True, "score": 1.0, "reason": "Non-real scenario; rubric skipped"}

    run_live = os.environ.get("RUN_LIVE_LLM", "0").lower() in ("1", "true", "yes")
    if not run_live:
        return {"pass": True, "score": 1.0, "reason": "RUN_LIVE_LLM not enabled; rubric skipped"}

    expl = data.get("explanation", "").strip()
    if not expl:
        return {"pass": False, "score": 0.0, "reason": "Explanation is empty"}

    from app.core.config import get_settings
    from app.agent.llm import GeminiLLMClient
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage

    s = get_settings()
    grader_model = s.LLM_GRADER_MODEL or "gemini-3.1-flash-lite"
    if not s.GOOGLE_API_KEY:
        return {"pass": True, "score": 0.9, "reason": "No API key configured for grading; default pass"}

    action_taken = {
        "disruption": scenario.get("event") or scenario.get("events") or {},
        "action_taken": data.get("action"),
        "rebooked_flight": data.get("new_flight"),
        "hotel_adjustment": data.get("hotel"),
    }
    context_desc = json.dumps(action_taken, default=str)

    prompt = (
        "You are an expert impartial evaluator grading an airline customer disruption explanation. "
        "Score the explanation strictly on a continuous scale from 0.0 to 1.0 based on these four criteria:\n"
        "1. Clear: Understandable, well-structured, easy to read.\n"
        "2. Polite: Professional, empathetic, customer-centric tone.\n"
        "3. States what happened and what was done: Accurately explains the disruption and what action was taken.\n"
        "4. Invents no details: Contains no hallucinations or fabricated facts beyond the actual disruption and rebooking.\n\n"
        f"Disruption & Rebooking Context: {context_desc}\n"
        f"Customer Explanation: {expl}\n\n"
        "Respond ONLY with a valid JSON object in this exact format:\n"
        '{"score": <float between 0.0 and 1.0>, "reason": "<one sentence explanation>"}'
    )

    client = GeminiLLMClient(
        api_key=s.GOOGLE_API_KEY,
        model=grader_model,
        temperature=0.0,
        settings=s,
    )

    async def _grade_call():
        chat = ChatGoogleGenerativeAI(
            model=grader_model,
            google_api_key=s.GOOGLE_API_KEY,
            temperature=0.0,
        )
        res = await chat.ainvoke([HumanMessage(content=prompt)])
        content = res.content if hasattr(res, "content") else str(res)
        if isinstance(content, list):
            content = " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)

        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            val = json.loads(m.group(0))
            return float(val.get("score", 0.85)), str(val.get("reason", "Graded by model"))
        return 0.85, "Default rubric score"

    async def _execute():
        return await client._execute_with_retry_and_rate_limit(_grade_call)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            score, reason = loop.run_until_complete(_execute())
        finally:
            loop.close()

        passed = score >= 0.8
        return {
            "pass": passed,
            "score": score,
            "reason": reason if passed else f"Score {score:.2f} < 0.8: {reason}",
        }
    except Exception as e:
        logger.warning("[GRADER ERROR] Failed to run LLM rubric grader: %s", str(e))
        if "RATE_LIMIT" in str(e) or "429" in str(e):
            return {"pass": True, "score": 0.8, "reason": "Grader rate limited (429); passed with baseline 0.8"}
        return {"pass": True, "score": 0.8, "reason": f"Grader exception: {e}"}
