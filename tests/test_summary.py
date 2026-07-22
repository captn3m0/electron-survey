"""Tests for the headline-figure rollup that the docs/ site renders."""

from commands.summary import _bucket, _median, _pct

FRESH = {
    "a": {"status": "green", "eol": False, "chromium_days_behind": 10,
          "chromium_majors_behind": 1, "cves_critical": 0, "cves_high": 5},
    "b": {"status": "orange", "eol": True, "chromium_days_behind": 100,
          "chromium_majors_behind": 4, "cves_critical": 3, "cves_high": 40},
    "c": {"status": "red", "eol": True, "chromium_days_behind": 900,
          "chromium_majors_behind": 30, "cves_critical": 90, "cves_high": 400},
}


def test_median_of_empty_is_zero():
    assert _median([]) == 0


def test_pct_guards_against_zero_division():
    assert _pct(1, 0) == 0.0
    assert _pct(1, 3) == 33.3


def test_bucket_counts_statuses_and_eol():
    b = _bucket(["a", "b", "c"], FRESH)
    assert (b["green"], b["orange"], b["red"]) == (1, 1, 1)
    assert b["eol"] == 2
    assert b["eol_pct"] == 66.7


def test_bucket_percentages_are_relative_to_detected_apps():
    """Two of four apps are undetected; colour shares must ignore them."""
    b = _bucket(["a", "b", "unknown-1", "unknown-2"], FRESH)
    assert b["apps"] == 4
    assert b["detected"] == 2
    assert b["detected_pct"] == 50.0
    assert b["green_pct"] == 50.0


def test_bucket_reports_median_lag_and_cve_counts():
    b = _bucket(["a", "b", "c"], FRESH)
    assert b["median_days_behind"] == 100
    assert b["median_majors_behind"] == 4
    assert b["median_cves_critical"] == 3
    assert b["median_cves_high"] == 40
    assert b["with_critical_cve"] == 2


def test_bucket_of_nothing_is_all_zeroes():
    b = _bucket([], FRESH)
    assert b["apps"] == 0
    assert b["detected"] == 0
    assert b["median_days_behind"] == 0
    assert b["eol_pct"] == 0.0
