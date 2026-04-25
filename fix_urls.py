#!/usr/bin/env python3
"""
fix_urls.py — correct invalid download URLs in data/zoo-extra.yml.

Applies a curated mapping of known-bad → known-good URLs (researched via
GitHub API and live HEAD checks).  After patching, removes the invalid/
invalid_reason flags for URLs that are now valid.

Usage:
    python3 fix_urls.py [--dry-run]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

DATA_FILE = Path(__file__).parent / "data" / "zoo-extra.yml"

# ---------------------------------------------------------------------------
# GITHUB REPO → LATEST ASSETS (fetched from API 2026-04-25)
# Keys: repo slug  Values: {tag, assets: [filename, ...]}
# ---------------------------------------------------------------------------
GITHUB_RELEASES = {
    "ferdium/ferdium-app": {
        "tag": "v7.1.2",
        "assets": [
            "Ferdium-linux-7.1.2-aarch64.rpm",
            "Ferdium-linux-7.1.2-amd64.deb",
            "Ferdium-linux-7.1.2-x86_64.rpm",
            "Ferdium-linux-Portable-7.1.2-x86_64.AppImage",
            "Ferdium-mac-7.1.2-arm64.dmg",
            "Ferdium-mac-7.1.2-x64.dmg",
            "Ferdium-win-AutoSetup-7.1.2-arm64.exe",
            "Ferdium-win-AutoSetup-7.1.2-x64.exe",
        ],
    },
    "Eugeny/tabby": {
        "tag": "v1.0.230",
        "assets": [
            "tabby-1.0.230-linux-arm64.AppImage",
            "tabby-1.0.230-linux-arm64.deb",
            "tabby-1.0.230-linux-arm64.rpm",
            "tabby-1.0.230-linux-x64.AppImage",
            "tabby-1.0.230-linux-x64.deb",
            "tabby-1.0.230-linux-x64.rpm",
            "tabby-1.0.230-macos-arm64.dmg",
            "tabby-1.0.230-macos-x86_64.dmg",
            "tabby-1.0.230-setup-arm64.exe",
            "tabby-1.0.230-setup-x64.exe",
        ],
    },
    "Kong/insomnia": {
        "tag": "core@12.5.0",
        "assets": [
            "Insomnia.Core-12.5.0.AppImage",
            "Insomnia.Core-12.5.0.deb",
            "Insomnia.Core-12.5.0.dmg",
            "Insomnia.Core-12.5.0.exe",
            "Insomnia.Core-12.5.0.rpm",
        ],
    },
    "laurent22/joplin": {
        "tag": "v3.5.13",
        "assets": [
            "Joplin-3.5.13-arm64.DMG",
            "Joplin-3.5.13.AppImage",
            "Joplin-3.5.13.deb",
            "Joplin-3.5.13.dmg",
            "Joplin-Setup-3.5.13.exe",
        ],
    },
    "standardnotes/app": {
        "tag": "@standardnotes/desktop@3.201.21",
        "assets": [
            "standard-notes-3.201.21-linux-amd64.deb",
            "standard-notes-3.201.21-linux-x86_64.AppImage",
            "standard-notes-3.201.21-mac-arm64.dmg",
            "standard-notes-3.201.21-mac-x64.dmg",
            "standard-notes-3.201.21-win-x64.exe",
        ],
    },
    "keeweb/keeweb": {
        "tag": "v1.18.7",
        "assets": [
            "KeeWeb-1.18.7.linux.AppImage",
            "KeeWeb-1.18.7.linux.x64.deb",
            "KeeWeb-1.18.7.linux.x64.zip",
            "KeeWeb-1.18.7.linux.x86_64.rpm",
            "KeeWeb-1.18.7.mac.arm64.dmg",
            "KeeWeb-1.18.7.mac.x64.dmg",
            "KeeWeb-1.18.7.win.arm64.exe",
            "KeeWeb-1.18.7.win.x64.exe",
        ],
    },
    "jgraph/drawio-desktop": {
        "tag": "v29.7.9",
        "assets": [
            "draw.io-29.7.9-windows-installer.exe",
            "draw.io-arm64-29.7.9-windows-arm64-installer.exe",
            "draw.io-arm64-29.7.9.dmg",
            "draw.io-universal-29.7.9.dmg",
            "draw.io-x64-29.7.9.dmg",
            "drawio-aarch64-29.7.9.rpm",
            "drawio-amd64-29.7.9.deb",
            "drawio-arm64-29.7.9.AppImage",
            "drawio-arm64-29.7.9.deb",
            "drawio-x86_64-29.7.9.AppImage",
            "drawio-x86_64-29.7.9.rpm",
        ],
    },
    "sindresorhus/caprine": {
        "tag": "v2.61.0",
        "assets": [
            "Caprine-2.61.0-arm64.dmg",
            "Caprine-2.61.0.AppImage",
            "Caprine-2.61.0.dmg",
            "Caprine-Setup-2.61.0.exe",
            "caprine_2.61.0_amd64.deb",
        ],
    },
    "RocketChat/Rocket.Chat.Electron": {
        "tag": "4.14.0",
        "assets": [
            "rocketchat-4.14.0-linux-amd64.deb",
            "rocketchat-4.14.0-linux-x86_64.AppImage",
            "rocketchat-4.14.0-linux-x86_64.rpm",
            "rocketchat-4.14.0-mac.dmg",
            "rocketchat-4.14.0-win-arm64.exe",
            "rocketchat-4.14.0-win-x64.exe",
        ],
    },
    "balena-io/etcher": {
        "tag": "v2.1.4",
        "assets": [
            "balena-etcher-2.1.4-1.x86_64.rpm",
            "balena-etcher_2.1.4_amd64.deb",
            "balenaEtcher-2.1.4-arm64.dmg",
            "balenaEtcher-2.1.4-x64.dmg",
            "balenaEtcher-2.1.4.Setup.exe",
        ],
    },
    "webtorrent/webtorrent-desktop": {
        "tag": "v0.24.0",
        "assets": [
            "WebTorrent-v0.24.0.dmg",
            "WebTorrentSetup-v0.24.0.exe",
            "webtorrent-desktop_0.24.0_amd64.deb",
        ],
    },
    "usebruno/bruno": {
        "tag": "v3.3.0",
        "assets": [
            "bruno_3.3.0_amd64_linux.deb",
            "bruno_3.3.0_arm64_linux.AppImage",
            "bruno_3.3.0_arm64_mac.dmg",
            "bruno_3.3.0_arm64_win.exe",
            "bruno_3.3.0_x64_mac.dmg",
            "bruno_3.3.0_x64_win.exe",
            "bruno_3.3.0_x86_64_linux.AppImage",
        ],
    },
    "logseq/logseq": {
        "tag": "0.10.15",
        "assets": [
            "Logseq-darwin-arm64-0.10.15.dmg",
            "Logseq-darwin-x64-0.10.15.dmg",
            "Logseq-linux-x64-0.10.15.AppImage",
            "Logseq-win-x64-0.10.15.exe",
        ],
    },
    "streetwriters/notesnook": {
        "tag": "v3.3.15",
        "assets": [
            "notesnook_linux_arm64.AppImage",
            "notesnook_linux_x86_64.AppImage",
            "notesnook_mac_arm64.dmg",
            "notesnook_mac_x64.dmg",
            "notesnook_win_x64.exe",
        ],
    },
    "Mastermindzh/tidal-hifi": {
        "tag": "6.3.1-Mavy",
        "assets": [
            "tidal-hifi-6.3.1-arm64.dmg",
            "tidal-hifi-6.3.1.AppImage",
            "tidal-hifi_6.3.1_amd64.deb",
            "tidal-hifi-6.3.1.x86_64.rpm",
        ],
    },
    "oxen-io/session-desktop": {
        "tag": "v1.14.3",
        "assets": [
            "session-desktop-linux-amd64-1.14.3.deb",
            "session-desktop-linux-x86_64-1.14.3.AppImage",
            "session-desktop-linux-x86_64-1.14.3.rpm",
            "session-desktop-mac-x64-1.14.3.dmg",
            "session-desktop-win-x64-1.14.3.exe",
        ],
    },
    "notable/notable": {
        "tag": "v1.8.4",
        "assets": [
            "Notable-1.8.4.AppImage",
            "Notable-1.8.4.dmg",
            "notable-1.8.4.x86_64.rpm",
            "Notable.Setup.1.8.4.exe",
            "notable_1.8.4_amd64.deb",
        ],
    },
    "kubernetes-sigs/headlamp": {
        "tag": "v0.41.0",
        "assets": [
            "Headlamp-0.41.0-linux-arm64.AppImage",
            "Headlamp-0.41.0-linux-x64.AppImage",
            "Headlamp-0.41.0-mac-arm64.dmg",
            "Headlamp-0.41.0-mac-x64.dmg",
            "Headlamp-0.41.0-win-x64.exe",
            "headlamp_0.41.0-1_amd64.deb",
        ],
    },
    "marktext/marktext": {
        "tag": "v0.17.1",
        "assets": [
            "marktext-amd64.deb",
            "marktext-arm64.dmg",
            "marktext-setup.exe",
            "marktext-x64.dmg",
            "marktext-x86_64.AppImage",
        ],
    },
    "agalwood/Motrix": {
        "tag": "v1.8.19",
        "assets": [
            "Motrix-1.8.19-arm64.dmg",
            "Motrix-1.8.19-x64.exe",
            "Motrix-1.8.19.AppImage",
            "Motrix-1.8.19.dmg",
            "Motrix-Setup-1.8.19.exe",
            "Motrix_1.8.19_amd64.deb",
        ],
    },
    "parsify-dev/desktop": {
        "tag": "v2.0.1",
        "assets": [
            "Parsify-2.0.1-linux-amd64.deb",
            "Parsify-2.0.1-linux-x86_64.AppImage",
            "Parsify-2.0.1-mac-arm64.dmg",
            "Parsify-2.0.1-mac-x64.dmg",
            "Parsify-2.0.1-win-x64.exe",
        ],
    },
    "hoppscotch/releases": {
        "tag": "v26.3.1-0",
        "assets": [
            "Hoppscotch_linux_x64.AppImage",
            "Hoppscotch_linux_x64.deb",
            "Hoppscotch_mac_aarch64.dmg",
            "Hoppscotch_mac_x64.dmg",
            "Hoppscotch_win_x64.msi",
        ],
    },
    "rizinorg/cutter": {
        "tag": "v2.4.1",
        "assets": [
            "Cutter-v2.4.1-Linux-x86_64.AppImage",
            "Cutter-v2.4.1-macOS-arm64.dmg",
            "Cutter-v2.4.1-macOS-x86_64.dmg",
            "Cutter-v2.4.1-Windows-x86_64.zip",
        ],
    },
    "ProtonMail/proton-bridge": {
        "tag": "v3.24.1",
        "assets": [
            "Bridge-Installer.dmg",
            "Bridge-Installer.exe",
            "protonmail-bridge-3.24.1-1.x86_64.rpm",
            "protonmail-bridge_3.24.1-1_amd64.deb",
        ],
    },
    "spacedriveapp/spacedrive": {
        "tag": "0.4.3",
        "assets": [
            "Spacedrive-darwin-aarch64.dmg",
            "Spacedrive-darwin-x86_64.dmg",
            "Spacedrive-linux-x86_64.deb",
            "Spacedrive-windows-x86_64.msi",
        ],
    },
    "Foundry376/Mailspring": {
        "tag": "1.20.1",
        "assets": [
            "mailspring-1.20.1-amd64.deb",
            "MailspringSetup.exe",
            "Mailspring.zip",
            "Mailspring-AppleSilicon.zip",
        ],
    },
    # versioned invalids
    "obsidianmd/obsidian-releases": {
        "tag": "v1.12.7",
        "assets": [
            "Obsidian-1.12.7-arm64.AppImage",
            "Obsidian-1.12.7.AppImage",
            "Obsidian-1.12.7.dmg",
            "Obsidian-1.12.7.exe",
            "obsidian_1.12.7_amd64.deb",
        ],
    },
    "meetfranz/franz": {
        "tag": "v5.11.0",
        "assets": [
            "Franz-5.11.0-arm64.dmg",
            "Franz-5.11.0.AppImage",
            "Franz-5.11.0.dmg",
            "Franz-Setup-5.11.0.exe",
            "franz_5.11.0_amd64.deb",
        ],
    },
    "electerm/electerm": {
        "tag": "v3.6.16",
        "assets": [
            "electerm-3.6.16-linux-amd64.deb",
            "electerm-3.6.16-linux-x86_64.AppImage",
            "electerm-3.6.16-mac-arm64.dmg",
            "electerm-3.6.16-mac-x64.dmg",
            "electerm-3.6.16-win-x64-installer.exe",
        ],
    },
    "altair-graphql/altair": {
        "tag": "v8.5.0",
        "assets": [
            "altair_8.5.0_amd64_linux.deb",
            "altair_8.5.0_arm64_linux.AppImage",
            "altair_8.5.0_arm64_mac.dmg",
            "altair_8.5.0_x64_mac.dmg",
            "altair_8.5.0_x64_win.exe",
            "altair_8.5.0_x86_64_linux.AppImage",
        ],
    },
    "buxuku/SmartSub": {
        "tag": "v2.15.0",
        "assets": [
            "SmartSub_Linux_2.15.0_amd64.deb",
            "SmartSub_Linux_2.15.0_x86_64.AppImage",
            "SmartSub_Mac_2.15.0_arm64.dmg",
            "SmartSub_Mac_2.15.0_x64.dmg",
            "SmartSub_Windows_2.15.0_x64.exe",
        ],
    },
    "bitwarden/clients": {
        "tag": "desktop-v2026.3.1",
        "assets": [
            "Bitwarden-2026.3.1-amd64.deb",
            "Bitwarden-2026.3.1-universal.dmg",
            "Bitwarden-2026.3.1-x86_64.AppImage",
            "Bitwarden-Installer-2026.3.1.exe",
        ],
    },
    # Atom is archived; v1.60.0 is the last release with assets
    "atom/atom": {
        "tag": "v1.60.0",
        "assets": [
            "AtomSetup-x64.exe",
            "atom-mac.zip",
            "atom-amd64.deb",
            "atom.x86_64.rpm",
            "atom-amd64.tar.gz",
        ],
    },
}

# ---------------------------------------------------------------------------
# DIRECT URL REPLACEMENTS (non-GitHub or special cases)
# ---------------------------------------------------------------------------
DIRECT_FIXES: dict[str, str | None] = {
    # Visual Studio Code – MSI installer removed from update server; no replacement
    "https://update.code.visualstudio.com/latest/win32-x64-msi/stable": None,
    "https://update.code.visualstudio.com/latest/win32-arm64-msi/stable": None,
    # VSCode zip archives on darwin – removed; no stable replacement
    "https://update.code.visualstudio.com/latest/darwin-x64-archive/stable": None,
    "https://update.code.visualstudio.com/latest/darwin-arm64-archive/stable": None,

    # Slack – MSI and new Linux paths
    "https://slack.com/ssb/download-win64-msi": None,  # MSI removed
    "https://downloads.slack-edge.com/desktop-releases/linux/x64/latest/slack-desktop-latest-amd64.deb": None,
    "https://downloads.slack-edge.com/desktop-releases/linux/x64/latest/slack-latest-x86_64.rpm": None,

    # Signal – apt repo index URL; not a download link – remove
    "https://updates.signal.org/desktop/apt/dists/xenial/main/binary-amd64/": None,

    # Postman – update to 64-bit endpoints (32-bit removed)
    "https://dl.pstmn.io/download/latest/win32": "https://dl.pstmn.io/download/latest/win64",
    "https://dl.pstmn.io/download/latest/linux32": "https://dl.pstmn.io/download/latest/linux64",

    # 1Password – updated URLs
    "https://downloads.1password.com/mac/1Password-latest.dmg":
        "https://downloads.1password.com/mac/1Password.pkg",
    "https://downloads.1password.com/linux/rpm/stable/x86_64/1password-latest.x86_64.rpm":
        "https://downloads.1password.com/linux/rpm/stable/x86_64/1password-latest.rpm",
    "https://downloads.1password.com/linux/tar/stable/x86_64/1password-latest.x86_64.tar.gz":
        "https://downloads.1password.com/linux/tar/stable/x86_64/1password-latest.tar.gz",

    # Notion – static CDN links (as of v7.12.0)
    "https://www.notion.so/desktop/windows/download/latest":
        "https://desktop-release.notion-static.com/Notion%20Setup%207.12.0.exe",
    "https://www.notion.so/desktop/mac/download/latest":
        "https://desktop-release.notion-static.com/Notion-7.12.0-universal.dmg",
    "https://www.notion.so/desktop/linux/download/latest": None,  # Notion has no Linux client

    # Microsoft Teams – no longer a standalone download page; remove
    "https://packages.microsoft.com/repos/ms-teams/pool/main/t/teams/": None,

    # Windsurf – URL scheme changed; remove outdated paths
    "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf/stable/latest/WindsurfSetup.exe": None,
    "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf/stable/latest/Windsurf.dmg": None,
    "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf/stable/latest/Windsurf.tar.gz": None,

    # Linear – no direct file download URLs available publicly; remove
    "https://desktop.linear.app/windows/installer/latest": None,
    "https://desktop.linear.app/mac/dmg/latest": None,

    # Bitwarden – use vault redirect URLs (302 → GitHub release)
    "https://vault.bitwarden.com/download/?app=desktop&platform=windows&variant=msi":
        "https://vault.bitwarden.com/download/?app=desktop&platform=windows",
    "https://vault.bitwarden.com/download/?app=desktop&platform=linux":
        "https://github.com/bitwarden/clients/releases/latest/download/Bitwarden-2026.3.1-amd64.deb",

    # Mailspring – HEAD returns 400 (API only); use GitHub releases directly
    "https://updates.getmailspring.com/download?platform=win":
        "https://github.com/Foundry376/Mailspring/releases/latest/download/MailspringSetup.exe",
    "https://updates.getmailspring.com/download?platform=mac":
        "https://github.com/Foundry376/Mailspring/releases/latest/download/Mailspring.zip",
    "https://updates.getmailspring.com/download?platform=linuxTarball":
        "https://github.com/Foundry376/Mailspring/releases/latest/download/mailspring-1.20.1-amd64.deb",

    # Camo – discontinued (Reincubate shut it down in 2023); remove
    "https://update.reincubate.com/camo/win/CamoSetup.exe": None,
    "https://update.reincubate.com/camo/mac/Camo.dmg": None,

    # Tot – macOS-only app, not Electron; remove from survey
    "https://tot.rocks/download": None,

    # Spacedrive – GitHub releases work; use /latest/download/ pattern
    "https://www.spacedrive.com/api/releases/desktop/stable/windows/x86_64":
        "https://github.com/spacedriveapp/spacedrive/releases/latest/download/Spacedrive-windows-x86_64.msi",
    "https://www.spacedrive.com/api/releases/desktop/stable/darwin/aarch64":
        "https://github.com/spacedriveapp/spacedrive/releases/latest/download/Spacedrive-darwin-aarch64.dmg",
    "https://www.spacedrive.com/api/releases/desktop/stable/darwin/x86_64":
        "https://github.com/spacedriveapp/spacedrive/releases/latest/download/Spacedrive-darwin-x86_64.dmg",
    "https://www.spacedrive.com/api/releases/desktop/stable/linux/x86_64":
        "https://github.com/spacedriveapp/spacedrive/releases/latest/download/Spacedrive-linux-x86_64.deb",

    # Enpass – apt CDN changed; no stable URL found; remove
    "https://apt.enpass.io/files/enpass_latest_amd64.deb": None,
    "https://rpm.enpass.io/enpass.repo": None,

    # Lens – lensapp/lens has no binary assets; OpenLens is the community fork
    "https://api.k8slens.dev/binaries/Lens%20Setup%20latest.exe":
        "https://github.com/MuhammedKalkan/OpenLens/releases/latest/download/OpenLens.6.5.2-366.exe",
    "https://api.k8slens.dev/binaries/Lens%20latest.dmg":
        "https://github.com/MuhammedKalkan/OpenLens/releases/latest/download/OpenLens-6.5.2-366.dmg",
    "https://api.k8slens.dev/binaries/Lens_latest_amd64.deb":
        "https://github.com/MuhammedKalkan/OpenLens/releases/latest/download/OpenLens-6.5.2-366.amd64.deb",
    "https://api.k8slens.dev/binaries/Lens-latest.x86_64.rpm":
        "https://github.com/MuhammedKalkan/OpenLens/releases/latest/download/OpenLens-6.5.2-366.x86_64.rpm",
    "https://api.k8slens.dev/binaries/Lens-latest.AppImage":
        "https://github.com/MuhammedKalkan/OpenLens/releases/latest/download/OpenLens-6.5.2-366.x86_64.AppImage",

    # Proton Bridge – use GitHub /latest/download/ (301 → asset)
    "https://proton.me/download/bridge/Proton_Mail_Bridge_Installer.exe":
        "https://github.com/ProtonMail/proton-bridge/releases/latest/download/Bridge-Installer.exe",
    "https://proton.me/download/bridge/Proton_Mail_Bridge.dmg":
        "https://github.com/ProtonMail/proton-bridge/releases/latest/download/Bridge-Installer.dmg",
    "https://proton.me/download/bridge/protonmail-bridge_amd64.deb":
        "https://github.com/ProtonMail/proton-bridge/releases/latest/download/protonmail-bridge_3.24.1-1_amd64.deb",
    "https://proton.me/download/bridge/protonmail-bridge.x86_64.rpm":
        "https://github.com/ProtonMail/proton-bridge/releases/latest/download/protonmail-bridge-3.24.1-1.x86_64.rpm",

    # Hyper – snap URL broken; remove (snap/AppImage not tracked in survey)
    "https://releases.hyper.is/download/snap": None,

    # Koofr – CDN gone; no working alternative found; remove
    "https://k2.koofr.eu/dl/koofr-desktop-latest-win-setup.exe": None,
    "https://k2.koofr.eu/dl/koofr-desktop-latest-mac.dmg": None,
    "https://k2.koofr.eu/dl/koofr-desktop-latest-linux-amd64.deb": None,
    "https://k2.koofr.eu/dl/koofr-desktop-latest-linux-x64.tar.gz": None,

    # Sidekick – browser discontinued in 2023; remove
    "https://api.meetsidekick.com/download/latest/win": None,
    "https://api.meetsidekick.com/download/latest/mac": None,
    "https://api.meetsidekick.com/download/latest/linux": None,

    # Typora – download domain is downloads.typora.io (not download.)
    "https://download.typora.io/windows/x64/typora-setup-x64.exe":
        "https://downloads.typora.io/windows/x64/typora-setup-x64.exe",
    "https://download.typora.io/windows/arm64/typora-setup-arm64.exe":
        "https://downloads.typora.io/windows/arm64/typora-setup-arm64.exe",

    # Publii – CDN changed to cdn.getpublii.com
    "https://getpublii.com/download/Publii-0.47.6.dmg":
        "https://cdn.getpublii.com/Publii-0.47.6-intel.dmg",
    "https://getpublii.com/download/Publii-0.47.6-win.exe":
        "https://cdn.getpublii.com/Publii-0.47.6.exe",

    # GitKraken – release CDN moved to api.gitkraken.dev (only macOS arm64 confirmed working)
    "https://release.axocdn.com/win64/GitKrakenSetup.exe": None,
    "https://release.axocdn.com/darwin/GitKraken.dmg":
        "https://api.gitkraken.dev/releases/production/darwin/arm64/12.0.1/GitKraken-v12.0.1.zip",
    "https://release.axocdn.com/linux/gitkraken-amd64.deb": None,
    "https://release.axocdn.com/linux/gitkraken-amd64.rpm": None,

    # atom/atom – repo archived December 2022; v1.63.1 tag has no assets;
    # point to last working release v1.60.0 assets
    "https://github.com/atom/atom/releases/download/v1.63.1/AtomSetup-x64.exe":
        "https://github.com/atom/atom/releases/download/v1.60.0/AtomSetup-x64.exe",
    "https://github.com/atom/atom/releases/download/v1.63.1/atom-x64-1.63.1-full.nupkg": None,
    "https://github.com/atom/atom/releases/download/v1.63.1/atom-mac.zip":
        "https://github.com/atom/atom/releases/download/v1.60.0/atom-mac.zip",
    "https://github.com/atom/atom/releases/download/v1.63.1/atom-amd64.deb":
        "https://github.com/atom/atom/releases/download/v1.60.0/atom-amd64.deb",
    "https://github.com/atom/atom/releases/download/v1.63.1/atom.x86_64.rpm":
        "https://github.com/atom/atom/releases/download/v1.60.0/atom.x86_64.rpm",
    "https://github.com/atom/atom/releases/download/v1.63.1/atom-amd64.tar.gz":
        "https://github.com/atom/atom/releases/download/v1.60.0/atom-amd64.tar.gz",

    # revell29/excalidraw-desktop – repo deleted; no alternative found; remove
    "https://github.com/revell29/excalidraw-desktop/releases/latest/download/Excalidraw-Setup.exe": None,
    "https://github.com/revell29/excalidraw-desktop/releases/latest/download/Excalidraw.dmg": None,

    # nicholasgasior/klack – repo deleted; macOS-only app anyway; remove
    "https://github.com/nicholasgasior/klack/releases/latest/download/Klack.dmg": None,

    # suchnsuch/Tangent – repo gone; remove
    "https://github.com/suchnsuch/Tangent/releases/latest/download/Tangent-win32.exe": None,
    "https://github.com/suchnsuch/Tangent/releases/latest/download/Tangent-mac.dmg": None,
    "https://github.com/suchnsuch/Tangent/releases/latest/download/Tangent-linux.AppImage": None,

    # nickvdyck/volta – repo gone; remove
    "https://github.com/nickvdyck/volta/releases/latest/download/Volta-Setup.exe": None,
    "https://github.com/nickvdyck/volta/releases/latest/download/Volta.dmg": None,

    # acheronfail/codeshot – repo gone; remove
    "https://github.com/acheronfail/codeshot/releases/latest/download/CodeShot.dmg": None,

    # responsively-org/responsively-app – latest release has no binary assets; remove
    "https://github.com/responsively-org/responsively-app/releases/latest/download/ResponsivelyApp-Setup.exe": None,
    "https://github.com/responsively-org/responsively-app/releases/latest/download/ResponsivelyApp.dmg": None,
    "https://github.com/responsively-org/responsively-app/releases/latest/download/ResponsivelyApp.AppImage": None,

    # nbonamy/witsy – repo not found; remove (handled above but ensure coverage)
    # theodi/comma-chameleon – 0.5.2 tag gone; use 0.5.1
    "https://github.com/theodi/comma-chameleon/releases/download/0.5.2/Comma.Chameleon-linux-x64.tar.gz":
        "https://github.com/theodi/comma-chameleon/releases/download/0.5.1/comma-chameleon-linux-x64.tar.gz",


    # Headlamp – repo moved
    "https://github.com/headlamp-k8s/headlamp/releases/latest/download/Headlamp-win-x64.exe":
        "https://github.com/kubernetes-sigs/headlamp/releases/latest/download/Headlamp-0.41.0-win-x64.exe",
    "https://github.com/headlamp-k8s/headlamp/releases/latest/download/Headlamp-mac-x64.dmg":
        "https://github.com/kubernetes-sigs/headlamp/releases/latest/download/Headlamp-0.41.0-mac-x64.dmg",
    "https://github.com/headlamp-k8s/headlamp/releases/latest/download/Headlamp-mac-arm64.dmg":
        "https://github.com/kubernetes-sigs/headlamp/releases/latest/download/Headlamp-0.41.0-mac-arm64.dmg",
    "https://github.com/headlamp-k8s/headlamp/releases/latest/download/Headlamp-linux-x64.AppImage":
        "https://github.com/kubernetes-sigs/headlamp/releases/latest/download/Headlamp-0.41.0-linux-x64.AppImage",
    "https://github.com/headlamp-k8s/headlamp/releases/latest/download/Headlamp-linux-x64.tar.gz":
        "https://github.com/kubernetes-sigs/headlamp/releases/latest/download/Headlamp-0.41.0-linux-x64.tar.gz",

    # Witsy – release v3.5.2 repo moved or removed; no new assets found
    "https://github.com/nbonamy/witsy/releases/download/v3.5.2/Witsy-3.5.2-darwin-arm64.dmg": None,
    "https://github.com/nbonamy/witsy/releases/download/v3.5.2/Witsy-3.5.2-darwin-x64.dmg": None,
    "https://github.com/nbonamy/witsy/releases/download/v3.5.2/Witsy-3.5.2-win32-x64-setup.exe": None,
    "https://github.com/nbonamy/witsy/releases/download/v3.5.2/Witsy-3.5.2-linux-x64.AppImage": None,

    # notesnook – no linux deb in v3.3.15; use AppImage instead
    "https://github.com/streetwriters/notesnook/releases/latest/download/notesnook_linux_amd64.deb":
        "https://github.com/streetwriters/notesnook/releases/latest/download/notesnook_linux_x86_64.AppImage",

    # zz85/space-radar – v6.0.1 x64 DMG gone; only ARM available
    "https://github.com/zz85/space-radar/releases/download/v6.0.1/stable-macos-x64-SpaceRadar.dmg": None,

    # ferdium – arm64 AppImage not available in v7.1.2; remove
    "https://github.com/ferdium/ferdium-app/releases/latest/download/Ferdium-6.7.4-arm64.AppImage": None,

    # insomnia – filename pattern changed to Insomnia.Core-X.X.X; add direct fixes
    "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.Setup.exe":
        "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.Core-12.5.0.exe",
    "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.dmg":
        "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.Core-12.5.0.dmg",
    "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.AppImage":
        "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.Core-12.5.0.AppImage",
    "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.deb":
        "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.Core-12.5.0.deb",
    "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.rpm":
        "https://github.com/Kong/insomnia/releases/latest/download/Insomnia.Core-12.5.0.rpm",

    # bruno – rpm renamed
    "https://github.com/usebruno/bruno/releases/latest/download/bruno_linux_amd64.rpm":
        "https://github.com/usebruno/bruno/releases/latest/download/bruno_3.3.0_x86_64_linux.rpm",

    # hoppscotch – win exe replaced by msi
    "https://github.com/hoppscotch/releases/releases/latest/download/Hoppscotch_win_x64.exe":
        "https://github.com/hoppscotch/releases/releases/latest/download/Hoppscotch_win_x64.msi",
    "https://github.com/hoppscotch/releases/releases/latest/download/Hoppscotch_mac_universal.dmg":
        "https://github.com/hoppscotch/releases/releases/latest/download/Hoppscotch_mac_x64.dmg",

    # balenaetcher – AppImage not available in v2.1.4; remove
    "https://github.com/balena-io/etcher/releases/latest/download/balenaEtcher-x64.AppImage": None,

    # tidal-hifi – Windows exe removed in 6.x; remove
    "https://github.com/Mastermindzh/tidal-hifi/releases/latest/download/tidal-hifi-setup.exe": None,

    # Discord – API only accepts platform=win now; use direct CDN URLs
    "https://discord.com/api/downloads/distributions/app/installers/latest?channel=stable&platform=osx":
        "https://stable.dl2.discordapp.net/apps/osx/0.0.387/Discord.dmg",
    "https://discord.com/api/downloads/distributions/app/installers/latest?channel=stable&platform=linux&format=deb":
        "https://stable.dl2.discordapp.net/apps/linux/0.0.134/discord-0.0.134.deb",
    "https://discord.com/api/downloads/distributions/app/installers/latest?channel=stable&platform=linux&format=tar.gz":
        "https://stable.dl2.discordapp.net/apps/linux/0.0.134/discord-0.0.134.tar.gz",
    "https://discord.com/api/downloads/distributions/app/installers/latest?channel=stable&platform=linux&format=rpm":
        None,  # no rpm on CDN

    # Wire – filename changed (exe) and linux dists URL is an apt repo index
    "https://wire-app.wire.com/win/prod/Wire.exe":
        "https://wire-app.wire.com/win/prod/Wire-Setup.exe",
    "https://wire-app.wire.com/mac/prod/Wire.dmg": None,  # CDN returns 403; no working URL
    "https://wire-app.wire.com/linux/debian/dists/stable/main/binary-amd64/":
        "https://wire-app.wire.com/linux/Wire-3.36.3462_amd64.deb",

    # Miro – URL path changed
    "https://desktop.miro.com/platforms/win32-x86_64/Miro.exe":
        "https://desktop.miro.com/platforms/win32-nsis-pu/Miro-setup.exe",

    # Keybase – Windows installer returns 403; no working URL found; remove
    "https://prerelease.keybase.io/keybase_production_amd64_installer.exe": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ext(filename: str) -> str:
    fname = filename.lower()
    for ext in [".appimage", ".tar.gz", ".dmg", ".deb", ".rpm", ".exe", ".msi", ".zip", ".pkg"]:
        if fname.endswith(ext):
            return ext
    return ""


def _contains_word(text: str, word: str) -> bool:
    """Check if *word* appears as a whole token (bounded by non-alphanum)."""
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text))


def _score_asset(asset: str, pkg: dict) -> int:
    """Higher score = better match for the given package spec."""
    score = 0
    a = asset.lower()
    fmt = pkg.get("format", "").lower()
    os_ = pkg.get("os", "").lower()
    arch = pkg.get("arch", "").lower()

    # extension must match format
    ext_map = {
        "exe": ".exe", "msi": ".msi", "dmg": ".dmg", "deb": ".deb",
        "rpm": ".rpm", "appimage": ".appimage", "zip": ".zip",
        "tar.gz": ".tar.gz", "pkg": ".pkg",
    }
    required_ext = ext_map.get(fmt)
    if required_ext and not a.endswith(required_ext.lower()):
        return -1  # extension mismatch

    # OS match
    os_keywords = {
        "windows": ["win", "windows", "setup", "installer"],
        "macos": ["mac", "macos", "darwin", "dmg", "osx"],
        "linux": ["linux", "amd64", "deb", "rpm", "appimage", "x86_64", "x64"],
    }
    for kw in os_keywords.get(os_, []):
        if kw in a:
            score += 2

    # arch match – use whole-token matching to avoid "64" matching "arm64"
    arch_keywords = {
        "x64": ["x64", "x86_64", "amd64", "win64"],
        "arm64": ["arm64", "aarch64", "apple-silicon"],
        "arm": ["armv7", "armhf"],
        "universal": ["universal"],
        "ia32": ["ia32", "i386"],
    }
    if arch:
        for kw in arch_keywords.get(arch, []):
            if _contains_word(a, kw):
                score += 3
        # penalise wrong arch
        if arch == "x64" and any(_contains_word(a, k) for k in ("arm64", "aarch64", "arm")):
            score -= 5
        if arch == "arm64" and any(_contains_word(a, k) for k in ("x64", "x86_64", "amd64", "ia32")):
            score -= 5
    else:
        # No arch specified – prefer x64/amd64/universal over arm64
        if any(_contains_word(a, k) for k in ("x64", "x86_64", "amd64", "universal")):
            score += 1
        if any(_contains_word(a, k) for k in ("arm64", "aarch64")):
            score -= 1

    # prefer shorter filenames (less "legacy", "bundle", etc.)
    score -= len(a) // 20
    for bad in ("portable", "legacy", "bundle", "debug", "unpacked", "nsis",
                "update", "delta", "blockmap"):
        if bad in a:
            score -= 2

    return score


def best_asset(assets: list[str], pkg: dict) -> str | None:
    """Return the best-matching asset filename for the given package spec."""
    candidates = [(a, _score_asset(a, pkg)) for a in assets]
    candidates = [(a, s) for a, s in candidates if s >= 0]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[1])[0]


def github_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/latest/download/{filename}"


# ---------------------------------------------------------------------------
# Main fix logic
# ---------------------------------------------------------------------------

def build_url_map() -> dict[str, str | None]:
    """Build old→new mapping for all known GitHub release invalids."""
    url_map: dict[str, str | None] = dict(DIRECT_FIXES)

    for repo, info in GITHUB_RELEASES.items():
        tag = info["tag"]
        assets = info["assets"]

        # Build per-package score map
        # We need to resolve current invalid package entries for this repo
        # The actual matching happens per-package in apply_fixes()
        url_map[f"__repo__{repo}"] = f"__assets__{','.join(assets)}"

    return url_map


def apply_fixes(data: list[dict], dry_run: bool) -> tuple[int, int, int]:
    """
    Apply URL fixes in-place on data.
    Returns (fixed, removed, unchanged) counts.
    """
    fixed = removed = unchanged = 0

    for app in data:
        new_packages = []
        for pkg in app.get("packages", []):
            if not pkg.get("invalid"):
                new_packages.append(pkg)
                continue

            url = pkg["url"]

            # 1. Direct fix?
            if url in DIRECT_FIXES:
                new_url = DIRECT_FIXES[url]
                if new_url is None:
                    print(f"  REMOVE  [{app['id']}] {url}")
                    if not dry_run:
                        removed += 1
                        continue  # drop the package
                else:
                    print(f"  FIX     [{app['id']}] {url}\n          → {new_url}")
                    if not dry_run:
                        pkg["url"] = new_url
                        pkg.pop("invalid", None)
                        pkg.pop("invalid_reason", None)
                        fixed += 1
                    new_packages.append(pkg)
                continue

            # 2. GitHub /releases/latest/download/ or /releases/download/vX/  ?
            m = re.match(
                r"https://github\.com/([^/]+/[^/]+)/releases/(?:latest/download|download/[^/]+)/(.*)",
                url,
            )
            if m:
                repo = m.group(1)
                old_filename = m.group(2)

                # Normalise repo case for lookup
                repo_key = next(
                    (k for k in GITHUB_RELEASES if k.lower() == repo.lower()), None
                )
                if repo_key:
                    info = GITHUB_RELEASES[repo_key]
                    new_fname = best_asset(info["assets"], pkg)
                    if new_fname:
                        new_url = github_url(repo_key, info["tag"], new_fname)
                        print(f"  FIX     [{app['id']}] {old_filename}\n          → {new_fname}")
                        if not dry_run:
                            pkg["url"] = new_url
                            pkg.pop("invalid", None)
                            pkg.pop("invalid_reason", None)
                            fixed += 1
                        new_packages.append(pkg)
                        continue
                    else:
                        print(f"  NOASSET [{app['id']}] {url}")
                        unchanged += 1
                else:
                    print(f"  NOREPO  [{app['id']}] {repo} not in GITHUB_RELEASES")
                    unchanged += 1

            else:
                print(f"  SKIP    [{app['id']}] {url}")
                unchanged += 1

            new_packages.append(pkg)

        app["packages"] = new_packages

    return fixed, removed, unchanged


def load_data(path: Path):
    raw = path.read_text()
    header = "".join(l for l in raw.splitlines(keepends=True) if l.startswith("#"))
    no_comments = "".join(l for l in raw.splitlines(keepends=True) if not l.startswith("#"))
    data = [d for d in (yaml.safe_load(no_comments) or []) if d]
    return data, header


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data, header = load_data(DATA_FILE)

    total_invalid_before = sum(1 for a in data for p in a.get("packages", []) if p.get("invalid"))
    print(f"Invalid packages before fix: {total_invalid_before}\n")

    fixed, removed, unchanged = apply_fixes(data, args.dry_run)

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Results:")
    print(f"  Fixed   : {fixed}")
    print(f"  Removed : {removed}")
    print(f"  Skipped : {unchanged}")

    if not args.dry_run:
        dumped = yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )
        DATA_FILE.write_text(header + dumped)
        total_invalid_after = sum(1 for a in data for p in a.get("packages", []) if p.get("invalid"))
        print(f"\nInvalid packages remaining: {total_invalid_after}")
        print(f"Written to {DATA_FILE}")


if __name__ == "__main__":
    main()
