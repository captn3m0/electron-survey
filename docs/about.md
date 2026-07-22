---
layout: default
title: Method
permalink: /about/
description: >
  How the Electron version of each app is detected, how popularity tiers are
  assigned, and what the Chromium lag numbers do and do not mean.
---

# How this is built

Every number on this site is derived from data in the
[electron-survey repository]({{ site.repository }}) and regenerated daily. No
figure is hand-entered.

## The app list

The starting point is [electron/electron-apps](https://github.com/electron/electron-apps),
the community registry of Electron applications, pulled in as a submodule and
flattened to one YAML file per app in `data/apps/`. Entries that are clearly
gone — dead repositories, dead download links — are marked `dead` and excluded.

## Detecting the Electron version

Detection is layered cheapest-first, and the first method that produces an
answer wins. Each app records which method resolved it, shown on its page.

1. **Lockfiles.** The app's source archive is downloaded from its latest GitHub
   release or tag and searched for `package-lock.json`, `yarn.lock`,
   `pnpm-lock.yaml`, or `package.json` — in that order of confidence, because a
   lockfile pins an exact version while `package.json` only gives a range
   (resolved against the stable release list).
2. **AUR dependencies.** Arch packages that link against a shared Electron
   declare an `electron<N>` dependency, which gives the major line for free.
3. **Binary fingerprinting.** For proprietary apps with no public source, the
   released binary is downloaded and fingerprinted with
   [which-electron](https://github.com/captn3m0/which-electron), which matches
   known Electron build artefacts. This is the expensive path, so it runs last
   and on a fixed daily budget, spending it on the most-used unresolved apps
   first.

{{ site.data.summary.coverage.detected }} of
{{ site.data.summary.coverage.tracked }} live apps
({{ site.data.summary.coverage.detected_pct }}%) currently resolve to a version.
The rest are overwhelmingly proprietary apps whose installers aren't
fingerprintable.

## From Electron to Chromium

Each Electron release pins one exact Chromium build; the mapping comes from
Electron's own release index. An app shipping Electron 30 is running Chromium
124 whether or not its maintainer thinks about browsers at all.

**Days behind** is the number of days since stable Electron first shipped a
Chromium major *newer* than the app's. That date is when the app's Chromium line
stopped being where new fixes land — everything after it is a fix the app cannot
get without a major upgrade. It is deliberately a floor, not a CVE count: the
true exposure is at least this long.

## Counting unpatched CVEs

Every CVE recorded against `cpe:2.3:a:google:chrome` is pulled from the
[NVD API](https://nvd.nist.gov/developers/vulnerabilities) —
{{ site.data.cves.total_cves }} of them — along with the Chromium version range
each one affects and its CVSS base severity.

A CVE counts as **open** in a given build when that build falls inside the CVE's
affected range: it was fixed in some later Chromium, and the app ships an
earlier one. Both ends of the range are honoured, so a bug that only ever
affected Chrome 70–80 is not charged against Chrome 120.

Two things this is not:

- **Not a claim of exploitability.** Reachability depends on what the app
  exposes — whether it renders remote content, what its sandbox and
  `nodeIntegration` settings are, and which subsystems it actually uses. An open
  CVE is a missing fix, not a demonstrated exploit path.
- **Not adjusted for backports.** Electron backports selected security fixes
  into supported release lines, so an app on a *supported* major that stays
  current with patch releases will really be better off than the raw count
  suggests. The count is measured against the exact Chromium build the app's
  latest release ships, which is the version users actually run.

Counts are cached in `data/cves.yml`, keyed by both Chromium build and Electron
release, and refreshed with the rest of the data.

**Colour** comes from [endoflife.date](https://endoflife.date/electron)'s
support status for the app's Electron major:

- <span class="st st-green">green</span> — the major is still supported and
  receiving backported fixes.
- <span class="st st-orange">orange</span> — the major went end-of-life within
  the last six months.
- <span class="st st-red">red</span> — end-of-life longer ago than that.

Because the rule is relative to today, every app drifts toward red on its own as
new Electron majors ship. Nothing here needs manual re-grading.

## Popularity tiers

Ranking by "importance" needs a usage signal, and the only two open, comparable
ones are:

- **AUR votes** — summed over the Arch packages matched to the app.
- **Homebrew installs** — 365-day cask install count.

The tiers take the **stronger of the two**, not a sum or weighted blend, so a
Linux-only or macOS-only app isn't punished for missing the other channel. The
thresholds are calibrated so both channels land at the same percentile:

| Tier | AUR votes | Homebrew installs (365d) | ≈ percentile |
| --- | --- | --- | --- |
| Flagship | ≥ 75 | ≥ 40,000 | p95 |
| Popular | ≥ 25 | ≥ 7,500 | p90 |
| Established | ≥ 5 | ≥ 1,000 | p68 |
| Minimal | 1–4 | 1–999 | below |
| Unranked | 0 | 0 | no signal |

The two channels overlap surprisingly little — AUR skews Linux-enthusiast,
Homebrew skews macOS-mainstream — which is exactly why both are needed.

## Caveats

- **Neither signal is a user count.** AUR votes are cumulative and all-time;
  Homebrew installs are a recent rate. They are proxies for reach, and they
  systematically miss Windows entirely.
- **The detected version is the latest *released* one.** Users running older
  releases are further behind than shown, never less.
- **Name collisions happen.** An app can match an AUR or Homebrew package for a
  different product with the same name. Known cases are opted out by hand; more
  certainly remain.
- **Chromium lag is not a vulnerability count.** An old Chromium is a strong
  proxy for missing fixes, but Electron backports selected security patches into
  supported lines, and some apps disable the attack surface that matters. Read
  it as exposure, not as a confirmed exploit path.
- **Absence of a version is not innocence.** Apps that don't resolve are simply
  unknown, and they skew proprietary — the group least likely to be current.
