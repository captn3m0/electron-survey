"""Compute a popularity tier for every app and write data/popularity.yml.

Popularity is derived from two independent, comparable signals:

  * AUR votes  – ``NumVotes`` summed over the app's ``aur`` packages, from
                 ``meta/packages-meta-ext-v1.json`` (``additionalAUR`` variants
                 are deliberately excluded so a variant isn't double-counted).
  * Homebrew   – 365-day cask installs, from
                 ``meta/homebrew-cask-install-365d.json``, joined on ``homebrew``.

Thresholds are calibrated so the two channels agree on tier boundaries
(≈ p95 / p90 / p68 of the apps that carry each signal):

    flagship     AUR ≥ 75   or  brew ≥ 40000
    popular      AUR ≥ 25   or  brew ≥ 7500
    established  AUR ≥ 5    or  brew ≥ 1000
    minimal      AUR ≥ 1    or  brew ≥ 1
    unranked     neither signal present

Output feeds the Jekyll site in ``docs/`` (``data/`` is symlinked to
``docs/_data``), so it stays plain, Liquid-friendly YAML:

    tiers:   {flagship: [id, ...], popular: [...], ...}   # each sorted by reach
    scores:  {<id>: {tier, aur_votes, aur_popularity, brew_installs, reach, rank}}

``rank`` is a 1-based position across every app that carries a signal at all,
ordered by ``reach`` — "the Nth most-used app we track".
"""

import json
import math
import pathlib
from typing import Any

import click
import yaml

from commands import DATA_DIR, cli, load_apps

_META = pathlib.Path("meta")
_AUR_META = _META / "packages-meta-ext-v1.json"
_BREW_META = _META / "homebrew-cask-install-365d.json"

# (tier, min_aur_votes, min_brew_installs); first match wins, checked high→low.
_TIERS = [
    ("flagship", 75, 40000),
    ("popular", 25, 7500),
    ("established", 5, 1000),
    ("minimal", 1, 1),
]
_TIER_ORDER = [t[0] for t in _TIERS] + ["unranked"]

# Dataset high-water marks, used to normalise each channel to 0..1 for sorting.
_AUR_MAX = 1738
_BREW_MAX = 590545


def _load_aur() -> dict[str, dict[str, Any]]:
    if not _AUR_META.exists():
        return {}
    return {p["Name"]: p for p in json.loads(_AUR_META.read_text())}


def _load_brew() -> dict[str, int]:
    if not _BREW_META.exists():
        return {}
    data = json.loads(_BREW_META.read_text())
    return {it["cask"]: int(it["count"].replace(",", "")) for it in data.get("items", [])}


def _tier(votes: int, installs: int) -> str:
    for name, min_votes, min_installs in _TIERS:
        if votes >= min_votes or installs >= min_installs:
            return name
    return "unranked"


def _reach(votes: int, installs: int) -> float:
    """Best single normalised signal (0..1) — used only to order listings."""
    a = math.log1p(votes) / math.log1p(_AUR_MAX) if votes else 0.0
    b = math.log1p(installs) / math.log1p(_BREW_MAX) if installs else 0.0
    return round(max(a, b), 4)


@cli.command("popularity")
def popularity() -> None:
    """Compute popularity tiers and write data/popularity.yml."""
    aur = _load_aur()
    brew = _load_brew()
    if not aur:
        click.echo("warning: meta/packages-meta-ext-v1.json missing; AUR votes=0 (run `make all`)", err=True)
    if not brew:
        click.echo("warning: meta/homebrew-cask-install-365d.json missing; brew installs=0 (run `make all`)", err=True)

    scores: dict[str, dict[str, Any]] = {}
    tiers: dict[str, list[str]] = {name: [] for name in _TIER_ORDER}

    for app in load_apps():
        app_id = app["id"]
        aur_pkgs = app.get("aur") or []  # may be False (opt-out flag)
        votes = sum(aur[n]["NumVotes"] for n in aur_pkgs if n in aur)
        pop = round(sum(aur[n]["Popularity"] for n in aur_pkgs if n in aur), 4)
        installs = brew.get(app.get("homebrew"), 0) if app.get("homebrew") else 0
        tier = _tier(votes, installs)
        scores[app_id] = {
            "tier": tier,
            "aur_votes": votes,
            "aur_popularity": pop,
            "brew_installs": installs,
            "reach": _reach(votes, installs),
        }
        tiers[tier].append(app_id)

    for ids in tiers.values():
        ids.sort(key=lambda i: scores[i]["reach"], reverse=True)

    # Overall "Nth most-used app we track", across every app with a signal.
    ranked = sorted(
        (i for i, s in scores.items() if s["reach"] > 0),
        key=lambda i: scores[i]["reach"],
        reverse=True,
    )
    for position, app_id in enumerate(ranked, start=1):
        scores[app_id]["rank"] = position

    path = DATA_DIR / "popularity.yml"
    path.write_text(
        yaml.dump({"tiers": tiers, "scores": scores},
                  default_flow_style=False, allow_unicode=True, sort_keys=False)
    )
    counts = "  ".join(f"{n}={len(tiers[n])}" for n in _TIER_ORDER)
    click.echo(f"Wrote {path}: {counts}")
