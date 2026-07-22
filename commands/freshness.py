"""Compute per-app Electron freshness and write data/freshness.yml.

For every app with a detected ``electron`` version, record how stale that
Electron (and therefore Chromium) is, from three sources:

  * ``data/versions.txt``      – every stable Electron release + its date.
  * ``meta/eol-electron.json`` – endoflife.date support/EOL per major line
                                 (falls back to the live API if absent).
  * ``meta/electron-index.json`` – the Chromium build each Electron release
                                 bundles (see ``commands.electron_index``).

Output (consumed by the docs/ site; data/ is symlinked to docs/_data):

    <id>:
      electron: "37.6.0"
      major: 37
      age_label: "6mo ago"       # age of that exact release
      age_days: 187              # same, as a sortable number
      eol: true
      majors_behind: 6           # current stable major − this major
      latest_in_major: "37.10.3" # newest patch in the same major line
      patches_behind: 4          # newer stable releases in that major line
      status: red                # green=supported, orange=recently EOL, red=old
      chromium: "128.0.6613.186" # Chromium this Electron bundles
      chromium_major: 128
      chromium_majors_behind: 6
      chromium_days_behind: 412  # days since a newer Chromium major reached
                                 # stable Electron — the exposure window
      cves_critical: 155         # Chromium CVEs of each severity that were
      cves_high: 929             # fixed in a build newer than this one, i.e.
      cves_total: 1882           # still open in what this app ships

``chromium_days_behind`` is the headline number: from the day stable Electron
first shipped Chromium *major + 1*, every security fix that landed only in that
newer major is one this app cannot receive as a patch.

A version is coloured by how long its major has been end-of-life, so the
signal ages automatically as new Electron majors ship.
"""

import collections
import json
import pathlib
from datetime import datetime, timezone

import click
import yaml

from commands import DATA_DIR, cli, load_apps
from commands import cves as cve_data
from commands import electron_index
from commands.electron_index import parse_version as _parse_ver
from commands.report import _load_version_dates, _relative_age

_META = pathlib.Path("meta")
_EOL_META = _META / "eol-electron.json"
_EOL_URL = "https://endoflife.date/api/v1/products/electron/"

# A major EOL more recently than this many months is "orange"; older is "red".
_ORANGE_MONTHS = 6


def _load_eol_releases() -> list[dict]:
    if _EOL_META.exists():
        data = json.loads(_EOL_META.read_text())
    else:
        import urllib.request
        with urllib.request.urlopen(_EOL_URL) as resp:
            data = json.loads(resp.read())
    return data["result"]["releases"]


@cli.command("freshness")
def freshness() -> None:
    """Compute Electron staleness per app -> data/freshness.yml."""
    dates = _load_version_dates()  # {version: datetime}
    by_major: dict[int, list[tuple[int, ...]]] = collections.defaultdict(list)
    for v in dates:
        t = _parse_ver(v)
        if t:
            by_major[t[0]].append(t)

    eol_by_major: dict[int, dict] = {}
    for rec in _load_eol_releases():
        try:
            eol_by_major[int(rec["name"])] = rec
        except (ValueError, KeyError):
            continue
    current_major = max(eol_by_major) if eol_by_major else max(by_major, default=0)

    try:
        current_chromium = electron_index.current_chromium_major()
    except Exception as exc:  # index missing and the live fetch failed
        click.echo(f"warning: no Electron release index, skipping Chromium fields: {exc}", err=True)
        current_chromium = 0

    # Unpatched Chromium CVE counts, keyed by the exact bundled build. Absent
    # until `uv run main.py cves` has run at least once.
    cve_by_chromium = cve_data.load_by_chromium()
    if not cve_by_chromium:
        click.echo("warning: data/cves.yml missing; CVE counts omitted (run `main.py cves`)", err=True)

    now = datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for app in load_apps():
        raw = app.get("electron")
        if not raw:
            continue
        t = _parse_ver(str(raw))
        if not t:
            continue
        major = t[0]
        rec = eol_by_major.get(major)
        eol = bool(rec and rec.get("isEol"))

        latest_in_major = (rec or {}).get("latest", {}).get("name") if rec else None
        if not latest_in_major and by_major.get(major):
            latest_in_major = ".".join(map(str, max(by_major[major])))
        patches_behind = sum(1 for o in by_major.get(major, []) if o > t)

        if not eol:
            status = "green"
        else:
            months = None
            if rec and rec.get("eolFrom"):
                try:
                    d = datetime.fromisoformat(rec["eolFrom"]).replace(tzinfo=timezone.utc)
                    months = (now - d).days / 30
                except ValueError:
                    pass
            status = "orange" if months is not None and months < _ORANGE_MONTHS else "red"

        chromium = electron_index.chromium_for(str(raw)) if current_chromium else None
        chromium_major = (_parse_ver(chromium) or [None])[0] if chromium else None
        chromium_days_behind = None
        if chromium_major is not None:
            since = electron_index.superseded_on(chromium_major)
            chromium_days_behind = max((now - since).days, 0) if since else 0

        dt = dates.get(str(raw))
        out[app["id"]] = {
            "electron": str(raw),
            "major": major,
            "age_label": _relative_age(dt) if dt else None,
            "age_days": (now - dt).days if dt else None,
            "eol": eol,
            "majors_behind": max(current_major - major, 0),
            "latest_in_major": latest_in_major,
            "patches_behind": patches_behind,
            "status": status,
            "chromium": chromium,
            "chromium_major": chromium_major,
            "chromium_majors_behind": (
                max(current_chromium - chromium_major, 0) if chromium_major is not None else None
            ),
            "chromium_days_behind": chromium_days_behind,
            "cves_critical": (cve_by_chromium.get(chromium) or {}).get("critical") if chromium else None,
            "cves_high": (cve_by_chromium.get(chromium) or {}).get("high") if chromium else None,
            "cves_total": (cve_by_chromium.get(chromium) or {}).get("total") if chromium else None,
        }

    path = DATA_DIR / "freshness.yml"
    path.write_text(yaml.dump(out, default_flow_style=False, allow_unicode=True, sort_keys=False))
    c = collections.Counter(v["status"] for v in out.values())
    lags = sorted(v["chromium_days_behind"] for v in out.values() if v["chromium_days_behind"] is not None)
    median = lags[len(lags) // 2] if lags else 0
    click.echo(f"Wrote {path}: {len(out)} apps  "
               f"green={c['green']} orange={c['orange']} red={c['red']}  "
               f"(current Electron {current_major} / Chromium {current_chromium}, "
               f"median {median}d behind)")
