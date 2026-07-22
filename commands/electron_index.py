"""Access to the Electron release index: version -> release date + bundled Chromium.

The index is ``meta/electron-index.json`` (built by ``make all`` from
https://artifacts.electronjs.org/headers/dist/index.json). Every entry carries
the exact Chromium build that Electron release shipped, which is what lets us
translate an app's Electron version into "how old is its Chromium".

``meta/`` is not committed, so callers running outside CI get a live fetch
fallback — same shape, one HTTP request, cached for the process lifetime.
"""

import functools
import json
import pathlib
from datetime import datetime, timezone
from typing import NamedTuple

_META = pathlib.Path("meta")
_INDEX = _META / "electron-index.json"
_INDEX_URL = "https://artifacts.electronjs.org/headers/dist/index.json"


class Release(NamedTuple):
    """One stable Electron release and the Chromium it bundles."""

    version: str
    parts: tuple[int, ...]  # (major, minor, patch)
    date: datetime
    chromium: str
    chromium_major: int


def parse_version(v: str) -> tuple[int, ...] | None:
    """Return (major, minor, patch) ints, or None if unparseable."""
    try:
        return tuple(int(p) for p in v.split("-", 1)[0].split(".")[:3])
    except ValueError:
        return None


def _load_raw() -> list[dict]:
    if _INDEX.exists():
        return json.loads(_INDEX.read_text())
    import urllib.request

    with urllib.request.urlopen(_INDEX_URL) as resp:
        return json.loads(resp.read())


def _release_date(rec: dict) -> datetime | None:
    raw = rec.get("fullDate") or rec.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@functools.cache
def stable_releases() -> list[Release]:
    """Every stable (non pre-release) Electron release, oldest version first."""
    out: list[Release] = []
    for rec in _load_raw():
        version = str(rec.get("version", ""))
        if not version or "-" in version:  # nightly / alpha / beta
            continue
        parts = parse_version(version)
        date = _release_date(rec)
        chromium = str(rec.get("chrome") or "")
        chromium_major = parse_version(chromium)
        if not parts or not date or not chromium_major:
            continue
        out.append(Release(version, parts, date, chromium, chromium_major[0]))
    out.sort(key=lambda r: r.parts)
    return out


@functools.cache
def chromium_by_version() -> dict[str, str]:
    """{electron version: bundled Chromium version} for stable releases."""
    return {r.version: r.chromium for r in stable_releases()}


@functools.cache
def current_chromium_major() -> int:
    """Newest Chromium major shipped by any stable Electron release."""
    releases = stable_releases()
    return max((r.chromium_major for r in releases), default=0)


@functools.cache
def _superseded_dates() -> dict[int, datetime]:
    """{chromium major: when stable Electron first shipped a *newer* major}.

    This is the moment an app pinned to that Chromium major started missing
    fixes it could no longer receive as patches — the start of its exposure
    window.
    """
    first_seen: dict[int, datetime] = {}
    for r in stable_releases():
        prev = first_seen.get(r.chromium_major)
        if prev is None or r.date < prev:
            first_seen[r.chromium_major] = r.date

    out: dict[int, datetime] = {}
    running: datetime | None = None
    for major in sorted(first_seen, reverse=True):
        if running is not None:
            out[major] = running
        seen = first_seen[major]
        running = seen if running is None or seen < running else running
    return out


def superseded_on(chromium_major: int) -> datetime | None:
    """Date a newer Chromium major first reached stable Electron, or None."""
    return _superseded_dates().get(chromium_major)


def chromium_for(electron_version: str) -> str | None:
    """Bundled Chromium for an Electron version.

    Falls back to the newest stable release at or below the requested version
    within the same major, so odd patch numbers (or versions the index has not
    picked up yet) still resolve to the right Chromium line.
    """
    exact = chromium_by_version().get(electron_version)
    if exact:
        return exact
    parts = parse_version(electron_version)
    if not parts:
        return None
    candidates = [r for r in stable_releases() if r.parts[0] == parts[0] and r.parts <= parts]
    if candidates:
        return max(candidates, key=lambda r: r.parts).chromium
    same_major = [r for r in stable_releases() if r.parts[0] == parts[0]]
    return min(same_major, key=lambda r: r.parts).chromium if same_major else None
