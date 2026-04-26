"""Processor that runs which-electron against download URLs.

For entries that don't yet have an `electron` version detected, download
the first usable artefact from `downloads` / `packages` and invoke
which-electron in JSON mode. The reported version (without the leading
``v``) is written back, with ``method = which-electron-<signal>``.

Opt-in (``AUTO = False``): pass the processor name explicitly, e.g.

    uv run main.py process which-electron
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import re
import subprocess
from typing import Any

import requests

log = logging.getLogger(__name__)

AUTO = False

ZIPS_DIR = pathlib.Path("zips")

# Formats which-electron handles reliably. `-setup` Windows installers and
# bare redirects without a sensible extension are skipped.
_GOOD_EXT = re.compile(
    r"\.(zip|dmg|appimage|tar\.gz|tar\.bz2|tar\.xz|deb|rpm|7z|exe|nupkg)$",
    re.IGNORECASE,
)
_SKIP_NAME = re.compile(r"-setup\b|setup\.exe$|\.blockmap$|RELEASES$|latest.*\.yml$", re.IGNORECASE)

_SESSION = requests.Session()


def _candidate_urls(entry: dict[str, Any]) -> list[str]:
    """Return download URLs worth feeding to which-electron, best first."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if not url or url in seen:
            return
        if _SKIP_NAME.search(url):
            return
        if not _GOOD_EXT.search(url.split("?", 1)[0]):
            return
        seen.add(url)
        urls.append(url)

    for src in (entry.get("downloads") or []) + (entry.get("packages") or []):
        if isinstance(src, dict):
            add(src.get("url", ""))
        elif isinstance(src, str):
            add(src)

    return urls


def _download(url: str) -> pathlib.Path | None:
    """Cache *url* under zips/<hash><ext> and return the path, or None on failure."""
    ZIPS_DIR.mkdir(exist_ok=True)
    suffix = ""
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if url.lower().endswith(ext):
            suffix = ext
            break
    if not suffix:
        suffix = pathlib.Path(url.split("?", 1)[0]).suffix or ".bin"
    digest = hashlib.sha256(url.encode()).hexdigest()[:10]
    path = ZIPS_DIR / f"{digest}{suffix}"
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        with _SESSION.get(url, stream=True, timeout=120, allow_redirects=True) as r:
            r.raise_for_status()
            tmp = path.with_suffix(path.suffix + ".part")
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            tmp.replace(path)
    except requests.RequestException as exc:
        log.warning("download failed %s: %s", url, exc)
        if path.exists():
            path.unlink()
        return None
    return path


def _run_which_electron(file: pathlib.Path) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            ["npx", "-y", "which-electron", "--json", str(file)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        log.warning("which-electron timed out on %s", file)
        return None
    if proc.returncode != 0:
        log.warning("which-electron exited %d on %s: %s", proc.returncode, file, proc.stderr.strip()[:200])
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        log.warning("which-electron produced no JSON for %s", file)
        return None


def matches(entry: dict[str, Any]) -> bool:
    if entry.get("dead"):
        return False
    if entry.get("electron"):
        return False
    return bool(_candidate_urls(entry))


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    app_id: str = entry["id"]

    for url in _candidate_urls(entry):
        path = _download(url)
        if path is None:
            continue
        result = _run_which_electron(path)
        if not result:
            continue
        version = result.get("version")
        if not version:
            log.info("[%s] no version in which-electron output for %s", app_id, url)
            continue
        method = result.get("method") or "which-electron"
        version = str(version).lstrip("v")
        log.info("[%s] electron %s detected via which-electron/%s on %s", app_id, version, method, url)
        return {"electron": version, "method": f"which-electron-{method}"}

    return None
