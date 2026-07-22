"""Count the Chromium CVEs left unpatched in each Electron release.

An Electron version pins one exact Chromium build. Every Chromium CVE that was
fixed in a *later* build is therefore still open in that Electron — this command
turns that into a number.

Source is the NVD CVE API 2.0, queried for everything matching
``cpe:2.3:a:google:chrome``. The raw response is cached in
``meta/chrome-cves.json`` (a few MB, not committed); the derived counts land in
``data/cves.yml``, which *is* committed so the site and any other consumer can
use them without hitting NVD.

    uv run main.py cves            # use the cache if present, else fetch
    uv run main.py cves --refresh  # always re-fetch from NVD

Output:

    generated: '2026-07-22'
    total_cves: 5452
    by_chromium:                       # exact Chromium build -> what is open in it
      148.0.7778.280: {critical: 1, high: 12, medium: 30, low: 2, total: 45}
    by_chromium_major:                 # same, for the newest build in each major
      148: {...}
    by_electron:                       # every stable Electron release
      42.6.0: {chromium: 148.0.7778.280, critical: 1, high: 12, ...}

A CVE counts against version V when V falls inside one of the CVE's affected
ranges — honouring both ends of the range, so a CVE that only ever affected
Chrome 70–80 is not charged to Chrome 120.
"""

import json
import pathlib
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

import click
import yaml

from commands import DATA_DIR, cli, electron_index

_META = pathlib.Path("meta")
_CACHE = _META / "chrome-cves.json"

_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_CPE = "cpe:2.3:a:google:chrome"
_PAGE = 2000
# NVD allows 5 requests per rolling 30s without an API key. Stay well inside it.
_DELAY_SECONDS = 7.0

_SEVERITIES = ["critical", "high", "medium", "low"]


def _version(v: str | None) -> tuple[int, ...] | None:
    """Chrome versions are dotted numbers; compare them as int tuples."""
    if not v:
        return None
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError:
        return None


def _fetch_all() -> dict[str, Any]:
    """Page through the NVD API and return one merged response document."""
    vulns: list[dict] = []
    start = 0
    total = None
    while True:
        url = f"{_API}?virtualMatchString={_CPE}&resultsPerPage={_PAGE}&startIndex={start}"
        with urllib.request.urlopen(url, timeout=180) as resp:
            page = json.loads(resp.read())
        vulns.extend(page.get("vulnerabilities", []))
        total = page.get("totalResults", 0)
        click.echo(f"  fetched {len(vulns)}/{total}")
        start += _PAGE
        if start >= total:
            break
        time.sleep(_DELAY_SECONDS)
    return {"totalResults": total, "vulnerabilities": vulns}


def _severity(cve: dict) -> str | None:
    """Best available CVSS base severity, newest scoring system first."""
    metrics = cve.get("metrics") or {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30"):
        for entry in metrics.get(key) or []:
            sev = (entry.get("cvssData") or {}).get("baseSeverity")
            if sev:
                return sev.lower()
    for entry in metrics.get("cvssMetricV2") or []:
        sev = entry.get("baseSeverity")
        if sev:
            return sev.lower()
    return None


def _ranges(cve: dict) -> list[tuple]:
    """Affected Chrome version ranges as (lo, lo_inclusive, hi, hi_inclusive).

    An exact-version CPE (older advisories list them one by one) becomes a
    degenerate range covering just that version.
    """
    out: list[tuple] = []
    for config in cve.get("configurations") or []:
        for node in config.get("nodes") or []:
            for match in node.get("cpeMatch") or []:
                if not match.get("vulnerable"):
                    continue
                criteria = match.get("criteria", "")
                if not criteria.startswith(_CPE + ":"):
                    continue

                lo = _version(match.get("versionStartIncluding"))
                lo_inc = lo is not None
                if lo is None:
                    lo = _version(match.get("versionStartExcluding"))
                hi = _version(match.get("versionEndIncluding"))
                hi_inc = hi is not None
                if hi is None:
                    hi = _version(match.get("versionEndExcluding"))

                if lo is None and hi is None:
                    exact = _version(criteria.split(":")[5])
                    if exact is None:
                        continue
                    out.append((exact, True, exact, True))
                else:
                    out.append((lo, lo_inc, hi, hi_inc))
    return out


def _affects(ranges: Iterable[tuple], v: tuple[int, ...]) -> bool:
    for lo, lo_inc, hi, hi_inc in ranges:
        if lo is not None:
            if lo_inc and v < lo:
                continue
            if not lo_inc and v <= lo:
                continue
        if hi is not None:
            if hi_inc and v > hi:
                continue
            if not hi_inc and v >= hi:
                continue
        return True
    return False


def _empty_counts() -> dict[str, int]:
    return {s: 0 for s in _SEVERITIES} | {"total": 0}


@cli.command("cves")
@click.option("--refresh", is_flag=True, help="Re-fetch from NVD even if the cache exists.")
def cves(refresh: bool) -> None:
    """Count unpatched Chromium CVEs per Electron version -> data/cves.yml."""
    if refresh or not _CACHE.exists():
        click.echo(f"Fetching Chrome CVEs from NVD (cache: {_CACHE})…")
        raw = _fetch_all()
        _META.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(raw))
    else:
        raw = json.loads(_CACHE.read_text())
        click.echo(f"Using cached {_CACHE} ({raw.get('totalResults')} CVEs)")

    # (severity, ranges) per CVE, skipping ones with no usable Chrome range.
    parsed: list[tuple[str, list[tuple]]] = []
    unscored = 0
    for item in raw.get("vulnerabilities", []):
        cve = item.get("cve") or {}
        ranges = _ranges(cve)
        if not ranges:
            continue
        sev = _severity(cve)
        if sev is None:
            unscored += 1
            continue
        parsed.append((sev, ranges))

    releases = electron_index.stable_releases()
    chromium_versions = sorted({r.chromium for r in releases}, key=lambda v: _version(v) or ())

    by_chromium: dict[str, dict[str, int]] = {}
    for version in chromium_versions:
        parts = _version(version)
        if parts is None:
            continue
        counts = _empty_counts()
        for sev, ranges in parsed:
            if _affects(ranges, parts):
                if sev in counts:
                    counts[sev] += 1
                counts["total"] += 1
        by_chromium[version] = counts

    # Roll up to majors using the newest build seen in each major, which is the
    # most favourable reading — a real app on an older build is never better off.
    by_major: dict[int, dict[str, int]] = {}
    newest_in_major: dict[int, tuple[int, ...]] = {}
    for version, counts in by_chromium.items():
        parts = _version(version)
        major = parts[0]
        if major not in newest_in_major or parts > newest_in_major[major]:
            newest_in_major[major] = parts
            by_major[major] = counts

    by_electron: dict[str, dict[str, Any]] = {}
    for release in releases:
        counts = by_chromium.get(release.chromium)
        if counts is None:
            continue
        by_electron[release.version] = {"chromium": release.chromium, **counts}

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "NVD CVE API 2.0, cpe:2.3:a:google:chrome",
        "total_cves": raw.get("totalResults", 0),
        "scored_cves": len(parsed),
        "unscored_cves": unscored,
        "by_chromium_major": dict(sorted(by_major.items())),
        "by_chromium": by_chromium,
        "by_electron": by_electron,
    }

    path = DATA_DIR / "cves.yml"
    path.write_text(yaml.dump(out, default_flow_style=False, allow_unicode=True, sort_keys=False))
    newest = max(by_major) if by_major else 0
    click.echo(
        f"Wrote {path}: {len(parsed)} scored CVEs mapped onto "
        f"{len(by_chromium)} Chromium builds / {len(by_electron)} Electron releases "
        f"(Chromium {newest} still open: {by_major.get(newest, {}).get('critical', 0)} critical, "
        f"{by_major.get(newest, {}).get('high', 0)} high)"
    )


def _load(key: str) -> dict[str, dict[str, int]]:
    path = DATA_DIR / "cves.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data.get(key) or {}


def load_by_electron() -> dict[str, dict[str, int]]:
    """{Electron version: severity counts} from data/cves.yml, or {} if absent."""
    return _load("by_electron")


def load_by_chromium() -> dict[str, dict[str, int]]:
    """{Chromium build: severity counts} from data/cves.yml, or {} if absent."""
    return _load("by_chromium")
