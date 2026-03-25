#!/usr/bin/env python3
import atexit
import importlib.util
import json
import logging
import pathlib
import signal
import sys
import threading
import types
from typing import Any
from urllib.parse import urlparse

import click
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

APPS_DIR = pathlib.Path("repos/electron-apps/apps")
DATA_DIR = pathlib.Path("data")


@click.group()
def cli():
    """electronic-survey: tools for analysing the Electron app ecosystem."""
    pass


@cli.command("extract-apps")
def extract_apps():
    """Parse repos/electron-apps/apps/ and upsert data/apps.yml.

    Reads any existing data/apps.yml and updates only the repository and
    website keys for each app, keyed by id.
    """
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / "apps.yml"

    # Load existing data keyed by id so we can do an upsert
    existing: dict[str, dict] = {}
    if out_path.exists():
        with out_path.open() as f:
            for entry in yaml.safe_load(f) or []:
                existing[entry["id"]] = entry

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
    with out_path.open("w") as f:
        yaml.dump(apps, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    with_repo = sum(1 for a in apps if "repository" in a)
    with_website = sum(1 for a in apps if "website" in a)
    click.echo(
        f"Wrote {len(apps)} apps to {out_path} "
        f"({with_repo} with repository, {with_website} with website)."
    )


def _load_processors(processors_dir: pathlib.Path) -> dict[str, types.ModuleType]:
    """Load all *.py files from *processors_dir*, keyed by their stem (e.g. 'github.com')."""
    processors: dict[str, types.ModuleType] = {}
    for path in sorted(processors_dir.glob("*.py")):
        domain = path.stem  # e.g. "github.com"
        spec = importlib.util.spec_from_file_location(
            f"processor_{domain.replace('.', '_')}", path
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        processors[domain] = module
    return processors


def _entry_domain(entry: dict[str, Any]) -> str | None:
    """Return the bare hostname of the repository URL, without a www. prefix."""
    url: str = entry.get("repository", "")
    if not url:
        return None
    try:
        return urlparse(url).netloc.removeprefix("www.").lower() or None
    except Exception:
        return None


def _write_apps(apps: list[dict[str, Any]], path: pathlib.Path) -> None:
    """Write apps atomically via a temp file + rename."""
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        yaml.dump(apps, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp.replace(path)


def _setup_persistent_writer(
    apps: list[dict[str, Any]], path: pathlib.Path, interval: int = 10
) -> threading.Event:
    """Write *apps* to *path* every *interval* seconds and on any exit.

    Returns a stop event; set it to halt the background thread cleanly.
    """
    lock = threading.Lock()
    stop = threading.Event()

    def _write() -> None:
        with lock:
            _write_apps(apps, path)

    def _writer_thread() -> None:
        while not stop.wait(interval):
            _write()

    def _on_exit() -> None:
        stop.set()
        _write()

    def _on_signal(sig: int, frame: Any) -> None:
        sys.exit(0)  # triggers atexit

    t = threading.Thread(target=_writer_thread, daemon=True)
    t.start()

    atexit.register(_on_exit)
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    return stop


def _processor_matches(processor: types.ModuleType, domain: str, entry: dict[str, Any]) -> bool:
    """Return True if *processor* should run against *entry*.

    Processors that define a ``matches(entry)`` function use that; otherwise
    the processor filename stem is compared against the repository domain.
    """
    if hasattr(processor, "matches"):
        return processor.matches(entry)
    return _entry_domain(entry) == domain


@cli.command("process")
@click.argument("processor_name", required=False, default=None)
@click.option("--limit", default=0, help="Stop after processing this many entries (0 = no limit).")
@click.option("--source-fast", is_flag=True, default=False, help="Skip entries that already have an electron version (source processor only).")
@click.option("--aur", "include_aur", is_flag=True, default=False, help="Include the AUR processor (skipped by default).")
def process_apps(processor_name: str | None, limit: int, source_fast: bool, include_aur: bool) -> None:
    """Run processors against data/apps.yml and update in place after each entry.

    PROCESSOR_NAME: optional name of a single processor to run (e.g. 'github.com'
    or 'source'). Omit to run all processors in filename order.
    """
    processors_dir = pathlib.Path("steps")
    out_path = DATA_DIR / "apps.yml"

    if not out_path.exists():
        raise click.ClickException(f"{out_path} not found — run extract-apps first.")

    all_processors = _load_processors(processors_dir)
    if not all_processors:
        raise click.ClickException(f"No processors found in {processors_dir}/.")

    if processor_name is not None:
        if processor_name not in all_processors:
            available = ", ".join(all_processors)
            raise click.ClickException(
                f"Unknown processor '{processor_name}'. Available: {available}"
            )
        processors = {processor_name: all_processors[processor_name]}
    else:
        processors = {
            name: mod for name, mod in all_processors.items()
            if include_aur or getattr(mod, "AUTO", True) is not False
        }

    click.echo(f"Loaded processors: {', '.join(processors)}")

    with out_path.open() as f:
        apps: list[dict[str, Any]] = yaml.safe_load(f) or []

    stop_writer = _setup_persistent_writer(apps, out_path)
    entries_processed = entries_updated = entries_skipped = entries_errored = 0

    for entry in apps:
        if entry is None:
            continue
        if limit and entries_processed >= limit:
            break

        had_match = had_update = had_error = False

        for domain, processor in processors.items():
            if not _processor_matches(processor, domain, entry):
                continue
            if source_fast and domain == "source" and entry.get("electron"):
                entries_skipped += 1
                continue
            had_match = True
            try:
                result: dict[str, Any] | None = processor.process(entry)
            except Exception as exc:
                click.echo(f"  ERROR [{domain}] {entry['id']}: {exc}", err=True)
                had_error = True
                continue
            if result is not None:
                entry.update(result)
                had_update = True

        if not had_match:
            entries_skipped += 1
            continue

        entries_processed += 1
        if had_error:
            entries_errored += 1
        elif had_update:
            entries_updated += 1

    stop_writer.set()
    click.echo(
        f"Done — processed: {entries_processed}, updated: {entries_updated}, "
        f"errors: {entries_errored}, skipped (no processor): {entries_skipped}."
    )


def _load_version_dates() -> dict[str, datetime]:
    """Return {version: release_date} from data/versions.txt."""
    from datetime import datetime, timezone
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
    from datetime import datetime, timezone
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
    """Generate REPORT.md from data/apps.yml."""
    out_path = DATA_DIR / "apps.yml"
    if not out_path.exists():
        raise click.ClickException(f"{out_path} not found — run extract-apps first.")

    with out_path.open() as f:
        apps: list[dict[str, Any]] = [e for e in (yaml.safe_load(f) or []) if e]

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


@cli.command("stats")
def stats() -> None:
    """Print processing statistics for data/apps.yml."""
    out_path = DATA_DIR / "apps.yml"
    if not out_path.exists():
        raise click.ClickException(f"{out_path} not found — run extract-apps first.")

    with out_path.open() as f:
        apps: list[dict[str, Any]] = [e for e in (yaml.safe_load(f) or []) if e]

    total = len(apps)
    with_version = sum(1 for a in apps if "electron" in a)
    remaining = [a for a in apps if "electron" not in a]
    with_downloads = sum(1 for a in remaining if "downloads" in a)
    with_aur = sum(1 for a in remaining if "downloads" not in a and a.get("aur"))
    no_idea = sum(1 for a in remaining if "downloads" not in a and not a.get("aur"))

    click.echo(f"total:          {total}")
    click.echo(f"with-version:   {with_version}")
    click.echo(f"with-downloads: {with_downloads}")
    click.echo(f"with-aur:       {with_aur}")
    click.echo(f"no-idea:        {no_idea}")


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


@cli.command("cleanup")
def cleanup() -> None:
    """Remove zip files in zips/ that are no longer referenced by data/apps.yml."""
    import hashlib

    zips_dir = pathlib.Path("zips")
    out_path = DATA_DIR / "apps.yml"

    if not zips_dir.exists():
        click.echo("zips/ does not exist, nothing to do.")
        return

    known_hashes: set[str] = set()
    if out_path.exists():
        with out_path.open() as f:
            for entry in yaml.safe_load(f) or []:
                src: str = entry.get("src", "")
                if src:
                    known_hashes.add(hashlib.sha256(src.encode()).hexdigest()[:10])

    removed = 0
    for zip_path in sorted(zips_dir.glob("*.zip")):
        stem = zip_path.stem  # e.g. "a3f9b12c4e"
        if stem not in known_hashes:
            zip_path.unlink()
            click.echo(f"  removed {zip_path}")
            removed += 1

    click.echo(f"Done — removed {removed} dangling zip(s).")


if __name__ == "__main__":
    cli()
