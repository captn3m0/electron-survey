"""Find and remove duplicate app entries that point at the same repository.

Manually-curated entries sometimes duplicate an app already present in the
upstream electron-apps registry (same ``repository`` under a different id).
Both then flow through every processor and show up twice in the report.

This command groups alive entries by normalised repository URL and, for each
group with more than one member, keeps a single canonical entry (preferring
the upstream one, then the richest) and removes the redundant *non-upstream*
duplicates — after copying over any curated keys the keeper was missing.

Entries that only exist in upstream are never deleted (``extract-apps`` would
just recreate them); groups where every member is upstream are left untouched
and reported, since that is an upstream data issue.

    uv run main.py dedupe            # dry-run: show what would change
    uv run main.py dedupe --apply    # actually remove duplicates
"""

import collections
from typing import Any

import click

from commands import APPS_DATA_DIR, APPS_DIR, cli, load_apps, write_app

# Keys worth carrying onto the keeper from a removed duplicate when the keeper
# lacks them. Curated keys are always safe to preserve; the version-bearing
# processor keys are only filled if missing, so removing a duplicate that
# happens to carry a detected version never regresses coverage (both entries
# point at the same repo, so the value is equivalent anyway).
_MERGE_KEYS = (
    "name", "website", "repository", "packages", "aur", "homebrew", "download_urls",
    "electron", "method", "latest", "src", "downloads",
)


def _norm_repo(entry: dict[str, Any]) -> str:
    repo = (entry.get("repository") or "").strip().lower().rstrip("/")
    return repo.removesuffix(".git")


def _upstream_ids() -> set[str]:
    if not APPS_DIR.exists():
        return set()
    return {p.name for p in APPS_DIR.iterdir() if p.is_dir()}


def _pick_keeper(members: list[dict[str, Any]], upstream: set[str]) -> dict[str, Any]:
    """Choose the entry to keep from a duplicate group.

    Prefers an upstream entry, then the one with the most keys, then one that
    already has a detected version, then the shorter (more canonical) id.
    """
    return max(
        members,
        key=lambda m: (m["id"] in upstream, len(m), "electron" in m, -len(m["id"])),
    )


@cli.command("dedupe")
@click.option("--apply", "do_apply", is_flag=True, help="Delete redundant entries (default: dry-run).")
def dedupe(do_apply: bool) -> None:
    """Report or remove entries that duplicate another entry's repository."""
    upstream = _upstream_ids()

    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for entry in load_apps():
        if entry.get("dead"):
            continue
        repo = _norm_repo(entry)
        if repo:
            groups[repo].append(entry)

    removed = 0
    skipped_upstream = 0
    for repo, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        if all(m["id"] in upstream for m in members):
            skipped_upstream += 1
            click.echo(f"skip (all upstream) {repo}: {[m['id'] for m in members]}")
            continue

        keeper = _pick_keeper(members, upstream)

        for m in members:
            if m is keeper or m["id"] in upstream:
                continue
            for key in _MERGE_KEYS:
                if key in m and key not in keeper:
                    keeper[key] = m[key]
            verb = "REMOVE" if do_apply else "would remove"
            click.echo(f"{verb} {m['id']}  (dup of {keeper['id']} @ {repo})")
            removed += 1
            if do_apply:
                (APPS_DATA_DIR / f"{m['id']}.yml").unlink(missing_ok=True)

        if do_apply:
            write_app(keeper)

    tail = "Removed" if do_apply else "Would remove"
    click.echo(f"\n{tail} {removed} duplicate(s); {skipped_upstream} upstream-only group(s) left as-is.")
