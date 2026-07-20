"""Processor that runs which-electron against download URLs.

For entries that don't yet have an `electron` version detected, download
the first usable artefact from `downloads` / `packages` and invoke
which-electron in JSON mode. The reported version (without the leading
``v``) is written back, with ``method = which-electron-<signal>``.

Downloads are transient: each artefact is fetched to a temp file and
deleted immediately after fingerprinting, so a run never accumulates
binaries on disk (important on CI, where the runner has ~14 GB free).
Artefacts larger than ``WHICH_ELECTRON_MAX_MB`` (default 500) are skipped.

Opt-in (``AUTO = False``): pass the processor name explicitly, e.g.

    uv run main.py process which-electron
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import re
import subprocess
import tempfile
from typing import Any

import requests

log = logging.getLogger(__name__)

AUTO = False

ZIPS_DIR = pathlib.Path("zips")
# Transient scratch dir for downloaded binaries; each file is unlinked right
# after use. Kept under zips/ so it lands on the same (large) volume, but its
# contents never persist between artefacts.
TMP_DIR = ZIPS_DIR / "_wbin"

# Skip artefacts larger than this to protect CI disk / runtime.
_MAX_MB = int(os.environ.get("WHICH_ELECTRON_MAX_MB", "500"))
_MAX_BYTES = _MAX_MB * 1024 * 1024

# Formats which-electron handles reliably. `-setup` Windows installers and
# bare redirects without a sensible extension are skipped.
_GOOD_EXT = re.compile(
    r"\.(zip|dmg|appimage|tar\.gz|tar\.bz2|tar\.xz|deb|rpm|7z|exe|nupkg)$",
    re.IGNORECASE,
)
_SKIP_NAME = re.compile(r"-setup\b|setup\.exe$|\.blockmap$|RELEASES$|latest.*\.yml$", re.IGNORECASE)

# Lower number = fetched first. Linux single-arch packages tend to be smaller
# than universal dmg / NSIS exe installers, so try them before the heavyweights.
_EXT_PRIORITY = {
    ".deb": 0, ".rpm": 0, ".appimage": 1, ".tar.gz": 1, ".tar.bz2": 1,
    ".tar.xz": 1, ".nupkg": 2, ".7z": 2, ".zip": 3, ".dmg": 4, ".exe": 5,
}

_SESSION = requests.Session()


class _TooLarge(Exception):
    """Raised to abort a download that grew past the size cap mid-stream."""


# Prefer a local which-electron checkout (repo keeps one, gitignored) so runs
# don't depend on npm network access; fall back to npx on CI.
_LOCAL_WE = pathlib.Path("which-electron/src/index.js")
if _LOCAL_WE.exists():
    _WE_CMD = ["node", str(_LOCAL_WE)]
else:
    _WE_CMD = ["npx", "-y", "which-electron"]


def _ext_of(url: str) -> str:
    path = url.split("?", 1)[0].lower()
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if path.endswith(ext):
            return ext
    return pathlib.Path(path).suffix


def _candidate_urls(entry: dict[str, Any]) -> list[str]:
    """Return download URLs worth feeding to which-electron, cheapest first."""
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

    urls.sort(key=lambda u: _EXT_PRIORITY.get(_ext_of(u), 9))
    return urls


def _too_big(url: str) -> bool:
    """Best-effort size check via a HEAD request before committing to a download."""
    try:
        r = _SESSION.head(url, allow_redirects=True, timeout=30)
        size = int(r.headers.get("content-length", 0))
    except (requests.RequestException, ValueError):
        return False  # unknown size: let the streaming guard handle it
    if size and size > _MAX_BYTES:
        log.info("skip %s: %d MB exceeds cap %d MB", url, size // (1 << 20), _MAX_MB)
        return True
    return False


def _download(url: str) -> pathlib.Path | None:
    """Download *url* to a fresh temp file and return its path, or None.

    The caller is responsible for deleting the returned path.
    """
    if _too_big(url):
        return None
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=_ext_of(url) or ".bin", dir=TMP_DIR)
    path = pathlib.Path(name)
    try:
        with _SESSION.get(url, stream=True, timeout=120, allow_redirects=True) as r:
            r.raise_for_status()
            written = 0
            with os.fdopen(fd, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    written += len(chunk)
                    if written > _MAX_BYTES:
                        log.info("abort %s: exceeded cap %d MB mid-stream", url, _MAX_MB)
                        raise _TooLarge
                    f.write(chunk)
    except (requests.RequestException, _TooLarge) as exc:
        if not isinstance(exc, _TooLarge):
            log.warning("download failed %s: %s", url, exc)
        path.unlink(missing_ok=True)
        return None
    return path


def _run_which_electron(file: pathlib.Path) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            [*_WE_CMD, "--json", str(file)],
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


def _signature(entry: dict[str, Any]) -> str:
    """A stable token for the set of artefacts we'd inspect.

    Changes when a new release ships (``latest`` tag) or the curated download
    URLs change, so a previously-checked app is only re-downloaded when there
    is genuinely something new to fingerprint.
    """
    latest = entry.get("latest")
    if latest:
        return str(latest)
    joined = "\n".join(_candidate_urls(entry))
    return "urls:" + hashlib.sha256(joined.encode()).hexdigest()[:12]


def matches(entry: dict[str, Any]) -> bool:
    if entry.get("dead"):
        return False
    if entry.get("electron"):
        return False
    if not _candidate_urls(entry):
        return False
    # Skip artefacts we already fingerprinted at their current release.
    return entry.get("we_tried") != _signature(entry)


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    app_id: str = entry["id"]
    fingerprinted = False

    for url in _candidate_urls(entry):
        path = _download(url)
        if path is None:
            continue
        try:
            result = _run_which_electron(path)
        finally:
            path.unlink(missing_ok=True)
        fingerprinted = True
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

    # Only record the attempt if we actually inspected something; a run where
    # every download failed (e.g. transient network) should be retried later.
    if fingerprinted:
        log.info("[%s] no electron version from which-electron; marking checked", app_id)
        return {"we_tried": _signature(entry)}
    return None
