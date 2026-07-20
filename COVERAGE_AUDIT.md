# Coverage Audit — Popular / Proprietary Electron Desktop Apps

Date: 2026-07-20
Dataset size: 899 app files under `data/apps/` (5 new stubs added by this audit).
Electron reference (latest stable, from `data/versions.txt`): **43.1.1** (2026-07-14) / **42.7.0** (2026-07-15). Supported majors in the wild: 41–43.

## Summary counts

| Verdict | Count | Apps |
|---|---|---|
| OK (matches / plausibly current) | 19 | 1Password, Discord, Obsidian, Loom, Beeper, Linear, Asana, Element, Bitwarden, Notion Calendar, balenaEtcher, Franz, MongoDB Compass, Insomnia, Mattermost, Ferdium, Logseq, Hyper, Caprine |
| STALE — confirmed (ours older than truth) | 8 | VS Code, Slack, Signal, Standard Notes, Tabby, GitHub Desktop, Joplin, Notion |
| STALE / suspect — unverified (aur-depends artifact or abandoned) | 6 | Postman, Trello, Station, Keybase, Cursor, Wire |
| UNDETECTED (in dataset, no `electron`) | 4 | Figma, Twitch, Windsurf, Shift |
| WRONG (detected but implausible) | 1 | Atom (1.1.1; app is discontinued) |
| MISSING → stub created | 5 | Ledger Live, Proton Mail, ClickUp, Termius, Todoist |
| N/A — not Electron (or retired) | 8 | Spotify, Zoom, Telegram Desktop, Docker Desktop, WhatsApp*, Microsoft Teams*, Skype*, Around |

\* In dataset as `dead: true` — correct, because these moved off Electron (Teams/WhatsApp → WebView2) or were retired (Skype, May 2025).

## Headline findings

1. **Systemic `aur-depends` error on apps that bundle their own Electron.** Four entries report **exactly `electron: 39.8.3`** via `aur-depends` — `slack`, `notion`, `visual-studio-code`, `karaokemugen`. That value is the current **Arch `electron` package version**, i.e. the version the *community AUR repackage* links against, **not** the Electron each vendor actually bundles. Confirmed wrong-low:
   - **Slack** ships **43.1.1** (Slack 4.51.180, 2026-07-15) — ours says 39.8.3.
   - **VS Code** ships **42.6.0** (VS Code 1.129, 2026-07) — ours says 39.8.3.
   - **Notion** almost certainly ships newer than 39.8.3 for the same reason (bundled build, current app 7.26.0).
   Recommendation: for proprietary apps, prefer `which-electron-rg` over `aur-depends`.

2. **Severely stale source-based detections.** Several `src-*` detections resolved a very old tag/lockfile:
   - **Signal**: ours **23.3.13** vs truth **42.3.0** (Signal-Desktop v8.19.0 `package.json`).
   - **Standard Notes**: ours **17.4.2** vs truth **35.2.0** (`packages/desktop/package.json` @ 3.201.21).
   - **Tabby**: ours **7.1.7** vs truth **38** (Eugeny/tabby v1.0.234 `package.json`).
   - **GitHub Desktop**: ours **40.1.0** vs truth **42.0.1** (desktop/desktop release-3.6.3).
   - **Joplin**: ours **39.2.3** vs truth **40.8.3** (laurent22/joplin v3.6.15).

3. **Undetected but genuinely Electron:** **Figma** (has `downloads`/homebrew but no `electron`; confirmed Electron), **Windsurf** (VS Code fork, Electron), **Shift** (has a download + `we_tried` marker), **Twitch** (only an AUR entry, no download source; Electron applicability uncertain). All should be fingerprintable via `which-electron`.

4. **Biggest MISSING popular apps** (stubs created): **Ledger Live**, **Proton Mail**, **ClickUp**, **Termius**, **Todoist**.

5. **Not Electron — correctly absent / flagged:** Spotify (Chromium Embedded Framework, not Electron), Zoom, Telegram Desktop (Qt), Docker Desktop. Around was Electron but discontinued (acquired by Miro).

## Detailed table

| App | id | ours (ver / method) | ground-truth ver | source(s) | verdict |
|---|---|---|---|---|---|
| 1Password | 1password | 42.2.0 / which-electron-rg | ~42 (current) | binary fingerprint of current build | OK |
| Slack | slack | 39.8.3 / aur-depends | **43.1.1** | felixrieseberg gist (Slack 4.51.180); 2026 audit | **STALE** |
| Spotify | — (absent) | — | n/a (CEF) | codenote 2026 audit; well-known | N/A |
| Discord | discord | 37.6.0 / which-electron-rg | ~37 (fingerprint) | binary fingerprint | OK |
| Visual Studio Code | visual-studio-code | 39.8.3 / aur-depends | **42.6.0** | ewanharris/vscode-versions (VS Code 1.129) | **STALE** |
| Microsoft Teams | microsoft-teams | dead:true | n/a (WebView2) | 2026 audit; MS docs | N/A (correct) |
| Signal Desktop | signal | 23.3.13 / src-pnpm-lock | **42.3.0** | Signal-Desktop v8.19.0 package.json; homebrew 8.19.0 | **STALE** |
| WhatsApp Desktop | whatsapp | dead:true | n/a (WebView2) | 2026 audit | N/A (correct) |
| Notion | notion | 39.8.3 / aur-depends | > 39.8.3 (bundled) | aur-depends artifact; homebrew 7.26.0 | STALE (suspect) |
| Figma | figma | undetected | Electron (ver n/a) | 2026 audit; homebrew 126.6.14 | UNDETECTED |
| Obsidian | obsidian | 39.8.3 / which-electron-rg | 39.8.3 | 2026 audit ("39.8.3 as of Mar 2026") | OK |
| Skype | skype | dead:true | n/a (retired 2025) | public retirement notice | N/A (correct) |
| Loom | loom | 39.2.6 / which-electron-rg | ~39 (fingerprint) | binary fingerprint | OK |
| Postman | postman | 28.3.3 / aur-depends | unverified (lags) | homebrew 12.20.0; postman issue #13836 | STALE? (unverified) |
| Insomnia | insomnia | 38.4.0 / src-package-lock | ~38 (current) | package-lock detection | OK |
| GitHub Desktop | github-desktop | 40.1.0 / src-yarn-lock | **42.0.1** | desktop/desktop release-3.6.3; 2026 audit | **STALE** |
| Trello | trello | 17.4.11 / aur-depends | unverified (abandoned) | aur-depends artifact | STALE? (unverified) |
| Twitch | twitch | undetected | Electron? (uncertain) | only AUR entry, no download | UNDETECTED |
| Beeper | beeper | 41.2.0 / which-electron-rg | ~41 (fingerprint) | binary fingerprint | OK |
| Linear | linear | 41.3.0 / which-electron-rg | ~41 (fingerprint) | binary fingerprint; homebrew 1.31.1 | OK |
| Todoist | todoist (NEW) | — | Electron (Linux app) | todoist.com/downloads; OMG Ubuntu | MISSING → stub |
| Asana | asana | 37.7.0 / which-electron-rg | ~37 (fingerprint) | binary fingerprint | OK |
| Element | element | 42.4.1 / which-electron-rg | ~42 (fingerprint) | binary fingerprint | OK |
| Mattermost | mattermost | 40.6.0 / src-package-lock | ~40 (current) | package-lock detection | OK |
| Bitwarden | bitwarden | 39.8.5 / which-electron-rg | ~39 (fingerprint) | binary fingerprint | OK |
| Joplin | joplin | 39.2.3 / src-yarn-lock | **40.8.3** | laurent22/joplin v3.6.15 package.json | **STALE** |
| Logseq | logseq | 38.8.6 / aur-depends | ~38 (current) | homebrew 2.0.1 | OK (plausible) |
| Standard Notes | standard-notes | 17.4.2 / src-yarn-lock | **35.2.0** | standardnotes/app @3.201.21 package.json | **STALE** |
| Ledger Live | ledger-live (NEW) | — | Electron | LedgerHQ/ledger-live @4.11.0 | MISSING → stub |
| balenaEtcher | balenaetcher | 37.2.4 / which-electron-rg | ~37 (fingerprint) | binary fingerprint | OK |
| Hyper | hyper | 20.3.6 / src-yarn-lock | ~20 (slow project) | yarn-lock detection | OK (plausible) |
| Tabby | tabby | 7.1.7 / (no method) | **38** | Eugeny/tabby v1.0.234 package.json | **STALE** |
| Wire | wire | 38.8.6 / aur-depends | unverified (bundled) | aur-depends artifact; homebrew 3.42.5489 | STALE? (unverified) |
| Station | station | 27.3.11 / aur-depends | unverified (abandoned) | project defunct | STALE? (unverified) |
| Shift | shift | undetected (we_tried) | Electron | homebrew 9.6.4 | UNDETECTED |
| Franz | franz | 33.3.0 / which-electron-rg | ~33 (fingerprint) | binary fingerprint | OK |
| Ferdium | ferdium | 37.10.3 / aur-depends | ~37 (maintained) | aur-depends | OK (plausible) |
| MongoDB Compass | mongodb-compass | 37.10.3 / src-package-lock | ~37 (current) | package-lock detection | OK |
| ClickUp | clickup (NEW) | — | Electron (todesktop) | homebrew 3.5.230 (todesktop) | MISSING → stub |
| Around | — (absent) | — | n/a (discontinued) | acquired/shut by Miro | N/A |
| Cursor | cursor | 40.10.6 / aur-depends | unverified | aur-depends | STALE? (unverified) |
| Windsurf | windsurf | undetected | Electron (VSCode fork) | project is a VS Code fork | UNDETECTED |
| Notion Calendar | notion-calendar | 41.5.0 / which-electron-rg | ~41 (fingerprint) | binary fingerprint | OK |
| Atom | atom | 1.1.1 / which-electron-rg | n/a (discontinued) | Atom sunset Dec 2022 | WRONG (dead) |
| Keybase | keybase | 32.3.3 / aur-depends | unverified (abandoned) | aur-depends artifact | STALE? (unverified) |
| Caprine | caprine | 29.4.6 / aur-depends | ~29 (maintained) | aur-depends | OK (plausible) |
| Termius | termius (NEW) | — | Electron | homebrew 9.41.1 | MISSING → stub |
| Proton Mail | proton-mail (NEW) | — | Electron | ProtonMail/inbox-desktop; homebrew 1.13.3 | MISSING → stub |
| Zoom | — (absent) | — | n/a (native) | well-known | N/A |
| Telegram Desktop | — (absent) | — | n/a (Qt/C++) | well-known | N/A |
| Docker Desktop | — (absent) | — | n/a (native) | well-known | N/A |

## New stub entries created

All created with `write_app()` (atomic, repo YAML style), curated keys only — no processor-owned fields (`electron`, `method`, `downloads`, `src`, `latest`):

- `data/apps/ledger-live.yml` — name, website, `repository: LedgerHQ/ledger-live` (open-source; source detection will pick it up).
- `data/apps/proton-mail.yml` — name, website, `repository: ProtonMail/inbox-desktop`, macOS `.dmg` package (verified via Homebrew 1.13.3).
- `data/apps/clickup.yml` — name, website, macOS `.dmg` package (todesktop URL verified via Homebrew).
- `data/apps/termius.yml` — name, website, macOS `.dmg` package (stable `autoupdate.termius.com` URL verified via Homebrew).
- `data/apps/todoist.yml` — name, website only (official desktop is a web-wrapper; Linux build is Electron, Windows via MS Store, macOS native — ambiguous, minimal stub).

## Recommendations

- Re-run `which-electron` for the aur-depends proprietary apps (slack, notion, visual-studio-code, wire, cursor, keybase) so their bundled Electron is fingerprinted instead of the Arch system value.
- Re-run source detection for signal, standard-notes, tabby, github-desktop, joplin — the cached `src/` extractions are resolving stale tags/lockfiles (Signal off by ~19 majors, Standard Notes ~18, Tabby ~31).
- Add a download source / repository to figma, windsurf, shift, twitch so the pipeline can detect them.
