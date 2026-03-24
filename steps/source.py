"""Processor that downloads source archives and detects bundled Electron versions.

Runs after domain processors (e.g. github.com) have set the ``src`` key.
Downloads the zip to zips/<hash>.zip, extracts to src/<id>/, then searches
for an exact Electron version in lockfiles.

Preference order: package-lock.json > yarn.lock > pnpm-lock.yaml > package.json.
If package.json contains a version range it is resolved against data/versions.txt
using npm semver semantics (highest matching version wins).
"""

import hashlib
import json
import logging
import pathlib
import re
import zipfile
from typing import Any

import requests
import semantic_version
import yaml as _yaml

log = logging.getLogger(__name__)

ZIPS_DIR = pathlib.Path("zips")
SRC_DIR = pathlib.Path("src")

_SESSION = requests.Session()


def matches(entry: dict[str, Any]) -> bool:
    return bool(entry.get("src"))


# ---------------------------------------------------------------------------
# Download / extract helpers
# ---------------------------------------------------------------------------

def _download_zip(url: str) -> pathlib.Path:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:10]
    ZIPS_DIR.mkdir(exist_ok=True)
    zip_path = ZIPS_DIR / f"{url_hash}.zip"
    if not zip_path.exists():
        resp = _SESSION.get(url, timeout=60, stream=True)
        resp.raise_for_status()
        with zip_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
    return zip_path


def _extract_zip(zip_path: pathlib.Path, dest: pathlib.Path) -> None:
    if dest.exists():
        return
    dest.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)


# ---------------------------------------------------------------------------
# Electron version extraction
# ---------------------------------------------------------------------------

def _by_depth(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    return sorted(paths, key=lambda p: len(p.parts))


def _electron_from_package_lock(paths: list[pathlib.Path]) -> str | None:
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        # v2/v3 format
        pkg = data.get("packages", {}).get("node_modules/electron")
        if pkg and "version" in pkg:
            return str(pkg["version"])
        # v1 format
        dep = data.get("dependencies", {}).get("electron")
        if dep and "version" in dep:
            return str(dep["version"])
    return None


def _electron_from_yarn_lock(paths: list[pathlib.Path]) -> str | None:
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Classic: electron@range:\n  version "x.y.z"
        # Berry (v2+): electron@range:\n  version: x.y.z
        m = re.search(
            r'^"?electron@[^\n]+\n\s+version[: ]+["\']?(\d+\.\d+\.\d+)',
            text,
            re.MULTILINE,
        )
        if m:
            return m.group(1)
    return None


def _electron_from_pnpm_lock(paths: list[pathlib.Path]) -> str | None:
    for path in paths:
        try:
            data = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        # pnpm v6-v8: packages keys like "/electron/20.1.0" or "/electron@20.1.0"
        # pnpm v9: snapshots keys like "electron@20.1.0"
        for section in ("packages", "snapshots"):
            for key in data.get(section, {}):
                if re.match(r'^/?electron[@/]', str(key)):
                    m = re.search(r'[\/@](\d+\.\d+\.\d+)', str(key))
                    if m:
                        return m.group(1)
    return None


def _electron_range_from_package_json(paths: list[pathlib.Path]) -> str | None:
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for dep_key in ("devDependencies", "dependencies"):
            val = data.get(dep_key, {}).get("electron")
            if val:
                return str(val)
    return None


# ---------------------------------------------------------------------------
# Version range resolution
# ---------------------------------------------------------------------------

_VERSIONS_PATH = pathlib.Path("data/versions.txt")
_known_versions: list[semantic_version.Version] | None = None


def _load_known_versions() -> list[semantic_version.Version]:
    global _known_versions
    if _known_versions is None:
        if not _VERSIONS_PATH.exists():
            log.warning("data/versions.txt not found — run fetch-versions first")
            _known_versions = []
        else:
            versions = []
            for line in _VERSIONS_PATH.read_text().splitlines():
                v = line.strip()
                try:
                    versions.append(semantic_version.Version(v))
                except ValueError:
                    pass
            _known_versions = versions
    return _known_versions


def _resolve_range(rng: str) -> str | None:
    """Return the highest known Electron version satisfying *rng*, or None."""
    try:
        spec = semantic_version.NpmSpec(rng)
    except ValueError:
        return None
    candidates = [v for v in _load_known_versions() if v in spec]
    return str(max(candidates)) if candidates else None


# ---------------------------------------------------------------------------
# Main processor entry point
# ---------------------------------------------------------------------------

def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    app_id: str = entry["id"]
    src_url: str = entry["src"]

    zip_path = _download_zip(src_url)
    extract_dir = SRC_DIR / app_id
    _extract_zip(zip_path, extract_dir)

    # Locate all instances of each file type, sorted shallowest first
    pkg_locks = _by_depth(list(extract_dir.rglob("package-lock.json")))
    yarn_locks = _by_depth(list(extract_dir.rglob("yarn.lock")))
    pnpm_locks = _by_depth(list(extract_dir.rglob("pnpm-lock.yaml")))
    pkg_jsons  = _by_depth(list(extract_dir.rglob("package.json")))

    # Collect exact versions from lockfiles in preference order
    lockfile_versions: list[tuple[str, str]] = []
    for label, extractor in [
        ("package-lock.json", lambda: _electron_from_package_lock(pkg_locks)),
        ("yarn.lock",         lambda: _electron_from_yarn_lock(yarn_locks)),
        ("pnpm-lock.yaml",    lambda: _electron_from_pnpm_lock(pnpm_locks)),
    ]:
        version = extractor()
        if version:
            lockfile_versions.append((label, version))

    unique_versions = list(dict.fromkeys(v for _, v in lockfile_versions))

    if len(unique_versions) > 1:
        detail = ", ".join(f"{lbl}={ver}" for lbl, ver in lockfile_versions)
        log.warning("[%s] conflicting electron versions across lockfiles: %s", app_id, detail)

    _method_map = {
        "package-lock.json": "src-package-lock",
        "yarn.lock":         "src-yarn-lock",
        "pnpm-lock.yaml":    "src-pnpm-lock",
    }

    if unique_versions:
        source, version = lockfile_versions[0]
        log.info("[%s] electron %s detected via %s", app_id, version, source)
        return {"electron": version, "method": _method_map.get(source, f"src-{source}")}

    # No lockfile found electron — try package.json files shallowest first
    if pkg_jsons:
        rng = _electron_range_from_package_json(pkg_jsons)
        if rng:
            exact = re.fullmatch(r'v?(\d+\.\d+\.\d+)', rng.strip())
            if exact:
                version = exact.group(1)
                log.info("[%s] electron %s detected via package.json (exact)", app_id, version)
                return {"electron": version}
            resolved = _resolve_range(rng)
            if resolved:
                log.warning("[%s] electron version-range ONLY from package.json: %s", app_id, rng)
                log.info("[%s] electron %s resolved from range %s", app_id, resolved, rng)
                return {"electron": resolved, "method": "src-range-guess"}
            log.warning("[%s] electron range %s could not be resolved", app_id, rng)

    log.info("[%s] no electron version found", app_id)
    return None
