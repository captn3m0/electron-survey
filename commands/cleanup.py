import hashlib
import pathlib

import click

from commands import cli, load_apps


@cli.command("cleanup")
def cleanup() -> None:
    """Remove zip files in zips/ that are no longer referenced by data/apps/."""
    zips_dir = pathlib.Path("zips")

    if not zips_dir.exists():
        click.echo("zips/ does not exist, nothing to do.")
        return

    known_hashes: set[str] = set()
    for entry in load_apps():
        src: str = entry.get("src", "")
        if src:
            known_hashes.add(hashlib.sha256(src.encode()).hexdigest()[:10])

    removed = 0
    for zip_path in sorted(zips_dir.glob("*.zip")):
        if zip_path.stem not in known_hashes:
            zip_path.unlink()
            click.echo(f"  removed {zip_path}")
            removed += 1

    click.echo(f"Done — removed {removed} dangling zip(s).")
