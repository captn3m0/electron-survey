"""Compute per-app Electron freshness and write data/freshness.yml.

For every app with a detected ``electron`` version, record how stale that
Electron (and therefore Chromium) is, from two sources:

  * ``data/versions.txt``     – every stable Electron release + its date.
  * ``meta/eol-electron.json`` – endoflife.date support/EOL per major line
                                 (falls back to the live API if absent).

Output (consumed by the docs/ site; data/ is symlinked to docs/_data):

    <id>:
      electron: "37.6.0"
      major: 37
      age_label: "6mo ago"       # age of that exact release
      eol: true
      majors_behind: 6           # current stable major − this major
      latest_in_major: "37.10.3" # newest patch in the same major line
      patches_behind: 4          # newer stable releases in that major line
      status: red                # green=supported, orange=recently EOL, red=old

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
from commands.report import _load_version_dates, _relative_age

_META = pathlib.Path("meta")
_EOL_META = _META / "eol-electron.json"
_EOL_URL = "https://endoflife.date/api/v1/products/electron/"

# A major EOL more recently than this many months is "orange"; older is "red".
_ORANGE_MONTHS = 6


def _parse_ver(v: str) -> tuple[int, ...] | None:
    """Return (major, minor, patch) ints, or None if unparseable."""
    try:
        return tuple(int(p) for p in v.split("-", 1)[0].split(".")[:3])
    except ValueError:
        return None


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

        dt = dates.get(str(raw))
        out[app["id"]] = {
            "electron": str(raw),
            "major": major,
            "age_label": _relative_age(dt) if dt else None,
            "eol": eol,
            "majors_behind": max(current_major - major, 0),
            "latest_in_major": latest_in_major,
            "patches_behind": patches_behind,
            "status": status,
        }

    path = DATA_DIR / "freshness.yml"
    path.write_text(yaml.dump(out, default_flow_style=False, allow_unicode=True, sort_keys=False))
    c = collections.Counter(v["status"] for v in out.values())
    click.echo(f"Wrote {path}: {len(out)} apps  "
               f"green={c['green']} orange={c['orange']} red={c['red']}  (current major {current_major})")
