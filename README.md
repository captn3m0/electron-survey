# electronic-survey

Measures the lag between Chromium security fixes and end users of Electron
applications receiving them.

Each bundled Electron release ships a pinned Chromium. App maintainers must
manually upgrade. This project tracks which Electron version each app ships,
cross-referenced against known CVE fix dates, to quantify that lag at scale.

## Data pipeline

    extract-apps      pull app registry into data/apps.yml
    fetch-versions    pull stable Electron release list from npm
    process github.com  fetch latest release + download links per app
    process source    download source archives, detect bundled Electron version
    process --aur     find AUR packages for each app (manual, review before use)
    stats             summary counts

## Usage

    uv run main.py <command> [--help]

Set `GITHUB_TOKEN` to avoid rate limiting on the github.com processor.

## Data

- `data/apps.yml` — app list with release metadata and detected Electron version
- `data/versions.txt` — all stable Electron releases
- `zips/` — cached source archives (not committed)
- `src/` — extracted source trees (not committed)

## Sources

- [electron/electron-apps](https://github.com/electron/electron-apps) — app registry (submodule)
- [which-electron](https://github.com/captn3m0/which-electron)
- [electron-fingerprints](https://github.com/captn3m0/electron-fingerprints)
