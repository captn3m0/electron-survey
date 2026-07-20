# electronic-survey

Measures the lag between Chromium security fixes and end users of Electron
applications receiving them.

Each bundled Electron release ships a pinned Chromium. App maintainers must
manually upgrade. This project tracks which Electron version each app ships,
cross-referenced against known CVE fix dates, to quantify that lag at scale.

## Data pipeline

    extract-apps            pull app registry into data/apps/
    fetch-versions          pull stable Electron release list from npm
    make all                build meta/ indexes (AUR, Homebrew, Electron headers)
    process github.com      fetch latest release + download links per app
    process homebrew        match Homebrew casks, add macOS download URLs
    process source          download source archives, detect from lockfiles
    process aur             find matching AUR packages
    process aur-version     read Electron major from AUR `electron<N>` depends
    process which-electron  fingerprint downloaded binaries (opt-in, downloads)
    dedupe                  drop entries duplicating another's repository
    stats                   summary counts
    report                  write REPORT.md

Detection is layered cheapest-first: lockfiles and AUR/Homebrew metadata cost
nothing per app, and `which-electron` (which downloads each binary) is the
last resort. Pass `--source-fast` to `process source` to skip apps that
already have a version. `which-electron` records a `we_tried` marker so a
binary is only re-fetched when a new release ships.

## Usage

    uv run main.py <command> [--help]

Set `GITHUB_TOKEN` to avoid rate limiting on the github.com processor.

## Data

- `data/apps/` — one YAML file per app, release metadata + detected Electron version
- `data/versions.txt` — all stable Electron releases
- `zips/` — cached source archives (not committed)
- `src/` — extracted source trees, cleaned up after each parse (not committed)

## Sources

- [electron/electron-apps](https://github.com/electron/electron-apps) — app registry (submodule)
- [which-electron](https://github.com/captn3m0/which-electron)
- [electron-fingerprints](https://github.com/captn3m0/electron-fingerprints)
