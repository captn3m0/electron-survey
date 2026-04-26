"""Processor that finds Homebrew casks matching an app entry.

Not run automatically — only when explicitly selected.

Matching strategy (tried in order):
1. Direct token lookup: try the app id as a cask token via the local
   meta/homebrew-casks.json index.
2. Homepage domain match: grep the app's website domain against the
   ``homepage`` field in the cask index.  Generic hosting domains are
   skipped to avoid false positives.

Sets ``homebrew: <token>`` and appends the cask download URL to
``downloads`` when a match is found.
"""

import json
import logging
import pathlib
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

AUTO = False

META_FILE = pathlib.Path("meta/homebrew-casks.json")

_GENERIC_DOMAINS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "sourceforge.net",
    "codeberg.org",
    "sr.ht",
    "gitlab.io",
    "github.io",
}


@lru_cache(maxsize=1)
def _load_index() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Return (by_token, by_domain) indexes from the cask meta file."""
    if not META_FILE.exists():
        log.warning("Homebrew cask meta file not found: %s", META_FILE)
        return {}, {}
    with META_FILE.open() as f:
        casks: list[dict] = json.load(f)
    by_token: dict[str, dict] = {}
    by_domain: dict[str, list[dict]] = {}
    for cask in casks:
        token = cask.get("token", "")
        if token:
            by_token[token] = cask
        hp = cask.get("homepage", "")
        if hp:
            try:
                domain = urlparse(hp).netloc.removeprefix("www.")
            except Exception:
                domain = ""
            if domain and domain not in _GENERIC_DOMAINS:
                by_domain.setdefault(domain, []).append(cask)
    return by_token, by_domain


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return ""


def matches(entry: dict[str, Any]) -> bool:
    if entry.get("homebrew") is False:
        return False
    if entry.get("dead"):
        return False
    return "homebrew" not in entry


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    by_token, by_domain = _load_index()

    found: list[dict] = []

    # 1. Try exact token match by app id
    app_id = entry.get("id", "")
    if app_id in by_token:
        found = [by_token[app_id]]

    # 2. Homepage domain fallback
    if not found:
        website = entry.get("website", "")
        if website:
            domain = _domain(website)
            if domain and domain not in _GENERIC_DOMAINS:
                found = by_domain.get(domain, [])

    if not found:
        return None

    if len(found) > 10:
        log.warning("[%s] Homebrew search returned %d results, skipping", entry["id"], len(found))
        return None

    if len(found) > 5:
        log.warning("[%s] Homebrew search returned %d results: %s", entry["id"], len(found), [c["token"] for c in found])

    # Use the first (or only) match
    cask = found[0]
    token: str = cask["token"]
    url: str = cask.get("url", "")
    version: str = cask.get("version", "")

    log.info("[%s] Homebrew cask: %s  version=%s", entry["id"], token, version)

    result: dict[str, Any] = {"homebrew": token}

    if url:
        name = url.rsplit("/", 1)[-1].split("?")[0] or f"{token}.dmg"
        dl: dict[str, Any] = {"url": url, "name": name}
        if version:
            dl["version"] = version
        # Append to existing downloads rather than replacing
        existing = list(entry.get("downloads") or [])
        result["downloads"] = existing + [dl]

    return result
