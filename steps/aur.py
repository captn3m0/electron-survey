"""Processor that finds AUR packages matching an app entry.

Not run automatically — only when --aur is passed to the process command.

Matching strategy (tried in order):
1. Match the domain of the app's website URL against the host of each AUR
   package's ``URL`` field.  Generic code-hosting domains (github.com,
   gitlab.com, …) are skipped to avoid matching every package on AUR.
2. Match the app id directly against a package name (case-insensitive).

Sets ``aur: [<package-name>, ...]`` when any match is found.  If a matched
package's ``URL`` is a GitHub repository and the entry has no ``repository``
yet, that repository is recovered too, bringing the app into the github.com /
source detection pipeline.

The full AUR metadata (~116k packages) is indexed once per run rather than
grepped per app.
"""

import logging
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

# This processor is opt-in; the process command skips it unless --aur is given.
AUTO = False
# Runs after the domain processors so a recovered repository is picked up on the
# next pass; before aur-version, which reads the aur key this sets.
ORDER = 50

META_FILE = "meta/packages-meta-ext-v1.json"

# Domains that host many projects — matching them produces useless noise.
_GENERIC_DOMAINS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "sourceforge.net",
    "codeberg.org",
    "sr.ht",
}

log = logging.getLogger(__name__)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.").lower()
    except Exception:
        return ""


@lru_cache(maxsize=1)
def _load_index() -> tuple[dict[str, list[str]], dict[str, str], dict[str, str]]:
    """Return (by_domain, by_name_lower, url_by_name) indexes over AUR metadata.

    by_domain      – {url-host: [package names]}
    by_name_lower  – {lowercased name: canonical name}
    url_by_name    – {canonical name: upstream URL}
    """
    import json
    import pathlib

    path = pathlib.Path(META_FILE)
    if not path.exists():
        log.warning("AUR meta file not found: %s", META_FILE)
        return {}, {}, {}

    by_domain: dict[str, list[str]] = {}
    by_name_lower: dict[str, str] = {}
    url_by_name: dict[str, str] = {}
    with path.open() as f:
        for pkg in json.load(f):
            name = pkg.get("Name")
            if not name:
                continue
            by_name_lower[name.lower()] = name
            url = pkg.get("URL") or ""
            if url:
                url_by_name[name] = url
                host = _host(url)
                if host and host not in _GENERIC_DOMAINS:
                    by_domain.setdefault(host, []).append(name)
    return by_domain, by_name_lower, url_by_name


def _github_repo(url: str) -> str | None:
    """Return a clean https://github.com/owner/repo URL, or None."""
    parsed = urlparse(url.rstrip("/"))
    if parsed.netloc.removeprefix("www.").lower() != "github.com":
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not owner or not repo:
        return None
    return f"https://github.com/{owner}/{repo}"


def matches(entry: dict[str, Any]) -> bool:
    if entry.get("aur") is False:
        return False
    return "aur" not in entry and bool(entry.get("website") or entry.get("id"))


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    by_domain, by_name_lower, url_by_name = _load_index()

    found: list[str] = []

    website: str = entry.get("website", "")
    if website:
        domain = _host(website)
        if domain and domain not in _GENERIC_DOMAINS:
            found = by_domain.get(domain, [])

    if not found:
        canonical = by_name_lower.get(entry["id"].lower())
        if canonical:
            found = [canonical]

    if not found:
        return None

    if len(found) > 10:
        log.warning("[%s] AUR search returned %d results, skipping", entry["id"], len(found))
        return None

    if len(found) > 5:
        log.warning("[%s] AUR search returned %d results: %s", entry["id"], len(found), found)

    result: dict[str, Any] = {"aur": found}

    # Recover a GitHub repository from the matched package's upstream URL so the
    # github.com / source processors can take over on the next run.
    if not entry.get("repository"):
        for name in found:
            repo = _github_repo(url_by_name.get(name, ""))
            if repo:
                log.info("[%s] recovered repository %s from AUR package %s", entry["id"], repo, name)
                result["repository"] = repo
                break

    return result
