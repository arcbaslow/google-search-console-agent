"""Tests for the GSC / CWV benchmark engine."""

import pytest

import gsc_benchmarks


# ---------- CWV thresholds ----------

def test_lcp_good():
    out = gsc_benchmarks.compare_cwv("lcp_p75_ms", 1800)
    assert out["verdict"] == "good"


def test_lcp_needs_improvement():
    out = gsc_benchmarks.compare_cwv("lcp_p75_ms", 3200)
    assert out["verdict"] == "needs_improvement"


def test_lcp_poor():
    out = gsc_benchmarks.compare_cwv("lcp_p75_ms", 4500)
    assert out["verdict"] == "poor"


def test_inp_thresholds():
    assert gsc_benchmarks.compare_cwv("inp_p75_ms", 150)["verdict"] == "good"
    assert gsc_benchmarks.compare_cwv("inp_p75_ms", 300)["verdict"] == "needs_improvement"
    assert gsc_benchmarks.compare_cwv("inp_p75_ms", 800)["verdict"] == "poor"


def test_cls_thresholds():
    assert gsc_benchmarks.compare_cwv("cls_p75", 0.05)["verdict"] == "good"
    assert gsc_benchmarks.compare_cwv("cls_p75", 0.18)["verdict"] == "needs_improvement"
    assert gsc_benchmarks.compare_cwv("cls_p75", 0.30)["verdict"] == "poor"


def test_unknown_metric_returns_error():
    out = gsc_benchmarks.compare_cwv("not_a_metric", 1.0)
    assert out.get("error") == "unknown_cwv_metric"


# ---------- Lighthouse score ----------

def test_lighthouse_score_bands():
    assert gsc_benchmarks.compare_lighthouse(0.95)["verdict"] == "good"
    assert gsc_benchmarks.compare_lighthouse(0.70)["verdict"] == "needs_improvement"
    assert gsc_benchmarks.compare_lighthouse(0.40)["verdict"] == "poor"
    assert gsc_benchmarks.compare_lighthouse(None)["verdict"] == "unknown"


# ---------- CTR curve ----------

def test_ctr_curve_returns_first_position_for_zero():
    assert gsc_benchmarks.expected_ctr_for_position(1) == pytest.approx(0.395)


def test_ctr_curve_interpolates_between_positions():
    # 2.5 should land halfway between p=2 (0.187) and p=3 (0.103) ≈ 0.145
    assert gsc_benchmarks.expected_ctr_for_position(2.5) == pytest.approx(0.145, abs=0.005)


def test_ctr_curve_tail_for_far_positions():
    assert gsc_benchmarks.expected_ctr_for_position(50) == pytest.approx(0.004)


def test_ctr_above_curve():
    out = gsc_benchmarks.compare_ctr(observed_ctr=0.50, average_position=1, impressions=10000)
    assert out["verdict"] == "above_curve"


def test_ctr_on_curve():
    out = gsc_benchmarks.compare_ctr(observed_ctr=0.10, average_position=3, impressions=10000)
    # expected for position 3 is 0.103, observed 0.10 → ratio ~0.97 → on_curve
    assert out["verdict"] == "on_curve"


def test_ctr_below_curve():
    # position 1 expected 0.395, observed 0.30 → ratio ~0.76 → below_curve
    out = gsc_benchmarks.compare_ctr(observed_ctr=0.30, average_position=1, impressions=10000)
    assert out["verdict"] == "below_curve"


def test_ctr_below_curve_critical():
    # position 1 expected 0.395, observed 0.20 → ratio ~0.51 → below_curve_critical
    out = gsc_benchmarks.compare_ctr(observed_ctr=0.20, average_position=1, impressions=10000)
    assert out["verdict"] == "below_curve_critical"


def test_ctr_low_volume_returns_low_volume():
    out = gsc_benchmarks.compare_ctr(observed_ctr=0.20, average_position=1, impressions=10)
    assert out["verdict"] == "low_volume"


# ---------- enrich_findings ----------

def test_enrich_findings_attaches_cwv_benchmark():
    findings = [
        {"severity": "High", "metric": "lcp_p75_ms", "metric_value": 4500},
        {"severity": "Low", "title": "no metric"},
    ]
    out = gsc_benchmarks.enrich_findings(findings)
    assert out[0]["benchmark"]["verdict"] == "poor"
    assert "benchmark" not in out[1]


def test_enrich_findings_skips_unknown_metrics():
    findings = [{"severity": "High", "metric": "made_up", "metric_value": 1.0}]
    out = gsc_benchmarks.enrich_findings(findings)
    assert "benchmark" not in out[0]
