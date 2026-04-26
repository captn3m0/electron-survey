import pathlib
from typing import Any

import click
import yaml

DATA_DIR = pathlib.Path("data")
APPS_DIR = pathlib.Path("repos/electron-apps/apps")
APPS_DATA_DIR = DATA_DIR / "apps"


def load_apps() -> list[dict[str, Any]]:
    """Load all per-app YAML files from data/apps/, sorted by id.

    If data/apps/ does not exist but data/apps.yml does, migrates automatically.
    """
    if not APPS_DATA_DIR.exists():
        _migrate_from_single_file()
    return [
        yaml.safe_load(f.read_text())
        for f in sorted(APPS_DATA_DIR.glob("*.yml"))
    ]


def write_app(entry: dict[str, Any]) -> None:
    """Atomically write a single app entry to data/apps/<id>.yml."""
    APPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = APPS_DATA_DIR / f"{entry['id']}.yml"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(entry, default_flow_style=False, allow_unicode=True, sort_keys=False))
    tmp.replace(path)


def _migrate_from_single_file() -> None:
    """Split legacy data/apps.yml into individual per-app files."""
    legacy = DATA_DIR / "apps.yml"
    if not legacy.exists():
        return
    APPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with legacy.open() as f:
        apps = yaml.safe_load(f) or []
    for entry in apps:
        if entry:
            write_app(entry)
    click.echo(f"Migrated {len(apps)} entries from {legacy} → {APPS_DATA_DIR}/")


@click.group()
def cli() -> None:
    """electronic-survey: tools for analysing the Electron app ecosystem."""
    pass


from commands import cleanup, extract_apps, fetch_versions, process, report, stats  # noqa: E402, F401
