"""Probe the artefacts which-electron would download, without downloading them.

An app can sit unresolved forever without anything in the data saying why: the
fingerprinter claims it every run, every download fails, and it is re-queued
unchanged. This makes that visible — it asks for the first couple of kilobytes
of each candidate artefact and reports which apps have nothing fetchable.

    uv run main.py download-audit
    uv run main.py download-audit --tier flagship,popular --workers 8

Read-only: it never writes to data/apps/. Findings are data-quality work
(a stale curated `packages` URL, a vendor that moved its CDN), not something
the pipeline can fix by itself.

Use a ranged GET rather than HEAD: several vendors answer HEAD with 403/404
while serving the file perfectly over GET, and the real downloader only ever
issues a GET. A HEAD-based audit reports failures that do not exist.
"""

import collections
import importlib.util
import pathlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import click
import requests
import yaml

from commands import DATA_DIR, cli, load_apps

_STEP = pathlib.Path("steps/which-electron.py")
# Enough to tell "the server is serving this file" from an error page.
_PROBE_BYTES = 2048


def _load_step() -> Any:
    """Load steps/which-electron.py, whose filename isn't importable."""
    spec = importlib.util.spec_from_file_location("step_which_electron", _STEP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe(session: requests.Session, url: str) -> tuple[bool, str]:
    try:
        with session.get(
            url, stream=True, timeout=30, allow_redirects=True,
            headers={"Range": f"bytes=0-{_PROBE_BYTES - 1}"},
        ) as r:
            if r.status_code >= 400:
                return False, f"HTTP {r.status_code}"
            got = len(next(r.iter_content(_PROBE_BYTES), b""))
            if not got:
                return False, "empty response"
            return True, f"HTTP {r.status_code}"
    except requests.RequestException as exc:
        return False, type(exc).__name__


@cli.command("download-audit")
@click.option("--tier", default="", help="Comma-separated tiers to limit the audit to.")
@click.option("--limit", default=0, help="Stop after this many apps (0 = no limit).")
@click.option("--workers", default=8, show_default=True, help="Concurrent probes.")
def download_audit(tier: str, limit: int, workers: int) -> None:
    """Report apps whose which-electron artefacts cannot be downloaded."""
    step = _load_step()

    scores: dict[str, dict] = {}
    pop = DATA_DIR / "popularity.yml"
    if pop.exists():
        scores = (yaml.safe_load(pop.read_text()) or {}).get("scores", {})

    wanted = {t.strip() for t in tier.split(",") if t.strip()}
    apps = [a for a in load_apps() if step.matches(a)]
    if wanted:
        apps = [a for a in apps if scores.get(a["id"], {}).get("tier") in wanted]
    apps.sort(key=lambda a: scores.get(a["id"], {}).get("reach", 0.0), reverse=True)
    if limit:
        apps = apps[:limit]

    session = requests.Session()
    session.headers["User-Agent"] = step._SESSION.headers["User-Agent"]

    def check(app: dict) -> tuple[str, str, list[tuple[str, str]]]:
        results = [(u, *_probe(session, u)) for u in step._candidate_urls(app)]
        reachable = [u for u, ok, _ in results if ok]
        state = "ok" if reachable else "unreachable"
        return state, app["id"], [(u, why) for u, ok, why in results if not ok]

    click.echo(f"Probing {len(apps)} apps queued for which-electron…")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        findings = list(pool.map(check, apps))

    counts = collections.Counter(state for state, _, _ in findings)
    stuck = [(app_id, fails) for state, app_id, fails in findings if state == "unreachable"]

    for app_id, fails in sorted(stuck):
        tier_label = scores.get(app_id, {}).get("tier", "unranked")
        click.echo(f"\n{app_id}  [{tier_label}] — nothing fetchable")
        for url, why in fails:
            click.echo(f"    {why:20s} {url}")

    click.echo(
        f"\n{counts['ok']} ok, {len(stuck)} with no fetchable artefact. "
        "The latter will be retried every run and never resolve until their "
        "download URLs are corrected."
    )
