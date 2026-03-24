# electronic-survey

A research tool to survey the Electron application ecosystem and measure the security update lag between:

- A bug being reported in Chromium
- A security fix landing in Electron
- That fix reaching end users via app releases

## Background

Electron apps are easy to build but hard to keep secure. Each shipped app bundles:

- A full Chromium runtime
- A copy of FFmpeg
- The Electron framework itself

This means Chromium CVEs don't automatically reach users — each app maintainer must upgrade their bundled Electron version. The gap between a CVE being fixed in Chromium and that fix reaching end users in a given Electron app can be weeks, months, or never.

Additionally, older Electron versions exposed a full Node.js environment in the renderer process, and there were at least 3 context isolation bypass vulnerabilities reported in 2020 alone, compounding the risk for apps that haven't upgraded.

## Goals

This project surveys a large corpus of Electron applications to answer:

1. What Electron versions are apps actually shipping?
2. How old are those versions relative to the latest Electron release?
3. How long does it take for a Chromium security fix to reach end users through the Electron update pipeline?

## Pipeline

```
repos/electron-apps/apps/   (upstream app registry)
         │
         ▼
  data/apps.yml             (extracted app metadata: id + repository URL)
         │
         ▼
  data/releases/            (fetched release data per app from GitHub)
         │
         ▼
  data/electron-versions/   (electron version bundled in each release)
         │
         ▼
  analysis/                 (CVE lag computation, statistics, charts)
```

## Usage

```bash
uv run main.py --help

# Extract app list from the electron-apps registry
uv run main.py extract-apps

# (future steps)
uv run main.py fetch-releases
uv run main.py analyze
```

## Data Sources

- [electron-apps](https://github.com/electron/electron-apps) — community registry of Electron applications
- [which-electron](https://github.com/captn3m0/which-electron) — tool to detect bundled Electron versions
- [electron-fingerprints](https://github.com/captn3m0/electron-fingerprints) — fingerprint database for Electron versions

## Requirements

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) for dependency management
