"""Extract Electron version from AUR package Depends metadata.

For apps that already have an ``aur`` key (matched packages), look up each
package in packages-meta-ext-v1.json and parse ``electron<major>`` entries
from the Depends array.  Map the major version to the latest stable release
in that series from data/versions.txt.

Sets electron + method: aur-depends on match.
"""

import json
import logging
import pathlib
import re
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)

META_FILE = pathlib.Path("meta/packages-meta-ext-v1.json")
VERSIONS_FILE = pathlib.Path("data/versions.txt")

_ELECTRON_DEP_RE = re.compile(r"^electron(\d+)$")


@lru_cache(maxsize=1)
def _load_pkg_index() -> dict[str, list[str]]:
    """Return {package_name: depends_list} for all AUR packages."""
    if not META_FILE.exists():
        log.warning("AUR meta file not found: %s", META_FILE)
        return {}
    index: dict[str, list[str]] = {}
    with META_FILE.open() as f:
        for pkg in json.load(f):
            name = pkg.get("Name")
            depends = pkg.get("Depends") or []
            if name:
                index[name] = depends
    return index


@lru_cache(maxsize=1)
def _load_major_versions() -> dict[int, str]:
    """Return {major: latest_version_string} from data/versions.txt."""
    if not VERSIONS_FILE.exists():
        log.warning("versions file not found: %s", VERSIONS_FILE)
        return {}
    import semantic_version

    by_major: dict[int, semantic_version.Version] = {}
    for line in VERSIONS_FILE.read_text().splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        ver_str = parts[0].strip()
        try:
            v = semantic_version.Version(ver_str)
        except ValueError:
            continue
        major = v.major
        if major not in by_major or v > by_major[major]:
            by_major[major] = v
    return {major: str(v) for major, v in by_major.items()}


def matches(entry: dict[str, Any]) -> bool:
    aur = entry.get("aur")
    return bool(aur) and isinstance(aur, list) and "electron" not in entry


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    pkg_index = _load_pkg_index()
    major_versions = _load_major_versions()

    found_major: int | None = None

    for pkg_name in entry.get("aur", []):
        depends = pkg_index.get(pkg_name, [])
        for dep in depends:
            m = _ELECTRON_DEP_RE.match(dep)
            if m:
                major = int(m.group(1))
                if found_major is None:
                    found_major = major
                elif found_major != major:
                    log.warning(
                        "[%s] conflicting electron majors in AUR deps (%d vs %d), skipping",
                        entry["id"], found_major, major,
                    )
                    return None

    if found_major is None:
        return None

    version = major_versions.get(found_major)
    if version is None:
        log.warning("[%s] no stable version found for electron major %d", entry["id"], found_major)
        return None

    log.info("[%s] electron %s (major %d from AUR depends)", entry["id"], version, found_major)
    return {"electron": version, "method": "aur-depends"}
