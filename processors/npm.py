"""Fetch Electron releases from the npm registry.

Writes data/versions.txt — one line per version, tab-separated:
    <version>\\t<ISO-8601 date>

Nightly and alpha builds are dropped; beta and rc are kept.
"""

import re
from datetime import datetime, timezone
from typing import Iterator

import requests

NPM_URL = "https://registry.npmjs.org/electron"
PRERELEASE = re.compile(r"nightly|alpha", re.IGNORECASE)

_SESSION = requests.Session()
_SESSION.headers["Accept"] = "application/json"


def stable_versions(data: dict) -> Iterator[tuple[str, datetime]]:
    """Yield (version, date) for every release except nightly/alpha, oldest first."""
    times: dict[str, str] = data.get("time", {})
    for version_str, ts in times.items():
        if version_str in ("created", "modified"):
            continue
        if PRERELEASE.search(version_str):
            continue
        try:
            date = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        yield version_str, date


def fetch() -> list[tuple[str, datetime]]:
    resp = _SESSION.get(NPM_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return sorted(stable_versions(data), key=lambda t: t[1])
