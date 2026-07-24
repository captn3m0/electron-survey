"""Roll per-app popularity + data/freshness.yml up into data/summary.yml.

The docs/ site needs headline numbers ("how many featured apps ship an
end-of-life Chromium", "median exposure in days") plus the ordered id lists its
two app tables render. Computing those in Liquid would mean looping over ~2000
apps per page render, so they are precomputed here. ``summary.yml`` is a
build-time artifact (regenerated at every publish, not committed), so its shape
is free to change.

Output:

    generated: '2026-07-22'
    current:  {electron_major, chromium_major}
    coverage: {apps, dead, tracked, detected, detected_pct}
    featured: {apps, detected, green/orange/red, eol, median_*, ..., ids}
              – stats + ordered ids for apps flagged ``homepage: true``
    overall:  {same shape, ids}   – stats + ordered ids for every non-dead app
    stalest_majors: [{major, apps}]   – most common Electron majors among featured

The ``ids`` lists are ordered by ``chromium_days_behind`` descending (most
exposed first); apps with no freshness row sort last.
"""

import collections
from datetime import datetime, timezone
from typing import Any

import click
import yaml

from commands import DATA_DIR, cli, load_apps


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _bucket(ids: list[str], fresh: dict[str, dict]) -> dict[str, Any]:
    """Aggregate freshness over a set of app ids."""
    rows = [fresh[i] for i in ids if i in fresh]
    counts = collections.Counter(r["status"] for r in rows)
    eol = sum(1 for r in rows if r["eol"])
    lags = [r["chromium_days_behind"] for r in rows if r.get("chromium_days_behind") is not None]
    majors = [r["chromium_majors_behind"] for r in rows if r.get("chromium_majors_behind") is not None]
    crit = [r["cves_critical"] for r in rows if r.get("cves_critical") is not None]
    high = [r["cves_high"] for r in rows if r.get("cves_high") is not None]
    return {
        "apps": len(ids),
        "detected": len(rows),
        "detected_pct": _pct(len(rows), len(ids)),
        "green": counts["green"],
        "orange": counts["orange"],
        "red": counts["red"],
        "green_pct": _pct(counts["green"], len(rows)),
        "orange_pct": _pct(counts["orange"], len(rows)),
        "red_pct": _pct(counts["red"], len(rows)),
        "eol": eol,
        "eol_pct": _pct(eol, len(rows)),
        "median_days_behind": _median(lags),
        "median_majors_behind": _median(majors),
        "median_cves_critical": _median(crit),
        "median_cves_high": _median(high),
        # Apps shipping a build with at least one unpatched critical Chromium CVE.
        "with_critical_cve": sum(1 for c in crit if c > 0),
        "with_critical_cve_pct": _pct(sum(1 for c in crit if c > 0), len(rows)),
    }


def _order_by_exposure(ids: list[str], fresh: dict[str, dict]) -> list[str]:
    """Ids ordered by chromium_days_behind descending; undetected apps last."""

    def key(app_id: str) -> int:
        row = fresh.get(app_id)
        if not row or row.get("chromium_days_behind") is None:
            return -1
        return row["chromium_days_behind"]

    return sorted(ids, key=key, reverse=True)


@cli.command("summary")
def summary() -> None:
    """Roll popularity + freshness up into data/summary.yml for the site."""
    fresh = yaml.safe_load((DATA_DIR / "freshness.yml").read_text()) or {}

    apps = {a["id"]: a for a in load_apps()}
    dead = sum(1 for a in apps.values() if a.get("dead"))

    current_chromium = max(
        (r["chromium_major"] for r in fresh.values() if r.get("chromium_major")), default=0
    )
    current_electron = max((r["major"] for r in fresh.values() if r.get("major")), default=0)
    for r in fresh.values():
        current_electron = max(current_electron, r["major"] + r.get("majors_behind", 0))
        if r.get("chromium_major"):
            current_chromium = max(
                current_chromium, r["chromium_major"] + (r.get("chromium_majors_behind") or 0)
            )

    featured_ids = [aid for aid, a in apps.items() if a.get("homepage")]
    all_ids = [aid for aid, a in apps.items() if not a.get("dead")]

    major_counts = collections.Counter(
        fresh[i]["major"] for i in featured_ids if i in fresh
    )
    stalest_majors = [
        {"major": m, "apps": n} for m, n in sorted(major_counts.items(), reverse=True)
    ]

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "current": {"electron_major": current_electron, "chromium_major": current_chromium},
        "coverage": {
            "apps": len(apps),
            "dead": dead,
            "tracked": len(apps) - dead,
            "detected": len(fresh),
            "detected_pct": _pct(len(fresh), len(apps) - dead),
        },
        "featured": {**_bucket(featured_ids, fresh), "ids": _order_by_exposure(featured_ids, fresh)},
        "overall": {**_bucket(all_ids, fresh), "ids": _order_by_exposure(all_ids, fresh)},
        "stalest_majors": stalest_majors,
    }

    path = DATA_DIR / "summary.yml"
    path.write_text(yaml.dump(out, default_flow_style=False, allow_unicode=True, sort_keys=False))
    f = out["featured"]
    click.echo(
        f"Wrote {path}: {f['detected']}/{f['apps']} featured apps detected, "
        f"{f['eol_pct']}% end-of-life, median {f['median_days_behind']}d behind Chromium, "
        f"median {f['median_cves_critical']} critical / {f['median_cves_high']} high CVEs open "
        f"(current Electron {current_electron} / Chromium {current_chromium})"
    )
