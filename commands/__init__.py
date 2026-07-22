import pathlib
from typing import Any

import click
import yaml

DATA_DIR = pathlib.Path("data")
APPS_DIR = pathlib.Path("repos/electron-apps/apps")
APPS_DATA_DIR = DATA_DIR / "apps"


def load_apps() -> list[dict[str, Any]]:
    """Load all per-app YAML files from data/apps/, sorted by id."""
    if not APPS_DATA_DIR.exists():
        return []
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


@click.group()
def cli() -> None:
    """electronic-survey: tools for analysing the Electron app ecosystem."""
    pass


from commands import audit, cleanup, cves, dedupe, evidence, extract_apps, fetch_versions, freshness, popularity, process, report, stats, summary  # noqa: E402, F401
