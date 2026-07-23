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
import os
import pathlib
import re
import shutil
import zipfile
from typing import Any

import requests
import semantic_version
import yaml as _yaml

log = logging.getLogger(__name__)

# Precise lockfile detection; runs before the approximate aur-version step so
# an exact version wins over an AUR major→latest guess.
ORDER = 40

ZIPS_DIR = pathlib.Path("zips")
SRC_DIR = pathlib.Path("src")

# Skip source archives larger than this (MB): normal npm projects are small,
# and huge archives are usually repos vendoring binaries — not worth the disk.
_MAX_ZIP_MB = int(os.environ.get("SOURCE_MAX_MB", "300"))
# Keep the extracted tree after parsing? Off by default so runs don't fill the
# disk (src/ reached 8 GB on CI); set SURVEY_KEEP_SRC=1 for local debugging.
_KEEP_SRC = os.environ.get("SURVEY_KEEP_SRC") == "1"

_SESSION = requests.Session()


def matches(entry: dict[str, Any]) -> bool:
    if not entry.get("src"):
        return False
    if entry.get("electron"):
        method = entry.get("method", "")
        if not method.startswith("src-"):
            # Resolved by a different (equally/more authoritative) processor —
            # don't overwrite a which-electron / aur-depends / direct value.
            return False
        if entry.get("electron_src") == entry.get("src"):
            # Already detected from this exact archive; re-detect only once the
            # github.com processor points src at a newer release.
            return False
    return True


# ---------------------------------------------------------------------------
# Download / extract helpers
# ---------------------------------------------------------------------------

def _download_zip(url: str) -> pathlib.Path | None:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:10]
    ZIPS_DIR.mkdir(exist_ok=True)
    zip_path = ZIPS_DIR / f"{url_hash}.zip"
    if zip_path.exists() and zip_path.stat().st_size > 0:
        return zip_path
    cap = _MAX_ZIP_MB * 1024 * 1024
    resp = _SESSION.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    if int(resp.headers.get("content-length", 0)) > cap:
        log.info("skip %s: archive larger than %d MB", url, _MAX_ZIP_MB)
        return None
    tmp = zip_path.with_suffix(".zip.part")
    written = 0
    try:
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                written += len(chunk)
                if written > cap:
                    log.info("skip %s: archive grew past %d MB", url, _MAX_ZIP_MB)
                    raise _ArchiveTooLarge
                f.write(chunk)
    except _ArchiveTooLarge:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(zip_path)
    return zip_path


class _ArchiveTooLarge(Exception):
    """Raised to abort a source archive that exceeds the size cap."""


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


def _electron_from_package_lock(paths: list[pathlib.Path]) -> tuple[str, pathlib.Path] | None:
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        # v2/v3 format
        pkg = data.get("packages", {}).get("node_modules/electron")
        if pkg and "version" in pkg:
            return str(pkg["version"]), path
        # v1 format
        dep = data.get("dependencies", {}).get("electron")
        if dep and "version" in dep:
            return str(dep["version"]), path
    return None


def _electron_from_yarn_lock(paths: list[pathlib.Path]) -> tuple[str, pathlib.Path] | None:
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
            return m.group(1), path
    return None


def _electron_from_pnpm_lock(paths: list[pathlib.Path]) -> tuple[str, pathlib.Path] | None:
    for path in paths:
        try:
            data = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        # Prefer the version pnpm resolved for the project's own `electron`
        # dependency (importers.<project>.*Dependencies.electron). Falling
        # straight to a packages/snapshots key match below picks up ANY
        # package literally named electron, including one pulled in by an
        # unrelated dev tool (e.g. react-devtools bundles its own electron
        # to run standalone) — a different, unrelated version.
        importers = data.get("importers") or {}
        for key in sorted(importers, key=lambda k: (k != ".", k)):
            project = importers[key]
            if not isinstance(project, dict):
                continue
            for dep_kind in ("dependencies", "devDependencies", "optionalDependencies"):
                dep = (project.get(dep_kind) or {}).get("electron")
                if isinstance(dep, dict) and dep.get("version"):
                    m = re.search(r'(\d+\.\d+\.\d+)', str(dep["version"]))
                    if m:
                        return m.group(1), path

        # pnpm v6-v8: packages keys like "/electron/20.1.0" or "/electron@20.1.0"
        # pnpm v9: snapshots keys like "electron@20.1.0"
        for section in ("packages", "snapshots"):
            for key in data.get(section, {}):
                if re.match(r'^/?electron[@/]', str(key)):
                    m = re.search(r'[\/@](\d+\.\d+\.\d+)', str(key))
                    if m:
                        return m.group(1), path
    return None


def _electron_range_from_package_json(paths: list[pathlib.Path]) -> tuple[str, pathlib.Path] | None:
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for dep_key in ("devDependencies", "dependencies"):
            val = data.get(dep_key, {}).get("electron")
            if val:
                return str(val), path
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
                v = line.split("\t")[0].strip()
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
    if zip_path is None:
        return None
    extract_dir = SRC_DIR / app_id
    try:
        result = _detect(app_id, zip_path, extract_dir)
    finally:
        if not _KEEP_SRC:
            shutil.rmtree(extract_dir, ignore_errors=True)
    if result and "electron" in result:
        # Record which archive this version came from so matches() can re-detect
        # when the github.com processor advances src to a newer release.
        result["electron_src"] = src_url
        if "evidence" in result:
            result["evidence"]["source"] = src_url
    return result


def _detect(app_id: str, zip_path: pathlib.Path, extract_dir: pathlib.Path) -> dict[str, Any] | None:
    try:
        _extract_zip(zip_path, extract_dir)
    except zipfile.BadZipFile:
        log.warning("[%s] corrupt archive %s, discarding", app_id, zip_path)
        zip_path.unlink(missing_ok=True)
        return None

    # Locate all instances of each file type, sorted shallowest first
    pkg_locks = _by_depth(list(extract_dir.rglob("package-lock.json")))
    yarn_locks = _by_depth(list(extract_dir.rglob("yarn.lock")))
    pnpm_locks = _by_depth(list(extract_dir.rglob("pnpm-lock.yaml")))
    pkg_jsons  = _by_depth(list(extract_dir.rglob("package.json")))

    # Collect exact versions from lockfiles in preference order
    lockfile_versions: list[tuple[str, str, pathlib.Path]] = []
    for label, extractor in [
        ("package-lock.json", lambda: _electron_from_package_lock(pkg_locks)),
        ("yarn.lock",         lambda: _electron_from_yarn_lock(yarn_locks)),
        ("pnpm-lock.yaml",    lambda: _electron_from_pnpm_lock(pnpm_locks)),
    ]:
        found = extractor()
        if found:
            version, path = found
            lockfile_versions.append((label, version, path))

    unique_versions = list(dict.fromkeys(v for _, v, _ in lockfile_versions))

    if len(unique_versions) > 1:
        detail = ", ".join(f"{lbl}={ver}" for lbl, ver, _ in lockfile_versions)
        log.warning("[%s] conflicting electron versions across lockfiles: %s", app_id, detail)

    _method_map = {
        "package-lock.json": "src-package-lock",
        "yarn.lock":         "src-yarn-lock",
        "pnpm-lock.yaml":    "src-pnpm-lock",
    }

    def _rel(path: pathlib.Path) -> str:
        """Path of the file inside the archive, not on this machine's disk."""
        try:
            return str(path.relative_to(extract_dir))
        except ValueError:
            return path.name

    if unique_versions:
        source, version, path = lockfile_versions[0]
        log.info("[%s] electron %s detected via %s (%s)", app_id, version, source, _rel(path))
        evidence = {
            "kind": "lockfile",
            "found_in": _rel(path),
            "signal": f"electron pinned in {source}",
        }
        if len(unique_versions) > 1:
            evidence["signal"] += (
                " — other lockfiles in this archive disagree: "
                + ", ".join(f"{lbl}={ver}" for lbl, ver, _ in lockfile_versions[1:])
            )
        return {
            "electron": version,
            "method": _method_map.get(source, f"src-{source}"),
            "evidence": evidence,
        }

    # No lockfile found electron — try package.json files shallowest first
    if pkg_jsons:
        found = _electron_range_from_package_json(pkg_jsons)
        if found:
            rng, path = found
            exact = re.fullmatch(r'v?(\d+\.\d+\.\d+)', rng.strip())
            if exact:
                version = exact.group(1)
                log.info("[%s] electron %s detected via package.json (exact)", app_id, version)
                return {
                    "electron": version,
                    "method": "src-package-json",
                    "evidence": {
                        "kind": "manifest",
                        "found_in": _rel(path),
                        "signal": f"electron pinned to exactly {rng}",
                    },
                }
            resolved = _resolve_range(rng)
            if resolved:
                log.warning("[%s] electron version-range ONLY from package.json: %s", app_id, rng)
                log.info("[%s] electron %s resolved from range %s", app_id, resolved, rng)
                return {
                    "electron": resolved,
                    "method": "src-range-guess",
                    "evidence": {
                        "kind": "manifest",
                        "found_in": _rel(path),
                        "signal": f"no lockfile; range \"{rng}\" resolved to its highest known match",
                    },
                }
            log.warning("[%s] electron range %s could not be resolved", app_id, rng)

    log.info("[%s] no electron version found", app_id)
    return None
