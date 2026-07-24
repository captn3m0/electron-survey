"""Processor that resolves the binary download URLs of AUR ``*-bin`` packages.

For entries already matched to one or more AUR ``*-bin`` packages (by the
``aur`` processor), fetch each package's ``.SRCINFO``, parse its ``source*``
lines, and expand them into concrete binary download URLs. These land in
``aur_downloads`` (each tagged ``source: aur-bin``) so the which-electron
processor can fingerprint the vendor's own prebuilt binary — a far more
reliable Electron signal than the ``Depends: electron<major>`` major-line
guess that ``aur-version`` produces.

This processor deliberately does NOT set ``electron`` itself; it only surfaces
the artefacts. Opt-in (``AUTO = False``); ``ORDER = 55`` places it after the
``aur`` step (which sets the ``aur`` key) and before ``aur-version`` (60).

Each ``.SRCINFO`` is cached on disk under ``meta/aur-srcinfo/<pkg>.SRCINFO``
and reused if present, so a run hits aur.archlinux.org at most once per package.
"""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Any
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

AUTO = False
# Between aur (50, which sets the `aur` key this reads) and aur-version (60).
ORDER = 55

CACHE_DIR = pathlib.Path("meta/aur-srcinfo")
_SRCINFO_URL = "https://aur.archlinux.org/cgit/aur.git/plain/.SRCINFO?h={pkg}"

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = (
    "electron-survey/1.0 (+https://github.com/captn3m0/electron-survey)"
)

# A `-bin` package ships a prebuilt vendor binary. Exclude VCS/prerelease
# channels (`-git`, `-nightly`, …) that track a moving target rather than the
# stable release users run.
_PRERELEASE_PKG = re.compile(r"-(?:git|nightly|beta|alpha)$", re.IGNORECASE)

# Skip artefacts whose filename marks them as a prerelease build. Boundary-aware
# to avoid false positives (mirrors which-electron._SKIP_NAME).
_PRERELEASE_FILE = re.compile(
    r"(?:^|[-_@./])(?:nightly|beta|alpha)(?:[-_.]|$)|-git(?:[-_.]|$)",
    re.IGNORECASE,
)

# $var / ${var} references inside a .SRCINFO source value.
_VAR_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)")


def _bin_packages(entry: dict[str, Any]) -> list[str]:
    """Return the `-bin` AUR package names worth fetching for this entry."""
    out: list[str] = []
    for pkg in entry.get("aur") or []:
        if not isinstance(pkg, str):
            continue
        if _PRERELEASE_PKG.search(pkg):
            continue
        if pkg.endswith("-bin"):
            out.append(pkg)
    return out


def matches(entry: dict[str, Any]) -> bool:
    if entry.get("dead"):
        return False
    if not isinstance(entry.get("aur"), list):
        return False
    if entry.get("aur_downloads"):
        # Already resolved; don't re-fetch .SRCINFO every run.
        return False
    return bool(_bin_packages(entry))


def _fetch_srcinfo(pkg: str) -> str | None:
    """Return the raw .SRCINFO text for *pkg*, fetching + caching on first use."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{pkg}.SRCINFO"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    url = _SRCINFO_URL.format(pkg=pkg)
    try:
        resp = _SESSION.get(url, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("failed to fetch .SRCINFO for %s: %s", pkg, exc)
        return None
    text = resp.text
    cache.write_text(text, encoding="utf-8")
    return text


def _parse_srcinfo(text: str, pkg: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Parse a .SRCINFO blob.

    Returns ``(variables, sources)`` where ``variables`` maps ``pkgver`` /
    ``pkgname`` / ``pkgbase`` / any ``_*`` custom var to its (already
    concrete) value, and ``sources`` is a list of ``(arch, raw_value)`` pairs
    from ``source`` / ``source_<arch>`` lines in file order.
    """
    variables: dict[str, str] = {}
    sources: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        if key in ("pkgver", "pkgname", "pkgbase") or key.startswith("_"):
            # .SRCINFO lists these once per package; first definition wins.
            variables.setdefault(key, value)
            continue
        m = re.fullmatch(r"source(?:_(\w+))?", key)
        if m:
            sources.append((m.group(1) or "any", value))
    variables.setdefault("pkgname", variables.get("pkgbase", pkg))
    variables.setdefault("pkgbase", variables.get("pkgname", pkg))
    return variables, sources


def _expand(value: str, subs: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return subs.get(name, match.group(0))

    return _VAR_RE.sub(repl, value)


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    app_id: str = entry["id"]
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pkg in _bin_packages(entry):
        text = _fetch_srcinfo(pkg)
        if not text:
            continue
        variables, sources = _parse_srcinfo(text, pkg)
        for arch, value in sources:
            # A source entry is either `filename::url` or a bare `url`.
            url = value.split("::", 1)[1] if "::" in value else value
            subs = {**variables, "CARCH": arch, "carch": arch, "arch": arch}
            url = _expand(url, subs)
            if not url.startswith(("http://", "https://")):
                continue  # local file (lens.install, .desktop) or non-URL source
            if "$" in url:
                continue  # an unresolved variable remained — can't download it
            name = urlparse(url).path.rsplit("/", 1)[-1] or url.rsplit("/", 1)[-1]
            if _PRERELEASE_FILE.search(name):
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append({
                "url": url,
                "name": name,
                "arch": arch,
                "source": "aur-bin",
            })

    if not results:
        return None
    log.info("[%s] %d aur-bin download URL(s) from %s", app_id, len(results),
             ", ".join(_bin_packages(entry)))
    return {"aur_downloads": results}
