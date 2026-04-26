import click

from commands import DATA_DIR, cli


@cli.command("fetch-versions")
def fetch_versions() -> None:
    """Fetch all stable Electron versions from npm and write data/versions.txt."""
    from processors import npm

    click.echo("Fetching electron versions from npm registry…")
    versions = npm.fetch()

    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / "versions.txt"
    with out_path.open("w") as f:
        for version, date in versions:
            f.write(f"{version}\t{date.isoformat()}\n")

    click.echo(f"Wrote {len(versions)} stable versions to {out_path}.")
