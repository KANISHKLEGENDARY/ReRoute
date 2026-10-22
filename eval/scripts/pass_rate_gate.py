"""
CI Quality Gate Enforcer for ReRoute Disruption Concierge.

Exits non-zero if:
1. Overall scenario pass rate < 0.90 (90%)
2. ANY invariant assertion fails
3. Critical-severity scenario pass rate < 1.0 (100%)

Prints a per-category breakdown table with failing scenario IDs.
"""

from pathlib import Path
import sys

# Ensure eval/scripts is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from summarize_results import summarize_results


def check_gate(results_file: Path) -> int:
    summary = summarize_results(results_file)

    overall_rate = summary["overall_pass_rate"] / 100.0
    failing_invariants = summary["failing_invariants"]
    severity_stats = summary["severity_stats"]
    category_stats = summary["category_stats"]

    critical_stats = severity_stats.get("critical", {"total": 0, "passed": 0, "failed": 0})
    critical_rate = (
        (critical_stats["passed"] / critical_stats["total"])
        if critical_stats["total"] > 0
        else 1.0
    )

    gate_failed = False
    reasons = []

    if overall_rate < 0.90:
        gate_failed = True
        reasons.append(f"Overall pass rate {overall_rate * 100:.1f}% is below 90% threshold.")

    if len(failing_invariants) > 0:
        gate_failed = True
        total_inv_fails = sum(len(v) for v in failing_invariants.values())
        reasons.append(f"{total_inv_fails} invariant failure(s) across {len(failing_invariants)} invariant rule(s).")

    if critical_rate < 1.0:
        gate_failed = True
        reasons.append(
            f"Critical severity pass rate {critical_rate * 100:.1f}% is below 100% "
            f"(passed {critical_stats['passed']}/{critical_stats['total']}, failed: {critical_stats['failed']})."
        )

    # Print Per-Category Gate Table with failing IDs
    print("\n" + "=" * 80)
    print("                    PER-CATEGORY QUALITY GATE BREAKDOWN                       ")
    print("=" * 80)
    print(f"{'Category':<24} | {'Total':<6} | {'Passed':<6} | {'Failed':<6} | {'Pass Rate':<10} | {'Failing IDs'}")
    print("-" * 80)
    for cat, stats in sorted(category_stats.items()):
        rate = (stats["passed"] / stats["total"] * 100.0) if stats["total"] > 0 else 0.0
        f_ids = ", ".join(stats.get("failing_ids", [])) if stats.get("failing_ids") else "None"
        print(f"{cat:<24} | {stats['total']:<6} | {stats['passed']:<6} | {stats['failed']:<6} | {rate:>8.1f}% | {f_ids}")
    print("=" * 80)

    print("\n" + "=" * 80)
    print("                           CI EVALUATION GATE                         ")
    print("=" * 80)
    if gate_failed:
        print("[GATE STATUS: FAILED] Pipeline does NOT satisfy release quality criteria:")
        for r in reasons:
            print(f"  - {r}")
        print("=" * 80)
        return 1
    else:
        print("[GATE STATUS: PASSED] All criteria satisfied:")
        print(f"  - Overall Pass Rate: {overall_rate * 100:.1f}% (>= 90%)")
        print("  - Zero Invariant Failures")
        print(f"  - Critical Severity Pass Rate: {critical_rate * 100:.1f}% (== 100%)")
        print("=" * 80)
        return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/baseline.json")
    if not target.is_absolute():
        eval_root = Path(__file__).resolve().parents[1]
        target = eval_root / target
    code = check_gate(target)
    sys.exit(code)
