"""Processor that populates downloads from manually curated stable download URLs.

For apps that don't distribute via GitHub releases, a ``download_urls`` key
can be added directly to the apps.yml entry:

    download_urls:
    - url: https://example.com/downloads/linux/latest
      name: app-latest.deb

Each URL is typically a stable redirect that resolves to the current release.
The binary inspector follows the redirect to get the actual file.

This processor simply copies ``download_urls`` → ``downloads`` so the rest of
the pipeline (binary inspection) can treat them uniformly.
"""

from typing import Any


def matches(entry: dict[str, Any]) -> bool:
    return bool(entry.get("download_urls"))


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    urls = entry.get("download_urls")
    if not urls:
        return None
    # Normalise: accept bare strings or {url, name} dicts
    downloads = []
    for item in urls:
        if isinstance(item, str):
            downloads.append({"url": item, "name": item.rsplit("/", 1)[-1]})
        elif isinstance(item, dict) and "url" in item:
            downloads.append(item)
    if not downloads:
        return None
    return {"downloads": downloads}
