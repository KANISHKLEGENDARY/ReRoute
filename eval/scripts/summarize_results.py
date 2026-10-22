"""
Evaluation Results Summarizer for ReRoute Concierge.

Parses promptfoo results JSON output and prints:
- Overall scenario pass rate and stats (excluding rate-limited scenarios)
- Pass rate per category (with failing scenario IDs)
- Pass rate per severity
- Execution latency percentiles (p50, p95)
- Total estimated cost in INR (and USD)
- Agent quality metrics (first proposal valid rate, revisions, escalation rate, agent steps)
- Detailed list of failing invariants with scenario IDs and offending values
- Rate-limited scenarios (if any).
"""

import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional


def calculate_percentile(values: List[float], percentile: float) -> float:
    """Calculates percentile (0-100) using nearest-rank method."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return float(d0 + d1)


def summarize_results(results_file: Path) -> Dict[str, Any]:
    if not results_file.exists():
        print(f"Error: Results file {results_file} does not exist.")
        sys.exit(1)

    with open(results_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Promptfoo JSON stores output in 'results'
    res_obj = data.get("results", data)
    test_results = res_obj.get("results", [])

    total_scenarios = len(test_results)
    passed_scenarios = 0
    failed_scenarios = 0
    rate_limited_scenarios: List[str] = []

    category_stats: Dict[str, Dict[str, Any]] = {}
    severity_stats: Dict[str, Dict[str, Any]] = {}
    failing_invariants: Dict[str, List[Dict[str, str]]] = {}

    latencies_ms: List[float] = []
    total_cost_usd = 0.0
    total_cost_inr = 0.0
    first_proposal_valid_count = 0
    total_revisions = 0
    escalated_count = 0
    total_agent_steps = 0
    total_tool_calls = 0
    rebooked_count = 0
    provider_stats: Dict[str, Dict[str, Any]] = {}

    for tr in test_results:
        # Extract scenario metadata
        vars_dict = tr.get("vars", {})
        scenario_id = (
            vars_dict.get("scenario_id")
            or vars_dict.get("scenario", {}).get("id")
            or "unknown"
        )
        category = (
            vars_dict.get("category")
            or vars_dict.get("scenario", {}).get("category")
            or "uncategorized"
        )
        severity = (
            vars_dict.get("severity")
            or vars_dict.get("scenario", {}).get("severity")
            or "normal"
        )

        if category not in category_stats:
            category_stats[category] = {"total": 0, "passed": 0, "failed": 0, "failing_ids": []}
        category_stats[category]["total"] += 1

        if severity not in severity_stats:
            severity_stats[severity] = {"total": 0, "passed": 0, "failed": 0}
        severity_stats[severity]["total"] += 1

        # Parse output payload from provider
        output_str = ""
        resp = tr.get("response")
        if isinstance(resp, dict):
            output_str = resp.get("output", "")
        elif isinstance(resp, str):
            output_str = resp

        output_data: Dict[str, Any] = {}
        if output_str:
            try:
                output_data = json.loads(output_str)
            except Exception:
                pass

        # Check for rate-limiting (429)
        metrics = output_data.get("metrics", {})
        err_msg = str(output_data.get("error", "")).lower()
        is_rate_limited = (
            metrics.get("llm_fallback_reason") == "rate_limit"
            or "rate_limit" in err_msg
            or "429" in err_msg
            or "resourceexhausted" in err_msg
        )
        if is_rate_limited:
            rate_limited_scenarios.append(scenario_id)

        # Telemetry aggregation
        latency = float(metrics.get("latency_ms", tr.get("latencyMs", 0.0)))
        if latency > 0:
            latencies_ms.append(latency)

        cost_usd = float(metrics.get("cost_usd", tr.get("cost", 0.0)))
        cost_inr = float(metrics.get("cost_inr", cost_usd * 86.5))
        total_cost_usd += cost_usd
        total_cost_inr += cost_inr

        if metrics.get("first_proposal_valid"):
            first_proposal_valid_count += 1
        total_revisions += int(metrics.get("revisions_used", 0))

        action = output_data.get("action", "")
        if action == "ESCALATED":
            escalated_count += 1
        elif action in ("REBOOKED", "REBOOKED_AND_HOTEL"):
            rebooked_count += 1

        steps = int(metrics.get("agent_steps", output_data.get("tool_calls", 1)))
        total_agent_steps += steps
        total_tool_calls += int(output_data.get("tool_calls", 0))

        # Check assertions
        success = tr.get("success", False)
        grading_result = tr.get("gradingResult", {})
        component_results = grading_result.get("componentResults", [])

        scenario_failed = not success
        if component_results:
            for cr in component_results:
                if not cr.get("pass", True):
                    scenario_failed = True
                    assertion_val = cr.get("assertion", {}).get("value", "")
                    inv_name = (
                        assertion_val.split(":")[-1]
                        if ":" in assertion_val
                        else assertion_val
                    )
                    reason = cr.get("reason", "Assertion failed")

                    if inv_name not in failing_invariants:
                        failing_invariants[inv_name] = []
                    failing_invariants[inv_name].append({
                        "scenario_id": scenario_id,
                        "category": category,
                        "reason": reason,
                    })

        if scenario_failed:
            failed_scenarios += 1
            category_stats[category]["failed"] += 1
            category_stats[category]["failing_ids"].append(scenario_id)
            severity_stats[severity]["failed"] += 1
        else:
            passed_scenarios += 1
            category_stats[category]["passed"] += 1
            severity_stats[severity]["passed"] += 1

        # Provider / Model tracking
        prov_obj = tr.get("provider", {})
        prov_label = prov_obj.get("label") or prov_obj.get("id") or "default"
        if prov_label not in provider_stats:
            provider_stats[prov_label] = {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "rate_limited": 0,
                "first_proposal_valid": 0,
                "revisions": 0,
                "escalated": 0,
                "agent_steps": 0,
                "tokens": 0,
                "cost_inr": 0.0,
                "latencies": [],
            }
        p_stat = provider_stats[prov_label]
        p_stat["total"] += 1
        if scenario_failed:
            p_stat["failed"] += 1
        else:
            p_stat["passed"] += 1
        if is_rate_limited:
            p_stat["rate_limited"] += 1
        if metrics.get("first_proposal_valid"):
            p_stat["first_proposal_valid"] += 1
        p_stat["revisions"] += int(metrics.get("revisions_used", 0))
        if action == "ESCALATED":
            p_stat["escalated"] += 1
        p_stat["agent_steps"] += steps
        token_usage = tr.get("tokenUsage", {})
        p_stat["tokens"] += int(token_usage.get("total", 0))
        p_stat["cost_inr"] += cost_inr
        if latency > 0:
            p_stat["latencies"].append(latency)

    # Pass rate excluding rate-limited runs
    effective_total = total_scenarios - len(rate_limited_scenarios)
    overall_pass_rate = (
        (passed_scenarios / effective_total * 100.0) if effective_total > 0 else 0.0
    )

    p50_latency = calculate_percentile(latencies_ms, 50.0)
    p95_latency = calculate_percentile(latencies_ms, 95.0)

    fpv_rate = (
        (first_proposal_valid_count / total_scenarios * 100.0)
        if total_scenarios > 0
        else 0.0
    )
    avg_revisions = (
        (total_revisions / total_scenarios) if total_scenarios > 0 else 0.0
    )
    escalation_rate = (
        (escalated_count / total_scenarios * 100.0) if total_scenarios > 0 else 0.0
    )
    avg_steps = (
        (total_agent_steps / total_scenarios) if total_scenarios > 0 else 0.0
    )

    # Print Summary Report
    print("=" * 80)
    print("                     REROUTE EVALUATION SUMMARY                       ")
    print("=" * 80)
    print(f"Total Scenarios Evaluated: {total_scenarios}")
    print(f"Passed:                    {passed_scenarios}")
    print(f"Failed:                    {failed_scenarios}")
    if rate_limited_scenarios:
        print(f"Rate-Limited (429):        {len(rate_limited_scenarios)} (excluded from pass rate)")
    print(f"Overall Pass Rate:         {overall_pass_rate:.1f}%")
    print("-" * 80)
    print(f"Latency Percentiles:       p50: {p50_latency:.1f}ms  |  p95: {p95_latency:.1f}ms")
    print(f"Total Estimated Cost:      INR {total_cost_inr:.2f} (${total_cost_usd:.4f} USD)")
    print("-" * 80)
    print("### Agent Quality Metrics:")
    print(f"  - First-Proposal Valid Rate: {fpv_rate:.1f}%")
    print(f"  - Average Revisions / Event: {avg_revisions:.2f}")
    print(f"  - Escalation Rate:          {escalation_rate:.1f}%")
    print(f"  - Average Agent Steps:       {avg_steps:.2f}")
    print(f"  - Total Tool Calls:          {total_tool_calls}")
    print("-" * 80)

    print("\n### Pass Rate per Category:")
    print(f"{'Category':<24} | {'Total':<6} | {'Passed':<6} | {'Failed':<6} | {'Pass Rate':<10} | {'Failing IDs'}")
    print("-" * 80)
    for cat, stats in sorted(category_stats.items()):
        rate = (stats["passed"] / stats["total"] * 100.0) if stats["total"] > 0 else 0.0
        f_ids = ", ".join(stats["failing_ids"]) if stats["failing_ids"] else "-"
        print(f"{cat:<24} | {stats['total']:<6} | {stats['passed']:<6} | {stats['failed']:<6} | {rate:>8.1f}% | {f_ids}")

    print("\n### Pass Rate per Severity:")
    print(f"{'Severity':<24} | {'Total':<6} | {'Passed':<6} | {'Failed':<6} | {'Pass Rate':<10}")
    print("-" * 64)
    for sev, stats in sorted(severity_stats.items()):
        rate = (stats["passed"] / stats["total"] * 100.0) if stats["total"] > 0 else 0.0
        print(f"{sev:<24} | {stats['total']:<6} | {stats['passed']:<6} | {stats['failed']:<6} | {rate:>8.1f}%")

    if rate_limited_scenarios:
        print("\n### Rate Limited (429) Scenarios:")
        for r_id in rate_limited_scenarios:
            print(f"  - {r_id}")

    print("\n### Failing Invariants Details:")
    if not failing_invariants:
        print("  All invariants passed (100% clean run).")
    else:
        for inv_name, failures in sorted(failing_invariants.items()):
            print(f"\n  [FAIL] Invariant: {inv_name} ({len(failures)} failure{'s' if len(failures) > 1 else ''})")
    if len(provider_stats) > 1 or any(k not in ("default", "") for k in provider_stats.keys()):
        print("\n### Model Comparison Breakdown:")
        print(f"{'Model':<24} | {'FPV Rate':<8} | {'Avg Rev':<7} | {'Esc Rate':<8} | {'Avg Steps':<9} | {'Accuracy':<8} | {'Tokens':<8} | {'Cost (INR)':<10} | {'p50 (ms)':<8} | {'Rate Lim'}")
        print("-" * 110)
        for prov, p_s in sorted(provider_stats.items()):
            p_tot = p_s["total"]
            p_pass = p_s["passed"]
            p_acc = (p_pass / p_tot * 100.0) if p_tot > 0 else 0.0
            p_fpv = (p_s["first_proposal_valid"] / p_tot * 100.0) if p_tot > 0 else 0.0
            p_rev = (p_s["revisions"] / p_tot) if p_tot > 0 else 0.0
            p_esc = (p_s["escalated"] / p_tot * 100.0) if p_tot > 0 else 0.0
            p_steps = (p_s["agent_steps"] / p_tot) if p_tot > 0 else 0.0
            p_p50 = calculate_percentile(p_s["latencies"], 50.0)
            print(f"{prov:<24} | {p_fpv:>7.1f}% | {p_rev:>7.2f} | {p_esc:>7.1f}% | {p_steps:>9.2f} | {p_acc:>7.1f}% | {p_s['tokens']:>8} | Rs.{p_s['cost_inr']:>7.2f} | {p_p50:>7.1f} | {p_s['rate_limited']:>8}")

    print("=" * 80)

    return {
        "total": total_scenarios,
        "passed": passed_scenarios,
        "failed": failed_scenarios,
        "rate_limited": len(rate_limited_scenarios),
        "overall_pass_rate": overall_pass_rate,
        "category_stats": category_stats,
        "severity_stats": severity_stats,
        "failing_invariants": failing_invariants,
        "p50_latency_ms": p50_latency,
        "p95_latency_ms": p95_latency,
        "total_cost_usd": total_cost_usd,
        "total_cost_inr": total_cost_inr,
        "first_proposal_valid_rate": fpv_rate,
        "avg_revisions": avg_revisions,
        "escalation_rate": escalation_rate,
        "avg_agent_steps": avg_steps,
    }


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/baseline.json")
    if not target.is_absolute():
        eval_root = Path(__file__).resolve().parents[1]
        target = eval_root / target
    summarize_results(target)
