---
layout: default
title: Home
---
# Electron Survey

Every Electron app pins a Chromium version and has to be upgraded by hand, so
people often run months-old, unpatched Chromium. This tracks the Electron
version each known app ships — grouped by how widely the app is used and
coloured by how far behind it is:
<span class="st st-green">supported</span>
<span class="st st-orange">recently end-of-life</span>
<span class="st st-red">old / long EOL</span>.

{% assign t = site.data.popularity.tiers %}

| Tier | Apps |
| --- | --- |
| [Flagship](/flagship/) | {{ t.flagship | size }} |
| [Popular](/popular/) | {{ t.popular | size }} |
| [Established](/established/) | {{ t.established | size }} |
| [Minimal](/minimal/) | {{ t.minimal | size }} |
| [Unranked](/unranked/) | {{ t.unranked | size }} |

## Flagship apps

{% include applist.html ids=t.flagship %}
