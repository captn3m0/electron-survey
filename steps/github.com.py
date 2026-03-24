"""Processor for GitHub repositories.

Calls the GitHub Releases API to discover the latest stable release,
its tag, a zip archive URL, and any attached release assets (with
checksums resolved where available).
"""

import os
import re
from typing import Any
from urllib.parse import urlparse

import requests

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
)
if token := os.environ.get("GITHUB_TOKEN"):
    _SESSION.headers["Authorization"] = f"Bearer {token}"


def _parse_owner_repo(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) from a GitHub URL, or None if not a GitHub URL."""
    parsed = urlparse(url.rstrip("/"))
    if parsed.netloc.removeprefix("www.") != "github.com":
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    return owner, repo


def _parse_checksums(text: str) -> dict[str, str]:
    """Parse a checksum file into {filename: hash}.

    Handles the common ``<hash>  <filename>`` and ``<hash>  *<filename>``
    formats produced by sha256sum / md5sum.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            checksum, filename = parts
            result[filename.lstrip("*")] = checksum
    return result


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch the latest stable GitHub release for *entry* and return metadata.

    Returns a dict with:
      latest    – the tag name of the latest stable release
      src  – zip archive URL for that tag
      downloads – list of release assets, each with name, url, and optionally
                  checksum

    Returns None if the entry has no GitHub repository or no stable release.
    """
    repo_url: str = entry.get("repository", "")
    parsed = _parse_owner_repo(repo_url)
    if parsed is None:
        return None

    owner, repo = parsed
    resp = _SESSION.get(
        f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
        timeout=15,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    release: dict[str, Any] = resp.json()
    tag: str = release["tag_name"]

    # Build the asset list before resolving checksums
    assets: list[dict[str, Any]] = release.get("assets", [])
    downloads: list[dict[str, Any]] = [
        {"name": a["name"], "url": a["browser_download_url"]} for a in assets
    ]

    # Find and parse any checksum files attached to the release
    checksum_map: dict[str, str] = {}
    for asset in assets:
        if re.search(r"sha(256|512|1|sums)|checksum|md5", asset["name"], re.IGNORECASE):
            cr = _SESSION.get(asset["browser_download_url"], timeout=15)
            if cr.ok:
                checksum_map.update(_parse_checksums(cr.text))

    # Attach resolved checksums to matching download entries
    if checksum_map:
        for dl in downloads:
            if dl["name"] in checksum_map:
                dl["checksum"] = checksum_map[dl["name"]]

    result: dict[str, Any] = {
        "latest": tag,
        "src": f"https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.zip",
    }
    if downloads:
        result["downloads"] = downloads

    return result
