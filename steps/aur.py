"""Processor that finds AUR packages matching an app entry.

Not run automatically — only when --aur is passed to the process command.

Matching strategy (tried in order):
1. grep the domain from the app's website URL against "URL" fields in
   packages-meta-ext-v1.json.  Generic code-hosting domains (github.com,
   gitlab.com, …) are skipped to avoid matching every package on AUR.
2. grep the app id directly in aur-packages (exact case-insensitive line).

Sets aur: [<package-name>, ...] on the entry when any match is found.
"""

import re
import subprocess
from typing import Any
from urllib.parse import urlparse

# This processor is opt-in; the process command skips it unless --aur is given.
AUTO = False

META_FILE = "meta/packages-meta-ext-v1.json"
PKGLIST_FILE = "meta/aur-packages"

# Domains that host many projects — grepping them produces useless noise.
_GENERIC_DOMAINS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "sourceforge.net",
    "codeberg.org",
    "sr.ht",
}


import logging

log = logging.getLogger(__name__)


def matches(entry: dict[str, Any]) -> bool:
    if entry.get("aur") is False:
        return False
    return "aur" not in entry and bool(entry.get("website") or entry.get("id"))


def _extract_names(grep_output: str) -> list[str]:
    return re.findall(r'"Name":"([^"]+)"', grep_output)


def _grep_domain(domain: str) -> list[str]:
    result = subprocess.run(
        ["grep", "-i", domain, META_FILE],
        capture_output=True, text=True
    )
    return _extract_names(result.stdout)


def _grep_id_in_pkglist(app_id: str) -> list[str]:
    result = subprocess.run(
        ["grep", "-ix", app_id, PKGLIST_FILE],
        capture_output=True, text=True
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    found: list[str] = []

    website: str = entry.get("website", "")
    if website:
        try:
            domain = urlparse(website).netloc.removeprefix("www.")
        except Exception:
            domain = ""
        if domain and domain not in _GENERIC_DOMAINS:
            found = _grep_domain(domain)

    if not found:
        found = _grep_id_in_pkglist(entry["id"])

    if not found:
        return None

    if len(found) > 10:
        log.warning("[%s] AUR search returned %d results, skipping", entry["id"], len(found))
        return None

    if len(found) > 5:
        log.warning("[%s] AUR search returned %d results: %s", entry["id"], len(found), found)

    return {"aur": found}
