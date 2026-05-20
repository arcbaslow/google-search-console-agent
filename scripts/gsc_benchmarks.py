"""
Search Console / Web Vitals benchmark engine.

Two benchmark sources are bundled:

  1. Core Web Vitals thresholds from web.dev / Google's official Search
     Console documentation. These are the same numbers GSC uses to
     classify URLs as Good / Needs Improvement / Poor.

  2. Average organic CTR by SERP position. Composite from public studies
     (FirstPageSage 2024, Backlinko 2023, Sistrix 2024). Position-1 CTR
     varies sharply by SERP layout (featured snippet, AI overview, image
     pack), so treat these as directional.

CLI:
  python scripts/gsc_benchmarks.py --list
  python scripts/gsc_benchmarks.py --compare lcp_p75_ms 3200
  python scripts/gsc_benchmarks.py --ctr-curve
  python scripts/gsc_benchmarks.py --compare ctr_position 1 --observed 0.12
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


# CWV thresholds — official Google buckets. Lower is better. Numbers are
# the p75 of a 28-day window across real visits.
CWV_THRESHOLDS: dict[str, dict[str, float]] = {
    "lcp_p75_ms":  {"good": 2500,  "needs_improvement": 4000},  # Largest Contentful Paint
    "inp_p75_ms":  {"good": 200,   "needs_improvement": 500},   # Interaction to Next Paint
    "cls_p75":     {"good": 0.10,  "needs_improvement": 0.25},  # Cumulative Layout Shift
    "fcp_p75_ms":  {"good": 1800,  "needs_improvement": 3000},  # First Contentful Paint
    "ttfb_p75_ms": {"good": 800,   "needs_improvement": 1800},  # Time to First Byte
}

LIGHTHOUSE_SCORE_BANDS = {
    "good": 0.90,
    "needs_improvement": 0.50,
}

# Organic CTR by position, mobile + desktop combined, 2024 composite.
# Values are 0-1 fractions.
CTR_BY_POSITION: dict[int, float] = {
    1: 0.395,
    2: 0.187,
    3: 0.103,
    4: 0.075,
    5: 0.053,
    6: 0.041,
    7: 0.033,
    8: 0.029,
    9: 0.027,
    10: 0.025,
    11: 0.018,
    12: 0.014,
    13: 0.012,
    14: 0.010,
    15: 0.008,
    16: 0.007,
    17: 0.006,
    18: 0.006,
    19: 0.005,
    20: 0.005,
}


def list_metrics() -> dict[str, Any]:
    return {
        "core_web_vitals": list(CWV_THRESHOLDS.keys()),
        "lighthouse_scores": ["lh_performance_score", "lh_seo_score",
                              "lh_accessibility_score", "lh_best_practices_score"],
        "ctr_curve_positions": sorted(CTR_BY_POSITION.keys()),
    }


def compare_cwv(metric: str, value: float) -> dict[str, Any]:
    """Compare a CWV p75 value to Google's good / needs-improvement / poor bands."""
    if metric not in CWV_THRESHOLDS:
        return {"metric": metric, "value": value, "error": "unknown_cwv_metric"}
    bands = CWV_THRESHOLDS[metric]
    if value <= bands["good"]:
        verdict = "good"
    elif value <= bands["needs_improvement"]:
        verdict = "needs_improvement"
    else:
        verdict = "poor"
    return {
        "metric": metric,
        "value": value,
        "good_threshold": bands["good"],
        "needs_improvement_threshold": bands["needs_improvement"],
        "verdict": verdict,
    }


def compare_lighthouse(score: float | None) -> dict[str, Any]:
    """Map a 0-1 Lighthouse category score to good / needs-improvement / poor."""
    if score is None:
        return {"verdict": "unknown"}
    if score >= LIGHTHOUSE_SCORE_BANDS["good"]:
        verdict = "good"
    elif score >= LIGHTHOUSE_SCORE_BANDS["needs_improvement"]:
        verdict = "needs_improvement"
    else:
        verdict = "poor"
    return {"score": score, "verdict": verdict, "bands": LIGHTHOUSE_SCORE_BANDS}


def expected_ctr_for_position(position: float) -> float | None:
    """Linearly interpolate the expected CTR for a fractional average position
    (GSC reports positions as floats). Positions > 20 return ~0.4%."""
    if position is None:
        return None
    if position < 1:
        return CTR_BY_POSITION[1]
    if position >= 20:
        return 0.004
    lo = int(position)
    hi = lo + 1
    if hi not in CTR_BY_POSITION:
        return CTR_BY_POSITION.get(lo)
    frac = position - lo
    return CTR_BY_POSITION[lo] * (1 - frac) + CTR_BY_POSITION[hi] * frac


def compare_ctr(observed_ctr: float, average_position: float,
                volume_threshold: int = 50, impressions: int | None = None) -> dict[str, Any]:
    """Compare an observed CTR to the curve-derived expected CTR for the
    observed average position.

    Skips the verdict when impressions are below `volume_threshold` (small-
    sample noise produces spurious findings)."""
    expected = expected_ctr_for_position(average_position)
    if expected is None:
        return {"verdict": "unknown", "reason": "position out of range"}
    if impressions is not None and impressions < volume_threshold:
        return {
            "verdict": "low_volume",
            "observed_ctr": observed_ctr,
            "expected_ctr": expected,
            "position": average_position,
            "impressions": impressions,
        }
    delta = observed_ctr - expected
    ratio = (observed_ctr / expected) if expected else None
    if ratio is None:
        verdict = "unknown"
    elif ratio >= 1.20:
        verdict = "above_curve"
    elif ratio <= 0.65:
        verdict = "below_curve_critical"
    elif ratio <= 0.85:
        verdict = "below_curve"
    else:
        verdict = "on_curve"
    return {
        "verdict": verdict,
        "observed_ctr": observed_ctr,
        "expected_ctr": expected,
        "position": average_position,
        "delta_pct": round(delta * 100, 2),
        "ratio": round(ratio, 3) if ratio is not None else None,
    }


def enrich_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk a list of findings and attach a `benchmark` field where each
    finding declares a CWV `metric` + `metric_value`."""
    out = []
    for f in findings:
        ff = dict(f)
        metric = ff.get("metric")
        value = ff.get("metric_value")
        if metric in CWV_THRESHOLDS and value is not None:
            ff["benchmark"] = compare_cwv(metric, value)
        out.append(ff)
    return out


def main():
    parser = argparse.ArgumentParser(description="GSC / CWV benchmark engine")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--compare", nargs=2, metavar=("METRIC", "VALUE"))
    parser.add_argument("--ctr-curve", action="store_true")
    parser.add_argument("--ctr-for-position", type=float)
    parser.add_argument("--observed", type=float, help="Observed CTR (0-1) for --compare ctr_position")
    parser.add_argument("--impressions", type=int)
    args = parser.parse_args()

    if args.list:
        print(json.dumps(list_metrics(), indent=2))
        return 0
    if args.ctr_curve:
        print(json.dumps(CTR_BY_POSITION, indent=2))
        return 0
    if args.ctr_for_position is not None:
        print(json.dumps({"position": args.ctr_for_position,
                          "expected_ctr": expected_ctr_for_position(args.ctr_for_position)},
                         indent=2))
        return 0
    if args.compare:
        metric, raw = args.compare
        try:
            value = float(raw)
        except ValueError:
            print(json.dumps({"error": "value not numeric"}), file=sys.stderr)
            return 1
        if metric == "ctr_position":
            if args.observed is None:
                print(json.dumps({"error": "--observed required for ctr_position compare"}), file=sys.stderr)
                return 1
            print(json.dumps(compare_ctr(args.observed, value,
                                          impressions=args.impressions), indent=2))
            return 0
        print(json.dumps(compare_cwv(metric, value), indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
