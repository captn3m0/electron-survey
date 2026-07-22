"""Reconstruct `evidence` for apps resolved before the processors recorded it.

Each processor now returns an ``evidence`` block saying exactly what it read —
which binary, which lockfile, which AUR package. Apps resolved before that was
added carry only a ``method``, and most will never be re-processed (a resolved
app is not re-fingerprinted), so the provenance has to be rebuilt from what is
already stored:

  * ``aur-depends``  – recomputed from ``meta/packages-meta-ext-v1.json`` exactly
    as the processor would. Skipped when today's AUR metadata no longer agrees
    with the stored version, rather than inventing evidence for a stale answer.
  * ``src-*``        – the archive URL is in ``electron_src``, and the method
    names the lockfile. The path *inside* the archive is not recoverable without
    re-downloading, so it is left out and the record is flagged ``reconstructed``.
  * ``which-electron-*`` – not recoverable at all: which artefact answered is not
    stored anywhere. These fill in as apps are re-fingerprinted.

    uv run main.py evidence-backfill [--dry-run]
"""

import collections
import pathlib
import re
from typing import Any

import click

from commands import cli, load_apps, write_app

_LOCKFILE_BY_METHOD = {
    "src-package-lock": "package-lock.json",
    "src-yarn-lock": "yarn.lock",
    "src-pnpm-lock": "pnpm-lock.yaml",
    "src-package-json": "package.json",
    "src-range-guess": "package.json",
}

_STEP = pathlib.Path("steps/aur-version.py")


def _load_aur_step() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("step_aur_version", _STEP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _major(version: str) -> int | None:
    m = re.match(r"(\d+)", str(version))
    return int(m.group(1)) if m else None


def _aur_evidence(entry: dict, pkg_index: dict[str, list[str]]) -> dict | None:
    """Recompute which AUR package and depend produced this app's version."""
    dep_re = re.compile(r"^electron(\d+)$")
    for pkg_name in entry.get("aur") or []:
        for dep in pkg_index.get(pkg_name, []):
            m = dep_re.match(dep)
            if not m:
                continue
            major = int(m.group(1))
            # Only claim this as the source if it still explains the stored
            # version; otherwise the AUR package has moved on since.
            if major != _major(entry["electron"]):
                return None
            return {
                "kind": "aur-depends",
                "source": f"https://aur.archlinux.org/packages/{pkg_name}",
                "found_in": pkg_name,
                "signal": f"depends on {dep}; reported as the newest "
                          f"{major}.x release ({entry['electron']})",
            }
    return None


def _src_evidence(entry: dict) -> dict | None:
    lockfile = _LOCKFILE_BY_METHOD.get(entry.get("method", ""))
    archive = entry.get("electron_src") or entry.get("src")
    if not lockfile or not archive:
        return None
    manifest = entry["method"] in ("src-package-json", "src-range-guess")
    signal = f"electron pinned in {lockfile}"
    if entry["method"] == "src-range-guess":
        signal = "no lockfile; a package.json range was resolved to its highest known match"
    elif entry["method"] == "src-package-json":
        signal = "electron pinned to an exact version in package.json"
    return {
        "kind": "manifest" if manifest else "lockfile",
        "source": archive,
        "found_in": lockfile,
        "signal": signal,
        # The path within the archive isn't stored; this was rebuilt from the
        # recorded method rather than read back out of the archive.
        "reconstructed": True,
    }


@cli.command("evidence-backfill")
@click.option("--dry-run", is_flag=True, help="Report what would change without writing.")
def evidence_backfill(dry_run: bool) -> None:
    """Rebuild `evidence` for apps resolved before it was recorded."""
    aur_step = _load_aur_step()
    pkg_index = aur_step._load_pkg_index()
    if not pkg_index:
        click.echo("warning: AUR metadata missing; aur-depends evidence will be skipped "
                   "(run `make all`)", err=True)

    stats: collections.Counter[str] = collections.Counter()
    for entry in load_apps():
        if not entry.get("electron") or entry.get("evidence"):
            continue
        method = entry.get("method", "")
        if method == "aur-depends":
            evidence = _aur_evidence(entry, pkg_index)
            stats["aur-stale" if evidence is None else "aur"] += 1
        elif method.startswith("src-"):
            evidence = _src_evidence(entry)
            stats["src" if evidence else "src-unrecoverable"] += 1
        elif method.startswith("which-electron"):
            stats["binary-unrecoverable"] += 1
            continue
        else:
            stats["no-method"] += 1
            continue

        if evidence and not dry_run:
            entry["evidence"] = evidence
            write_app(entry)

    click.echo(
        f"aur-depends rebuilt: {stats['aur']}  (skipped, AUR no longer agrees: {stats['aur-stale']})\n"
        f"src lockfile rebuilt: {stats['src']}  (skipped, no archive recorded: {stats['src-unrecoverable']})\n"
        f"binary, not recoverable: {stats['binary-unrecoverable']}  "
        f"(fills in as apps are re-fingerprinted)\n"
        f"no method recorded: {stats['no-method']}"
        + ("\n(dry run — nothing written)" if dry_run else "")
    )
