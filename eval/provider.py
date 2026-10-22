"""
Custom Promptfoo Python Provider for ReRoute Travel-Disruption Concierge.

Signature: `call_api(prompt, options, context) -> dict`
Connects Promptfoo runner to `backend.app.eval_adapter.run_scenario`.
Enforces:
- Imports backend package correctly regardless of invocation directory
- Executes pure-function pipeline via in-memory adapter
- Returns JSON output string along with token and cost tracking
- No external network, Redis, or database calls
"""

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict

# Ensure backend directory is in sys.path
eval_dir = Path(__file__).resolve().parent
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

from app.eval_adapter import run_scenario


def call_api(prompt: Any, options: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Promptfoo custom Python provider entrypoint.
    
    Parameters:
    - prompt: Rendered prompt string or list
    - options: Provider options and config dict
    - context: Test case context dictionary containing `vars`
    
    Returns:
    - Dict with "output" (JSON string), "tokenUsage", and "cost"
    """
    vars_dict = context.get("vars", {}) if context else {}

    # Extract scenario dictionary
    scenario = vars_dict.get("scenario")
    if not scenario:
        # If vars itself holds the scenario fields
        scenario = vars_dict

    # If scenario is a filepath or string, attempt to load it
    if isinstance(scenario, str):
        try:
            scenario = json.loads(scenario)
        except Exception:
            try:
                import yaml
                p = Path(scenario)
                if not p.is_absolute():
                    p = eval_dir / p
                if p.exists():
                    with open(p, "r", encoding="utf-8") as f:
                        scenario = yaml.safe_load(f)
            except Exception as e:
                return {
                    "output": json.dumps({"error": f"Failed to parse scenario string: {e}"}),
                    "tokenUsage": {"total": 0, "prompt": 0, "completion": 0},
                    "cost": 0.0,
                }

    # Extract model override and env vars from provider options
    if isinstance(scenario, dict):
        config_dict = options.get("config", {}) if options else {}
        model_override = config_dict.get("model") or options.get("model")
        if model_override:
            scenario["model"] = model_override
        env_dict = config_dict.get("env", {})
        if isinstance(env_dict, dict):
            for k, v in env_dict.items():
                os.environ[k] = str(v)

    seed = int(scenario.get("seed", 0)) if isinstance(scenario, dict) else 0

    try:
        # Run async scenario synchronously inside event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(run_scenario(scenario, seed=seed))
        finally:
            loop.close()

        metrics = result.get("metrics", {})
        tokens_in = int(metrics.get("tokens_in", 0))
        tokens_out = int(metrics.get("tokens_out", 0))
        cost_usd = float(metrics.get("cost_usd", 0.0))

        return {
            "output": json.dumps(result, default=str),
            "tokenUsage": {
                "total": tokens_in + tokens_out,
                "prompt": tokens_in,
                "completion": tokens_out,
            },
            "cost": cost_usd,
        }

    except Exception as e:
        error_payload = {
            "scenario_id": scenario.get("id", "unknown"),
            "action": "ERROR",
            "policy_verdict": "ESCALATE",
            "new_flight": None,
            "hotel": None,
            "fare_delta": 0.0,
            "explanation": f"Provider execution failed: {str(e)}",
            "notification": {},
            "trace_stages": [],
            "tool_calls": 0,
            "metrics": {},
            "error": str(e),
        }
        return {
            "output": json.dumps(error_payload),
            "tokenUsage": {"total": 0, "prompt": 0, "completion": 0},
            "cost": 0.0,
        }
