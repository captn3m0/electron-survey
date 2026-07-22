"""Tests for the Electron release index: version parsing and Chromium lookup."""

from datetime import datetime, timezone

import pytest

from commands import electron_index
from commands.electron_index import Release, parse_version


def _release(version, chromium, day):
    parts = parse_version(version)
    return Release(
        version=version,
        parts=parts,
        date=datetime(2020, 1, day, tzinfo=timezone.utc),
        chromium=chromium,
        chromium_major=parse_version(chromium)[0],
    )


# Two Electron majors per Chromium major, plus a patch release on an old line
# that ships after a newer major — the ordering trap `_superseded_dates` exists
# to handle.
FIXTURE = [
    _release("30.0.0", "124.0.1.1", 1),
    _release("30.1.0", "124.0.2.2", 9),
    _release("31.0.0", "126.0.1.1", 5),
    _release("32.0.0", "128.0.1.1", 7),
]


@pytest.fixture(autouse=True)
def _stub_index(monkeypatch):
    for fn in (
        electron_index.stable_releases,
        electron_index.chromium_by_version,
        electron_index.current_chromium_major,
        electron_index._superseded_dates,
    ):
        fn.cache_clear()
    monkeypatch.setattr(electron_index, "stable_releases", lambda: FIXTURE)
    yield
    electron_index._superseded_dates.cache_clear()


def test_parse_version_handles_prereleases():
    assert parse_version("43.1.1") == (43, 1, 1)
    assert parse_version("45.0.0-nightly.20260721") == (45, 0, 0)
    assert parse_version("not-a-version") is None


def test_current_chromium_major_is_the_newest_shipped():
    assert electron_index.current_chromium_major() == 128


def test_chromium_for_exact_version():
    assert electron_index.chromium_for("31.0.0") == "126.0.1.1"


def test_chromium_for_unknown_patch_falls_back_within_the_major():
    """An unlisted 30.0.5 resolves to the newest 30.x at or below it."""
    assert electron_index.chromium_for("30.0.5") == "124.0.1.1"
    assert electron_index.chromium_for("30.9.9") == "124.0.2.2"


def test_chromium_for_version_below_the_first_known_release_in_a_major():
    assert electron_index.chromium_for("30.0.0") == "124.0.1.1"


def test_chromium_for_unknown_major_is_none():
    assert electron_index.chromium_for("99.0.0") is None


def test_superseded_on_uses_the_earliest_newer_major():
    """Chromium 124 was superseded when 126 shipped on the 5th, not by the
    later 124 patch on the 9th."""
    assert electron_index.superseded_on(124) == datetime(2020, 1, 5, tzinfo=timezone.utc)
    assert electron_index.superseded_on(126) == datetime(2020, 1, 7, tzinfo=timezone.utc)


def test_newest_major_has_never_been_superseded():
    assert electron_index.superseded_on(128) is None
