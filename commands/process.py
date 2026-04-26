import importlib.util
import pathlib
import types
from typing import Any
from urllib.parse import urlparse

import click

from commands import load_apps, write_app, cli


def _load_processors(processors_dir: pathlib.Path) -> dict[str, types.ModuleType]:
    """Load all *.py files from *processors_dir*, keyed by their stem."""
    processors: dict[str, types.ModuleType] = {}
    for path in sorted(processors_dir.glob("*.py")):
        stem = path.stem
        spec = importlib.util.spec_from_file_location(
            f"processor_{stem.replace('.', '_')}", path
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        processors[stem] = module
    return processors


def _entry_domain(entry: dict[str, Any]) -> str | None:
    url: str = entry.get("repository", "")
    if not url:
        return None
    try:
        return urlparse(url).netloc.removeprefix("www.").lower() or None
    except Exception:
        return None


def _processor_matches(processor: types.ModuleType, domain: str, entry: dict[str, Any]) -> bool:
    if hasattr(processor, "matches"):
        return processor.matches(entry)
    return _entry_domain(entry) == domain


@cli.command("process")
@click.argument("processor_name", required=False, default=None)
@click.option("--limit", default=0, help="Stop after processing this many entries (0 = no limit).")
@click.option("--source-fast", is_flag=True, default=False, help="Skip entries that already have an electron version (source processor only).")
@click.option("--aur", "include_aur", is_flag=True, default=False, help="Include the AUR processor (skipped by default).")
def process_apps(processor_name: str | None, limit: int, source_fast: bool, include_aur: bool) -> None:
    """Run processors against data/apps/ and write each entry immediately on update.

    PROCESSOR_NAME: optional name of a single processor to run (e.g. 'github.com'
    or 'source'). Omit to run all processors in filename order.
    """
    processors_dir = pathlib.Path("steps")
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

    apps = load_apps()
    entries_processed = entries_updated = entries_skipped = entries_errored = 0

    for entry in apps:
        if entry.get("dead"):
            entries_skipped += 1
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

        if had_update:
            write_app(entry)

        entries_processed += 1
        if had_error:
            entries_errored += 1
        elif had_update:
            entries_updated += 1

    click.echo(
        f"Done — processed: {entries_processed}, updated: {entries_updated}, "
        f"errors: {entries_errored}, skipped (no processor): {entries_skipped}."
    )
