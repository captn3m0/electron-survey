"""Tests for mapping NVD Chrome CVE ranges onto a bundled Chromium build."""

from commands.cves import _affects, _ranges, _severity, _version


def _cve(matches, metrics=None):
    return {
        "metrics": metrics or {},
        "configurations": [{"nodes": [{"cpeMatch": matches}]}],
    }


def _match(**kwargs):
    return {
        "vulnerable": True,
        "criteria": kwargs.pop("criteria", "cpe:2.3:a:google:chrome:*:*:*:*:*:*:*:*"),
        **kwargs,
    }


def test_version_parses_four_part_chrome_versions():
    assert _version("148.0.7778.280") == (148, 0, 7778, 280)
    assert _version("*") is None
    assert _version(None) is None


def test_open_ended_range_affects_everything_below_the_fix():
    ranges = _ranges(_cve([_match(versionEndExcluding="149.0.7827.53")]))
    assert _affects(ranges, _version("148.0.7778.280"))
    # The build the fix shipped in is not itself affected.
    assert not _affects(ranges, _version("149.0.7827.53"))
    assert not _affects(ranges, _version("150.0.7871.47"))


def test_bounded_range_is_not_charged_to_later_versions():
    """A bug that only ever affected Chrome 70-80 is not open in Chrome 120."""
    ranges = _ranges(
        _cve([_match(versionStartIncluding="70.0.0.0", versionEndExcluding="80.0.0.0")])
    )
    assert _affects(ranges, _version("75.0.1.2"))
    assert _affects(ranges, _version("70.0.0.0"))
    assert not _affects(ranges, _version("69.9.9.9"))
    assert not _affects(ranges, _version("120.0.0.0"))


def test_inclusive_upper_bound_is_honoured():
    ranges = _ranges(_cve([_match(versionEndIncluding="80.0.0.0")]))
    assert _affects(ranges, _version("80.0.0.0"))
    assert not _affects(ranges, _version("80.0.0.1"))


def test_exact_version_cpes_only_match_that_version():
    """Older advisories enumerate affected builds one CPE at a time."""
    ranges = _ranges(
        _cve([
            _match(criteria="cpe:2.3:a:google:chrome:0.2.149.29:*:*:*:*:*:*:*"),
            _match(criteria="cpe:2.3:a:google:chrome:0.2.149.30:*:*:*:*:*:*:*"),
        ])
    )
    assert _affects(ranges, _version("0.2.149.29"))
    assert not _affects(ranges, _version("0.2.149.31"))


def test_non_chrome_and_non_vulnerable_cpes_are_ignored():
    ranges = _ranges(
        _cve([
            {"vulnerable": True, "criteria": "cpe:2.3:o:google:android:*:*:*:*:*:*:*:*",
             "versionEndExcluding": "999.0.0.0"},
            {"vulnerable": False, "criteria": "cpe:2.3:a:google:chrome:*:*:*:*:*:*:*:*",
             "versionEndExcluding": "999.0.0.0"},
        ])
    )
    assert ranges == []
    assert not _affects(ranges, _version("100.0.0.0"))


def test_wildcard_cpe_without_bounds_contributes_no_range():
    assert _ranges(_cve([_match()])) == []


def test_severity_prefers_the_newest_scoring_system():
    cve = _cve([_match(versionEndExcluding="99.0.0.0")], metrics={
        "cvssMetricV2": [{"baseSeverity": "MEDIUM"}],
        "cvssMetricV31": [{"cvssData": {"baseSeverity": "HIGH"}}],
    })
    assert _severity(cve) == "high"


def test_severity_falls_back_to_cvss_v2():
    cve = _cve([], metrics={"cvssMetricV2": [{"baseSeverity": "MEDIUM"}]})
    assert _severity(cve) == "medium"


def test_severity_is_none_when_unscored():
    assert _severity(_cve([])) is None
