from typing import Any

import click

from commands import cli, load_apps


@cli.command("stats")
def stats() -> None:
    """Print processing statistics for data/apps/."""
    apps = load_apps()

    total = len(apps)
    dead = sum(1 for a in apps if a.get("dead"))
    alive = [a for a in apps if not a.get("dead")]
    with_version = sum(1 for a in alive if "electron" in a)
    remaining = [a for a in alive if "electron" not in a]
    def has_source(a: Any) -> bool:
        return bool(a.get("downloads") or a.get("download_urls") or a.get("homebrew") or a.get("chocolatey") or a.get("winget") or a.get("flathub"))

    with_downloads = sum(1 for a in remaining if has_source(a))
    with_aur = sum(1 for a in remaining if not has_source(a) and a.get("aur"))
    no_idea = sum(1 for a in remaining if not has_source(a) and not a.get("aur"))

    click.echo(f"total:          {total}")
    click.echo(f"dead:           {dead}")
    click.echo(f"with-version:   {with_version}")
    click.echo(f"with-downloads: {with_downloads}")
    click.echo(f"with-aur:       {with_aur}")
    click.echo(f"no-idea:        {no_idea}")


@cli.command("unresolved")
@click.option("--count", default=15, show_default=True, help="Number of entries to show.")
def unresolved(count: int) -> None:
    """List apps with no electron version, no downloads, and no AUR match."""
    apps = load_apps()

    def has_source(a: Any) -> bool:
        return bool(a.get("downloads") or a.get("download_urls") or a.get("homebrew") or a.get("chocolatey") or a.get("winget") or a.get("flathub"))

    no_idea = [
        a for a in apps
        if not a.get("dead")
        and "electron" not in a
        and not has_source(a)
        and not a.get("aur")
    ]

    for a in no_idea[:count]:
        parts = [a["id"]]
        if a.get("website"):
            parts.append(a["website"])
        if a.get("repository"):
            parts.append(f"repo:{a['repository']}")
        click.echo("  ".join(parts))

    click.echo(f"\n({len(no_idea)} total unresolved)")
