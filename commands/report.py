import json
import pathlib
from datetime import datetime, timezone
from typing import Any

import click

from commands import DATA_DIR, cli, load_apps


def _load_version_dates() -> dict[str, datetime]:
    """Return {version: release_date} from data/versions.txt."""
    path = DATA_DIR / "versions.txt"
    if not path.exists():
        return {}
    result: dict[str, datetime] = {}
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            try:
                result[parts[0].strip()] = datetime.fromisoformat(parts[1].strip())
            except ValueError:
                pass
    return result


def _relative_age(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    days = (now - dt).days
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    years, months = divmod(days // 30, 12)
    return f"{years}y {months}mo ago" if months else f"{years}y ago"


def _supported_electron_versions() -> set[str]:
    """Return the set of latest.name values for non-EOL Electron releases."""
    import urllib.request
    with urllib.request.urlopen("https://endoflife.date/api/v1/products/electron") as resp:
        data = json.loads(resp.read())
    return {
        r["latest"]["name"]
        for r in data["result"]["releases"]
        if not r["isEol"] and r.get("latest")
    }


@cli.command("report")
def report() -> None:
    """Generate REPORT.md from data/apps/."""
    apps: list[dict[str, Any]] = load_apps()

    try:
        supported = _supported_electron_versions()
        click.echo(f"Supported Electron releases: {len(supported)}")
    except Exception as exc:
        click.echo(f"Warning: could not fetch EOL data: {exc}", err=True)
        supported = set()

    version_dates = _load_version_dates()

    rows = [a for a in apps if "electron" in a]
    rows.sort(key=lambda a: a.get("name") or a["id"])

    lines = [
        "# Electron version report",
        "",
        f"Apps with detected Electron version: {len(rows)} / {len(apps)}",
        "",
        "| App | Electron | Age | Method |",
        "| --- | -------- | --- | ------ |",
    ]

    for a in rows:
        name = a.get("name") or a["id"]
        website = a.get("website", "")
        repo = a.get("repository", "")
        app_label = f"[{name}]({website})" if website else name
        if repo:
            app_label += f" [[repo]]({repo})"
        electron = a.get("electron", "")
        flag = " ⚠️" if supported and electron not in supported else ""
        dt = version_dates.get(electron)
        age = _relative_age(dt) if dt else ""
        method = a.get("method", "")
        lines.append(f"| {app_label} | {electron}{flag} | {age} | {method} |")

    report_path = pathlib.Path("REPORT.md")
    report_path.write_text("\n".join(lines) + "\n")
    click.echo(f"Wrote {len(rows)} rows to {report_path}.")
