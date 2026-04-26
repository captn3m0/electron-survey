from typing import Any

import click
import yaml

from commands import APPS_DATA_DIR, APPS_DIR, load_apps, write_app, cli


@cli.command("extract-apps")
def extract_apps() -> None:
    """Parse repos/electron-apps/apps/ and upsert data/apps/<id>.yml.

    Reads any existing per-app files and updates only the name, repository,
    and website keys for each app, keyed by id.
    """
    APPS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict[str, Any]] = {a["id"]: a for a in load_apps()}

    for app_dir in sorted(APPS_DIR.iterdir()):
        if not app_dir.is_dir():
            continue
        yml_file = app_dir / f"{app_dir.name}.yml"
        if not yml_file.exists():
            continue
        with yml_file.open() as f:
            data = yaml.safe_load(f) or {}

        entry = existing.setdefault(app_dir.name, {"id": app_dir.name})
        for key in ("name", "repository", "website"):
            if key in data:
                entry[key] = data[key]
            else:
                entry.pop(key, None)

    apps = sorted(existing.values(), key=lambda a: a["id"])
    for entry in apps:
        write_app(entry)

    with_repo = sum(1 for a in apps if "repository" in a)
    with_website = sum(1 for a in apps if "website" in a)
    click.echo(
        f"Wrote {len(apps)} apps to {APPS_DATA_DIR}/ "
        f"({with_repo} with repository, {with_website} with website)."
    )
