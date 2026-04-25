#!/usr/bin/env python3
"""
validate_urls.py — HEAD-check every download URL in data/zoo-extra.yml.

Invalid packages (non-2xx/3xx response, network error, or explicit 404/4xx)
are marked with  invalid: true  in the YAML in-place.
A summary table is printed at the end.

Usage:
    python3 validate_urls.py [--workers N] [--timeout S] [--dry-run]

Options:
    --workers N   Parallel workers (default: 20)
    --timeout S   Per-request timeout in seconds (default: 15)
    --dry-run     Report results without modifying the YAML file
"""

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

DATA_FILE = Path(__file__).parent / "data" / "zoo-extra.yml"
GOOD_CODES = {200, 201, 202, 203, 204, 206, 301, 302, 303, 307, 308}


def head_check(url: str, timeout: int) -> tuple[str, int | None, str | None]:
    """Run `curl -sI` on *url* and return (url, http_status, error_msg)."""
    try:
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--head",
                "--location",           # follow redirects
                "--max-redirs", "5",
                "--connect-timeout", str(timeout),
                "--max-time", str(timeout * 2),
                "--write-out", "%{http_code}",
                "--output", "/dev/null",
                "--user-agent", "Mozilla/5.0 (validate_urls/1.0)",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout * 3,
        )
        code_str = result.stdout.strip()
        code = int(code_str) if code_str.isdigit() else None
        if code is None:
            return url, None, f"unexpected output: {result.stdout!r}"
        return url, code, None
    except subprocess.TimeoutExpired:
        return url, None, "timeout"
    except Exception as exc:
        return url, None, str(exc)


def load_data(path: Path) -> tuple[list[dict], str]:
    """Load YAML preserving the raw text so we can do a surgical rewrite."""
    raw = path.read_text()
    # Strip leading comment lines before parsing (same pattern as rest of project)
    no_comments = "".join(
        line for line in raw.splitlines(keepends=True) if not line.startswith("#")
    )
    data = [d for d in (yaml.safe_load(no_comments) or []) if d]
    return data, raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=20,
                        help="Parallel workers (default: 20)")
    parser.add_argument("--timeout", type=int, default=15,
                        help="Per-request timeout in seconds (default: 15)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report results without modifying the YAML file")
    args = parser.parse_args()

    data, _ = load_data(DATA_FILE)

    # Collect all (app_id, pkg_index, url) triples
    tasks: list[tuple[str, int, str]] = []
    for app in data:
        for idx, pkg in enumerate(app.get("packages", [])):
            tasks.append((app["id"], idx, pkg["url"]))

    total = len(tasks)
    print(f"Checking {total} URLs across {len(data)} apps with {args.workers} workers…\n")

    results: dict[str, tuple[int | None, str | None]] = {}  # url -> (code, error)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(head_check, url, args.timeout): url for _, _, url in tasks}
        done = 0
        for future in as_completed(futures):
            url, code, err = future.result()
            results[url] = (code, err)
            done += 1
            status = f"HTTP {code}" if code else f"ERR  {err}"
            marker = "✓" if code in GOOD_CODES else "✗"
            print(f"  [{done:4}/{total}] {marker} {status:12}  {url}", flush=True)

    # ── Compute stats ──────────────────────────────────────────────────────────
    ok = sum(1 for c, _ in results.values() if c in GOOD_CODES)
    bad_4xx = sum(1 for c, _ in results.values() if c is not None and 400 <= c < 500)
    bad_5xx = sum(1 for c, _ in results.values() if c is not None and c >= 500)
    errs = sum(1 for c, _ in results.values() if c is None)

    invalid_urls: set[str] = {
        url for url, (code, err) in results.items()
        if code not in GOOD_CODES
    }

    print("\n" + "═" * 70)
    print("VALIDATION SUMMARY")
    print("═" * 70)
    print(f"  Total URLs checked : {total}")
    print(f"  ✓ Valid (2xx/3xx)  : {ok}  ({ok/total*100:.1f}%)")
    print(f"  ✗ 4xx errors       : {bad_4xx}")
    print(f"  ✗ 5xx errors       : {bad_5xx}")
    print(f"  ✗ Network/timeout  : {errs}")
    print(f"  ✗ Total invalid    : {len(invalid_urls)}  ({len(invalid_urls)/total*100:.1f}%)")
    print("═" * 70)

    if invalid_urls:
        print("\nINVALID URLs:")
        for app in data:
            for pkg in app.get("packages", []):
                url = pkg["url"]
                if url in invalid_urls:
                    code, err = results[url]
                    reason = f"HTTP {code}" if code else err
                    print(f"  [{app['id']}]  {reason}  {url}")

    if args.dry_run:
        print("\n--dry-run: YAML not modified.")
        return

    if not invalid_urls:
        print("\nAll URLs valid — no changes needed.")
        return

    # ── Mark invalids in the YAML ──────────────────────────────────────────────
    # We patch the in-memory data and dump it, keeping comment header lines.
    raw = DATA_FILE.read_text()
    # Collect header comments at the top
    header_lines: list[str] = []
    for line in raw.splitlines(keepends=True):
        if line.startswith("#"):
            header_lines.append(line)
        else:
            break
    header = "".join(header_lines)

    # Patch in-memory
    for app in data:
        for pkg in app.get("packages", []):
            url = pkg["url"]
            if url in invalid_urls:
                code, err = results[url]
                pkg["invalid"] = True
                pkg["invalid_reason"] = f"HTTP {code}" if code else str(err)
            else:
                # Remove stale markers if previously invalid but now valid
                pkg.pop("invalid", None)
                pkg.pop("invalid_reason", None)

    dumped = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    DATA_FILE.write_text(header + dumped)
    print(f"\nMarked {len(invalid_urls)} invalid URLs in {DATA_FILE}.")


if __name__ == "__main__":
    main()
