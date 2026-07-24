"""Write per-app popularity signals into each data/apps/<id>.yml.

Popularity is a property of an app, so it is stored on the app rather than in a
separate global file. Two independent, comparable signals feed it:

  * AUR votes  – ``NumVotes`` summed over the app's ``aur`` packages, from
                 ``meta/packages-meta-ext-v1.json`` (``additionalAUR`` variants
                 are deliberately excluded so a variant isn't double-counted).
  * Homebrew   – 365-day cask installs, from
                 ``meta/homebrew-cask-install-365d.json``, joined on ``homebrew``.

For every app this writes up to three fields (and removes them when they no
longer apply, so the command is deterministic and stale flags never linger):

  * ``homepage: true`` – the app clears the merged flagship+popular bar on
    either channel (exact ``votes >= 25`` or ``installs >= 7500``). These are the
    apps the site leads with in its "Featured" list. Decided on EXACT counts.
  * ``aur_votes``      – order-of-magnitude bucket of the vote count, written
    only when votes >= 1.
  * ``brew_installs``  – order-of-magnitude bucket of the install count, written
    only when installs >= 1.

The stored vote/install numbers are BUCKETED (``10 ** floor(log10(n))``: 1234 ->
1000, 25 -> 10, 7 -> 1) on purpose: the homepage decision reads the exact counts,
but the persisted signals round down to a power of ten so day-to-day count drift
doesn't churn per-app diffs. Re-running is idempotent.
"""

import json
import pathlib
from typing import Any

import click

from commands import cli, load_apps, write_app

_META = pathlib.Path("meta")
_AUR_META = _META / "packages-meta-ext-v1.json"
_BREW_META = _META / "homebrew-cask-install-365d.json"

# Merged flagship+popular bar: an app is featured on the homepage when it clears
# either channel. Checked against EXACT counts, not the stored buckets.
_HOMEPAGE_MIN_VOTES = 25
_HOMEPAGE_MIN_INSTALLS = 7500


def _load_aur() -> dict[str, dict[str, Any]]:
    if not _AUR_META.exists():
        return {}
    return {p["Name"]: p for p in json.loads(_AUR_META.read_text())}


def _load_brew() -> dict[str, int]:
    if not _BREW_META.exists():
        return {}
    data = json.loads(_BREW_META.read_text())
    return {it["cask"]: int(it["count"].replace(",", "")) for it in data.get("items", [])}


def _bucket(n: int) -> int:
    """Order-of-magnitude bucket, ``10 ** floor(log10(n))``: 1234 -> 1000,
    25 -> 10, 7 -> 1. Exact for positive integers (digit count avoids float
    rounding at powers of ten). Caller guarantees ``n >= 1``.
    """
    return 10 ** (len(str(n)) - 1)


@cli.command("popularity")
def popularity() -> None:
    """Write per-app popularity signals (homepage / aur_votes / brew_installs)."""
    aur = _load_aur()
    brew = _load_brew()
    if not aur:
        click.echo("warning: meta/packages-meta-ext-v1.json missing; AUR votes=0 (run `make all`)", err=True)
    if not brew:
        click.echo("warning: meta/homebrew-cask-install-365d.json missing; brew installs=0 (run `make all`)", err=True)

    featured = written = 0
    for app in load_apps():
        aur_pkgs = app.get("aur") or []  # may be False (opt-out flag)
        votes = sum(aur[n]["NumVotes"] for n in aur_pkgs if n in aur)
        installs = brew.get(app.get("homebrew"), 0) if app.get("homebrew") else 0

        before = (app.get("homepage"), app.get("aur_votes"), app.get("brew_installs"))

        if votes >= _HOMEPAGE_MIN_VOTES or installs >= _HOMEPAGE_MIN_INSTALLS:
            app["homepage"] = True
            featured += 1
        else:
            app.pop("homepage", None)

        if votes >= 1:
            app["aur_votes"] = _bucket(votes)
        else:
            app.pop("aur_votes", None)

        if installs >= 1:
            app["brew_installs"] = _bucket(installs)
        else:
            app.pop("brew_installs", None)

        after = (app.get("homepage"), app.get("aur_votes"), app.get("brew_installs"))
        if after != before:
            write_app(app)
            written += 1

    click.echo(f"popularity: {featured} apps flagged homepage: true; updated {written} app file(s)")
