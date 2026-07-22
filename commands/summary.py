"""Roll up data/popularity.yml + data/freshness.yml into data/summary.yml.

The docs/ site needs headline numbers ("how many flagship apps ship an
end-of-life Chromium", "median exposure in days") on every page. Computing
those in Liquid would mean looping over ~2000 apps per page render, so they are
precomputed here and committed alongside the data they summarise.

Output:

    generated: '2026-07-22'
    current:  {electron_major, chromium_major}
    coverage: {apps, dead, tracked, detected, detected_pct}
    tiers:
      <tier>: {label, apps, detected, green, orange, red, eol, eol_pct,
               median_days_behind, median_majors_behind,
               median_cves_critical, median_cves_high, with_critical_cve}
    main:     same shape, flagship+popular+established combined
    overall:  same shape, every tracked app
    worst:    [{id, name, tier, electron, chromium, chromium_majors_behind,
                chromium_days_behind}]  – most-used apps furthest behind
    stalest_majors: [{major, apps}]     – most common Electron majors in use
"""

import collections
from datetime import datetime, timezone
from typing import Any

import click
import yaml

from commands import DATA_DIR, cli, load_apps

# Display order, and which of those are the tiers the site leads with.
TIER_ORDER = ["flagship", "popular", "established", "minimal", "unranked"]
MAIN_TIERS = ["flagship", "popular", "established"]
TIER_LABELS = {
    "flagship": "Flagship",
    "popular": "Popular",
    "established": "Established",
    "minimal": "Minimal",
    "unranked": "Unranked",
}

_WORST_COUNT = 15


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


@cli.command("summary")
def summary() -> None:
    """Roll popularity + freshness up into data/summary.yml for the site."""
    pop = yaml.safe_load((DATA_DIR / "popularity.yml").read_text()) or {}
    fresh = yaml.safe_load((DATA_DIR / "freshness.yml").read_text()) or {}
    tiers: dict[str, list[str]] = pop.get("tiers", {})
    scores: dict[str, dict] = pop.get("scores", {})

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

    per_tier = {
        name: {"label": TIER_LABELS[name], **_bucket(tiers.get(name, []), fresh)}
        for name in TIER_ORDER
    }
    main_ids = [i for name in MAIN_TIERS for i in tiers.get(name, [])]
    all_ids = [i for name in TIER_ORDER for i in tiers.get(name, [])]

    # Most-used apps furthest behind: sort by exposure, break ties by reach so
    # the list leads with apps people actually run.
    candidates = [
        (i, fresh[i])
        for i in main_ids
        if i in fresh and fresh[i].get("chromium_days_behind") is not None
    ]
    candidates.sort(
        key=lambda kv: (kv[1]["chromium_days_behind"], scores.get(kv[0], {}).get("reach", 0)),
        reverse=True,
    )
    worst = [
        {
            "id": app_id,
            "name": apps.get(app_id, {}).get("name") or app_id,
            "tier": scores.get(app_id, {}).get("tier", ""),
            "electron": row["electron"],
            "chromium": row["chromium"],
            "chromium_majors_behind": row["chromium_majors_behind"],
            "chromium_days_behind": row["chromium_days_behind"],
            "cves_critical": row.get("cves_critical"),
            "cves_high": row.get("cves_high"),
        }
        for app_id, row in candidates[:_WORST_COUNT]
    ]

    major_counts = collections.Counter(
        fresh[i]["major"] for i in main_ids if i in fresh
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
        "tier_order": TIER_ORDER,
        "main_tiers": MAIN_TIERS,
        "tiers": per_tier,
        "main": _bucket(main_ids, fresh),
        "overall": _bucket(all_ids, fresh),
        "worst": worst,
        "stalest_majors": stalest_majors,
    }

    path = DATA_DIR / "summary.yml"
    path.write_text(yaml.dump(out, default_flow_style=False, allow_unicode=True, sort_keys=False))
    m = out["main"]
    click.echo(
        f"Wrote {path}: {m['detected']}/{m['apps']} main-tier apps detected, "
        f"{m['eol_pct']}% end-of-life, median {m['median_days_behind']}d behind Chromium, "
        f"median {m['median_cves_critical']} critical / {m['median_cves_high']} high CVEs open "
        f"(current Electron {current_electron} / Chromium {current_chromium})"
    )
