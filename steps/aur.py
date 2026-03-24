"""Processor that finds AUR packages matching an app entry.

Matching strategy (tried in order):
1. grep the domain from the app's website URL against "URL" fields in
   packages-meta-ext-v1.json — returns package names whose upstream URL
   contains the same domain.
2. grep the app id directly in aur-packages (exact line match).

Sets aur: [<package-name>, ...] on the entry when any match is found.
"""

import re
import subprocess
from typing import Any
from urllib.parse import urlparse

META_FILE = "packages-meta-ext-v1.json"
PKGLIST_FILE = "aur-packages"


def matches(entry: dict[str, Any]) -> bool:
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
        if domain:
            found = _grep_domain(domain)

    if not found:
        found = _grep_id_in_pkglist(entry["id"])

    if not found:
        return None

    return {"aur": found}
