"""Processor that runs which-electron against download URLs.

For entries that don't yet have an `electron` version detected, download
the first usable artefact from `downloads` / `packages` / `aur_downloads`
and invoke which-electron in JSON mode. The reported version (without the
leading ``v``) is written back, with ``method = which-electron-<signal>``.

Candidates are ordered by a source *tier* (homebrew cask binary > AUR
``-bin`` binary > everything else) so the most authoritative artefact is
fingerprinted first. A tier-0/1 binary also *overrides* a version that was
only inferred from github source or AUR depends metadata: see ``matches()``.

Downloads are transient: each artefact is fetched to a temp file and
deleted immediately after fingerprinting, so a run never accumulates
binaries on disk (important on CI, where the runner has ~14 GB free).
Artefacts larger than ``WHICH_ELECTRON_MAX_MB`` (default 700) are skipped.

Opt-in (``AUTO = False``): pass the processor name explicitly, e.g.

    uv run main.py process which-electron
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import re
import subprocess
import tempfile
import time
import zipfile
from typing import Any

import requests

log = logging.getLogger(__name__)

AUTO = False
# Runs last: the only processor that downloads full binaries, so every cheaper
# metadata/source signal gets a chance to resolve the version first.
ORDER = 90

ZIPS_DIR = pathlib.Path("zips")
# Transient scratch dir for downloaded binaries; each file is unlinked right
# after use. Kept under zips/ so it lands on the same (large) volume, but its
# contents never persist between artefacts.
TMP_DIR = ZIPS_DIR / "_wbin"

# Skip artefacts larger than this to protect CI disk / runtime. Raised from 500
# to 700: several legitimate Electron apps (e.g. chatgpt-desktop, codex-app ship
# universal macOS zips in the 530-570 MB range) were permanently stuck unread —
# an oversized sibling artefact meant `we_tried` could never be set (see the
# "only retire once every candidate has actually been inspected" comment below),
# so the app was retried forever without ever getting a fair fingerprint attempt.
_MAX_MB = int(os.environ.get("WHICH_ELECTRON_MAX_MB", "700"))
_MAX_BYTES = _MAX_MB * 1024 * 1024

# Wall-clock budget for a single `process which-electron` run (seconds; 0 = off).
# Once exceeded, matches() stops claiming new entries so the step returns
# promptly and the job's final commit step runs — instead of the job hitting its
# hard timeout mid-download and being force-cancelled, which discards *all*
# uncommitted work (the commit is the last step). The backlog drains across
# successive scheduled runs: each fingerprinted entry gets an electron version
# or a we_tried marker and drops out of matches(), and popularity ordering means
# every run spends its budget on the most-used still-unresolved apps first.
_DEADLINE_SECONDS = int(os.environ.get("WHICH_ELECTRON_DEADLINE_SECONDS", "0"))
_START = time.monotonic()

# Re-claim apps this processor already resolved but for which it never recorded
# *which* artefact answered (see matches()). Opt-in: WHICH_ELECTRON_BACKFILL_EVIDENCE=1.
_BACKFILL_EVIDENCE = os.environ.get("WHICH_ELECTRON_BACKFILL_EVIDENCE") == "1"


def _past_deadline() -> bool:
    return _DEADLINE_SECONDS > 0 and time.monotonic() - _START >= _DEADLINE_SECONDS

# Formats which-electron handles reliably. `-setup` Windows installers and
# bare redirects without a sensible extension are skipped.
_GOOD_EXT = re.compile(
    r"\.(zip|dmg|appimage|tar\.gz|tar\.bz2|tar\.xz|deb|rpm|7z|exe|nupkg)$",
    re.IGNORECASE,
)
# Also drop prerelease artefacts (nightly/beta/alpha channels, VCS `-git`
# builds): a prerelease binary carries the wrong release channel's Electron and
# must not override a stable source/binary detection. Boundary-aware so real
# tokens like "betaflight" or a "beta.example.com" path segment aren't caught by
# a bare substring.
_SKIP_NAME = re.compile(
    r"-setup\b|setup\.exe$|\.blockmap$|RELEASES$|latest.*\.yml$"
    r"|(?:^|[-_@./])(?:nightly|beta|alpha)(?:[-_.]|$)"
    r"|-git(?:[-_.]|$)",
    re.IGNORECASE,
)

# Lower number = fetched first. Linux single-arch packages tend to be smaller
# than universal dmg / NSIS exe installers, so try them before the heavyweights.
_EXT_PRIORITY = {
    ".deb": 0, ".rpm": 0, ".appimage": 1, ".tar.gz": 1, ".tar.bz2": 1,
    ".tar.xz": 1, ".nupkg": 2, ".7z": 2, ".zip": 3, ".dmg": 4, ".exe": 5,
}

_SESSION = requests.Session()
# Identify ourselves. Several vendor CDNs (exodus.com among them) answer 403 to
# the default `python-requests/x.y` User-Agent, which used to fail silently:
# every download errored, so `process()` never wrote a we_tried marker and the
# app was re-queued and re-failed on every run, forever. Any non-default UA is
# enough — no need to impersonate a browser.
_SESSION.headers["User-Agent"] = (
    "electron-survey/1.0 (+https://github.com/captn3m0/electron-survey)"
)


class _TooLarge(Exception):
    """Raised to abort a download that grew past the size cap mid-stream."""


def _resolve_we_cmd() -> list[str]:
    """Build the argv prefix that runs which-electron.

    which-electron's bin entry (``src/index.js``) ships without a
    ``#!/usr/bin/env node`` shebang, so executing the package's ``.bin`` shim
    directly — as ``npx which-electron`` does — hands the file to ``/bin/sh``,
    which chokes on the first line with ``Syntax error: "(" unexpected``. Always
    run the JS file through ``node`` explicitly to sidestep the broken shim.

    Prefer the repo's local checkout (kept gitignored, and provisioned the same
    way on CI) so runs don't depend on npm's network cache. If it's absent, fall
    back to an npm-resolvable install — still via ``node`` — and, failing that,
    log loudly and return a no-op so the misconfiguration is obvious instead of
    silently surfacing as "no JSON" on every artefact.
    """
    local = pathlib.Path("which-electron/src/index.js")
    if local.exists():
        return ["node", str(local)]
    try:
        proc = subprocess.run(
            ["node", "-e", "process.stdout.write(require.resolve('which-electron'))"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        entry = proc.stdout.strip()
        if proc.returncode == 0 and entry:
            return ["node", entry]
    except (OSError, subprocess.SubprocessError):
        pass
    log.error(
        "which-electron not found: no checkout at %s and not resolvable via node. "
        "Fingerprinting will produce no results — provision it with "
        "`git clone https://github.com/captn3m0/which-electron` + `npm ci --omit=dev`.",
        local,
    )
    # Trailing `--` so the wrapper's appended `--json <file>` are treated as
    # script args, not node options (node would reject an unknown `--json`).
    return ["node", "-e", "process.exit(127)", "--"]


_WE_CMD = _resolve_we_cmd()


def _ext_of(url: str) -> str:
    path = url.split("?", 1)[0].lower()
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if path.endswith(ext):
            return ext
    return pathlib.Path(path).suffix


# Source tiers, lowest = highest confidence. A binary fingerprint of the
# vendor's own artefact beats a source/metadata guess, and among binaries a
# homebrew cask or AUR `-bin` build is more authoritative than a generic
# github/static download (which is the same tier as the github source lockfile
# and so must never override it). Candidates are ordered (tier, ext priority).
_TIER_HOMEBREW = 0
_TIER_AUR_BIN = 1
_TIER_OTHER = 2


def _tier_of(src: dict[str, Any], default: int) -> int:
    tag = src.get("source")
    if tag == "homebrew":
        return _TIER_HOMEBREW
    if tag == "aur-bin":
        return _TIER_AUR_BIN
    return default


def _candidate_urls(entry: dict[str, Any]) -> list[tuple[int, str]]:
    """Return ``(tier, url)`` download candidates, highest-confidence first.

    Tier 0 = homebrew cask binary, 1 = AUR `-bin` binary, 2 = everything else
    (github release asset, static/curated download). Sorted by
    ``(tier, ext priority)`` so the most authoritative, cheapest artefact is
    fetched first.
    """
    out: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(url: str, tier: int) -> None:
        if not url or url in seen:
            return
        if _SKIP_NAME.search(url):
            return
        if not _GOOD_EXT.search(url.split("?", 1)[0]):
            return
        seen.add(url)
        out.append((tier, url))

    for src in (entry.get("downloads") or []) + (entry.get("packages") or []):
        if isinstance(src, dict):
            add(src.get("url", ""), _tier_of(src, _TIER_OTHER))
        elif isinstance(src, str):
            add(src, _TIER_OTHER)

    for src in entry.get("aur_downloads") or []:
        if isinstance(src, dict):
            add(src.get("url", ""), _tier_of(src, _TIER_AUR_BIN))
        elif isinstance(src, str):
            add(src, _TIER_AUR_BIN)

    out.sort(key=lambda tu: (tu[0], _EXT_PRIORITY.get(_ext_of(tu[1]), 9)))
    return out


def _too_big(url: str) -> bool:
    """Best-effort size check via a HEAD request before committing to a download."""
    try:
        r = _SESSION.head(url, allow_redirects=True, timeout=30)
        size = int(r.headers.get("content-length", 0))
    except (requests.RequestException, ValueError):
        return False  # unknown size: let the streaming guard handle it
    if size and size > _MAX_BYTES:
        log.info("skip %s: %d MB exceeds cap %d MB", url, size // (1 << 20), _MAX_MB)
        return True
    return False


def _download(url: str) -> pathlib.Path | None:
    """Download *url* to a fresh temp file and return its path, or None.

    The caller is responsible for deleting the returned path.
    """
    if _too_big(url):
        return None
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=_ext_of(url) or ".bin", dir=TMP_DIR)
    path = pathlib.Path(name)
    try:
        with _SESSION.get(url, stream=True, timeout=120, allow_redirects=True) as r:
            r.raise_for_status()
            written = 0
            with os.fdopen(fd, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    written += len(chunk)
                    if written > _MAX_BYTES:
                        log.info("abort %s: exceeded cap %d MB mid-stream", url, _MAX_MB)
                        raise _TooLarge
                    f.write(chunk)
    except (requests.RequestException, _TooLarge) as exc:
        if not isinstance(exc, _TooLarge):
            log.warning("download failed %s: %s", url, exc)
        path.unlink(missing_ok=True)
        return None
    return path


_ASAR_ELECTRON_VERSION = re.compile(rb'"electron":\s*"(\d+\.\d+\.\d+)"')


def _electron_from_asar_in_zip(path: pathlib.Path) -> str | None:
    """Peek inside a downloaded zip for a packed ``app.asar`` and read the
    ``electron`` version pinned in its bundled ``package.json``.

    which-electron's binary-signature fingerprinting can miss a build that
    strips or customises the strings it looks for — observed on OpenAI's
    ChatGPT/Codex desktop apps, both of which which-electron read cleanly with
    no signal, yet the exact version sat unmodified in the asar. Conservative
    by construction: only trusted when every ``"electron": "X.Y.Z"``
    occurrence in the archive agrees, so a bundled dev-tool with its own
    unrelated pin yields no signal rather than a wrong guess.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            members = sorted(
                (n for n in zf.namelist() if n.lower().endswith("app.asar")),
                key=lambda n: n.count("/"),
            )
            if not members:
                return None
            data = zf.read(members[0])
    except (zipfile.BadZipFile, OSError, KeyError):
        return None

    versions = {m.decode() for m in _ASAR_ELECTRON_VERSION.findall(data)}
    if len(versions) > 1:
        log.info("conflicting electron pins inside %s: %s", path, versions)
        return None
    return next(iter(versions), None)


def _run_which_electron(file: pathlib.Path) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            [*_WE_CMD, "--json", str(file)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        log.warning("which-electron timed out on %s", file)
        return None
    if proc.returncode != 0:
        log.warning("which-electron exited %d on %s: %s", proc.returncode, file, proc.stderr.strip()[:200])
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        log.warning("which-electron produced no JSON for %s", file)
        return None


# Bump when *this file's own* detection logic changes in a way that could
# produce a different result for an already-`we_tried` app — a new fallback
# method, a raised size cap, etc — independent of the which-electron tool's
# own fingerprint DB version below. Folded into the epoch so one bump forces
# exactly one re-sweep of the backlog; the daily budgeted run then drains it
# same as any other newly-unresolved apps.
#   1: raised WHICH_ELECTRON_MAX_MB 500->700 MB and added the asar-manifest
#      fallback (see _electron_from_asar_in_zip) — both were silently missing
#      apps like chatgpt-desktop/codex-app whose binaries sit just over the
#      old cap.
_PROCESSOR_EPOCH = "1"


def _fingerprint_epoch() -> str:
    """Identifier for the fingerprint database *and* wrapper logic in use.

    Included in the we_tried signature so that upgrading which-electron (whose
    fingerprint DB may now recognise versions it previously couldn't), or
    bumping _PROCESSOR_EPOCH (when this file's own logic changes), re-opens
    every app that was marked as checked. Tracks the tool's own version when a
    local checkout is present; override with WHICH_ELECTRON_EPOCH.
    """
    try:
        import json
        version = json.loads(pathlib.Path("which-electron/package.json").read_text()).get("version")
        if version:
            return f"we{version}+p{_PROCESSOR_EPOCH}"
    except Exception:
        pass
    return os.environ.get("WHICH_ELECTRON_EPOCH", "we0") + f"+p{_PROCESSOR_EPOCH}"


_EPOCH = _fingerprint_epoch()


def _signature(entry: dict[str, Any]) -> str:
    """A stable token for the set of artefacts we'd inspect.

    Changes when the fingerprint DB is upgraded, when a new release ships
    (``latest`` tag), or when the curated download URLs change — so a
    previously-checked app is only re-downloaded when there is genuinely
    something new to fingerprint.
    """
    latest = entry.get("latest")
    if latest:
        return f"{_EPOCH}:{latest}"
    joined = "\n".join(url for _, url in _candidate_urls(entry))
    return f"{_EPOCH}:urls:" + hashlib.sha256(joined.encode()).hexdigest()[:12]


# Methods that only approximate the bundled version: aur-depends maps an
# `electron<major>` dependency to the latest release in that series (and for
# proprietary apps repackaged against the distro's Electron, that isn't even
# the vendor's bundle), and src-range-guess resolves a semver range to its
# highest match. A binary fingerprint is ground truth, so it overrides these.
_LOW_CONFIDENCE_METHODS = {"aur-depends", "src-range-guess"}


def _is_nonbinary_method(method: str) -> bool:
    """True for versions inferred from github source or AUR depends metadata.

    These live below a binary fingerprint in the precedence order, so a tier-0
    (homebrew cask) or tier-1 (AUR `-bin`) binary is allowed to override them.
    which-electron's own results (``which-electron-*``) are never overridden.
    The ``source`` processor emits ``src-*`` methods; ``source*`` is accepted
    too so the check stays correct if those are ever renamed.
    """
    return method == "aur-depends" or method.startswith(("src-", "source"))


def _has_binary_override_candidate(entry: dict[str, Any]) -> bool:
    """True when a tier-0/1 (homebrew or aur-bin) binary is available to fetch."""
    return any(tier <= _TIER_AUR_BIN for tier, _ in _candidate_urls(entry))


def matches(entry: dict[str, Any]) -> bool:
    if _past_deadline():
        return False  # out of budget: leave the rest for the next scheduled run
    if entry.get("dead"):
        return False
    if not _candidate_urls(entry):
        return False
    electron = entry.get("electron")
    method = str(entry.get("method", ""))

    if electron and _is_nonbinary_method(method):
        # Override case: a github-source lockfile/manifest or an aur-depends
        # major guess can be replaced by a higher-confidence binary fingerprint,
        # but only when a tier-0/1 (homebrew cask / AUR `-bin`) artefact exists —
        # a generic tier-2 github asset is the same tier as the source lockfile
        # and must not override it. When no such binary is available, fall back
        # to the pre-existing behaviour: the low-confidence methods stay eligible
        # for a plain tier-2 re-fingerprint (bounded by we_tried); the exact
        # source lockfiles stay put.
        if _has_binary_override_candidate(entry):
            return entry.get("we_tried") != _signature(entry)
        if method in _LOW_CONFIDENCE_METHODS:
            return entry.get("we_tried") != _signature(entry)
        return False

    if electron:
        # Already resolved by an exact/authoritative method (a binary
        # fingerprint, or a directly-set value). Opting in re-claims the ones
        # this processor resolved before it recorded which artefact answered, so
        # the provenance shown on the site can be filled in — and, as a side
        # effect, their version re-read from the current binary. Off by default:
        # it competes with genuinely unresolved apps for the daily budget.
        if not (_BACKFILL_EVIDENCE
                and method.startswith("which-electron")
                and not entry.get("evidence")):
            return False
        return True

    # Unresolved: skip artefacts we already fingerprinted at their current release.
    return entry.get("we_tried") != _signature(entry)


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    app_id: str = entry["id"]
    inspected = 0
    unread = 0

    candidates = _candidate_urls(entry)
    electron = entry.get("electron")
    method = str(entry.get("method", ""))
    # Override mode: the version is already set by a github-source or aur-depends
    # method and a tier-0/1 binary is available to overrule it. Restrict the
    # artefacts we download to those binaries — a generic tier-2 github/static
    # asset is the same tier as the source lockfile and must not override it.
    # The terminal marking logic below is unchanged, so the existing version is
    # kept on failure (electron is a separate key, never wiped by we_tried) and
    # re-download stops once every readable artefact has been checked.
    override = (
        bool(electron)
        and _is_nonbinary_method(method)
        and any(tier <= _TIER_AUR_BIN for tier, _ in candidates)
    )
    if override:
        candidates = [(tier, url) for tier, url in candidates if tier <= _TIER_AUR_BIN]

    for _tier, url in candidates:
        path = _download(url)
        if path is None:
            unread += 1
            continue
        try:
            result = _run_which_electron(path)
            if result is None:
                # The tool crashed or emitted no JSON (nteract hit a
                # which-electron AppImage extraction bug). That is "we failed
                # to look", not "we looked and found nothing" — an empty
                # `signals` list is the latter.
                unread += 1
                continue
            inspected += 1
            if result:
                version = result.get("version")
                if version:
                    method = result.get("method") or "which-electron"
                    version = str(version).lstrip("v")
                    log.info("[%s] electron %s detected via which-electron/%s on %s", app_id, version, method, url)
                    signals = result.get("signals") or []
                    return {
                        "electron": version,
                        "method": f"which-electron-{method}",
                        "evidence": {
                            "kind": "binary",
                            "source": url,
                            "found_in": url.rsplit("/", 1)[-1],
                            "signal": f"which-electron {method} signal"
                                      + (f" ({len(signals)} signals agreed)" if len(signals) > 1 else ""),
                        },
                    }
                log.info("[%s] no version in which-electron output for %s", app_id, url)

            # which-electron's binary-signature match found nothing — fall back
            # to reading an embedded package.json straight out of a packed
            # app.asar, in case the build strips whatever strings the tool
            # looks for (see _electron_from_asar_in_zip).
            asar_version = _electron_from_asar_in_zip(path)
            if asar_version:
                log.info("[%s] electron %s detected via asar-packed package.json in %s", app_id, asar_version, url)
                return {
                    "electron": asar_version,
                    "method": "which-electron-asar-manifest",
                    "evidence": {
                        "kind": "manifest",
                        "source": url,
                        "found_in": "app.asar (packed package.json)",
                        "signal": "electron version read from a package.json packed inside the app's asar archive",
                    },
                }
        finally:
            path.unlink(missing_ok=True)

    # Only retire the app once *every* candidate has actually been inspected.
    # Marking it checked while some artefact failed to download retires it on
    # the strength of the ones that happened to work — and the artefact that
    # failed is often the only readable one. Typora was exactly this: its .deb
    # fingerprints cleanly, but a transient failure on it plus an unreadable
    # .dmg was enough to write the marker and drop the app for good.
    if inspected and not unread:
        log.info("[%s] no electron version from which-electron; marking checked", app_id)
        return {"we_tried": _signature(entry)}
    if unread:
        log.info("[%s] %d/%d artefacts unreadable; leaving queued for a retry",
                 app_id, unread, inspected + unread)
    return None
