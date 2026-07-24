"""Processor that finds Homebrew casks matching an app entry.

Not run automatically — only when explicitly selected.

Matching strategy (tried in order):
1. Direct token lookup: try the app id as a cask token via the local
   meta/homebrew-casks.json index.
2. Homepage domain match: grep the app's website domain against the
   ``homepage`` field in the cask index.  Generic hosting domains are
   skipped to avoid false positives.

Sets ``homebrew: <token>`` and appends the cask download URL to
``downloads`` when a match is found. Also carries the cask's own
``deprecated``/``disabled`` status forward as ``homebrew_deprecated`` /
``homebrew_disabled`` (plus a short machine reason, e.g. ``unmaintained``,
``fails_gatekeeper_check``), including backfilling it onto apps matched
before this field existed — see ``matches()``.
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
# Adds macOS download URLs before source / which-electron consume them.
ORDER = 30

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

# Cask tokens for prerelease channels (firefox@beta, foo-nightly, …). We want
# the stable binary users actually run: a prerelease dmg tagged as a tier-0
# homebrew candidate could otherwise override a stable source-detected version
# with the wrong release channel. Boundary-aware so e.g. "betaflight" is kept.
_PRERELEASE_TOKEN = re.compile(r"(?:^|[-@])(?:beta|nightly|alpha)(?:$|[-@])", re.IGNORECASE)


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


def _path(url: str) -> str:
    try:
        return urlparse(url).path.strip("/").lower()
    except Exception:
        return ""


def _paths_compatible(website_path: str, cask_path: str) -> bool:
    """True when a shared-domain match is trustworthy.

    A plain single-app vendor homepage has no path on either side, so the
    shared domain alone is enough. Once either side carries a product path
    (openai.com hosts /chatgpt/desktop/ *and* /codex as separate apps), the
    paths must actually correspond — otherwise a domain-only match cross-wires
    sibling products onto the same cask, as happened with chatgpt-desktop
    picking up codex-app's binary.
    """
    if not website_path and not cask_path:
        return True
    if not website_path or not cask_path:
        return False
    return (
        website_path == cask_path
        or website_path.startswith(cask_path + "/")
        or cask_path.startswith(website_path + "/")
    )


def _status_fields(cask: dict[str, Any]) -> dict[str, Any]:
    """Carry a cask's own deprecated/disabled status forward onto the app."""
    fields: dict[str, Any] = {}
    if cask.get("deprecated"):
        fields["homebrew_deprecated"] = True
        if cask.get("deprecation_reason"):
            fields["homebrew_deprecation_reason"] = cask["deprecation_reason"]
    if cask.get("disabled"):
        fields["homebrew_disabled"] = True
        if cask.get("disable_reason"):
            fields["homebrew_disable_reason"] = cask["disable_reason"]
    return fields


def matches(entry: dict[str, Any]) -> bool:
    if entry.get("homebrew") is False:
        return False
    if entry.get("dead"):
        return False
    if "homebrew" not in entry:
        return True
    # Already matched: only re-fire to backfill a deprecated/disabled status
    # that wasn't recorded yet (added after the original match, either because
    # this field didn't exist then or because Homebrew flagged the cask since).
    # One-directional on purpose — a cask essentially never gets "undeprecated"
    # in practice, and reprocessing on any status difference would loop forever
    # since a cleared flag can't be distinguished from one never re-checked.
    by_token, _ = _load_index()
    cask = by_token.get(entry["homebrew"])
    if cask is None:
        return False
    return bool(
        (cask.get("deprecated") and not entry.get("homebrew_deprecated"))
        or (cask.get("disabled") and not entry.get("homebrew_disabled"))
    )


def process(entry: dict[str, Any]) -> dict[str, Any] | None:
    by_token, by_domain = _load_index()

    existing_token = entry.get("homebrew")
    if existing_token:
        # Backfill path (see matches()): the match itself stands, just refresh
        # the deprecated/disabled status.
        cask = by_token.get(existing_token)
        return _status_fields(cask) if cask else None

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
                website_path = _path(website)
                found = [
                    c for c in by_domain.get(domain, [])
                    if _paths_compatible(website_path, _path(c.get("homepage", "")))
                ]

    if not found:
        return None

    # Prefer the plain stable cask over any prerelease-channel variant.
    stable = [c for c in found if not _PRERELEASE_TOKEN.search(c.get("token", ""))]
    if not stable:
        log.info(
            "[%s] only prerelease Homebrew casks (%s); skipping",
            entry["id"], [c.get("token", "") for c in found],
        )
        return None
    found = stable

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

    result: dict[str, Any] = {"homebrew": token, **_status_fields(cask)}

    if url:
        name = url.rsplit("/", 1)[-1].split("?")[0] or f"{token}.dmg"
        # Tag the cask binary so which-electron treats it as a tier-0 candidate
        # (highest-confidence source) and fingerprints it before anything else.
        dl: dict[str, Any] = {"url": url, "name": name, "source": "homebrew"}
        if version:
            dl["version"] = version
        # Append to existing downloads rather than replacing
        existing = list(entry.get("downloads") or [])
        result["downloads"] = existing + [dl]

    return result
