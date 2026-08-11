# Velador

**Home Assistant says the integration is fine. Its entities say otherwise. Velador is the one that notices — and revives it.**

[![hacs][hacs-badge]][hacs-url]
[![release][release-badge]][release-url]
![hassfest][hassfest-badge]
![license][license-badge]

A *velador* is a night watchman. This one guards against the failure mode nothing else
catches: the **zombie integration** — a config entry reporting `loaded` while most of its
entities sit `unavailable`. Home Assistant shows everything green. Your automations quietly
stop working. You find out days later, from a hole in your data.

It happens after power outages, HA restarts, cloud hiccups and expired tokens. Core doesn't
detect it. Nothing in HACS detects it. That's why this exists.

## Why isn't X enough?

| Tool | Territory | The question it answers |
|---|---|---|
| **Watchman** | Static config | "Does your YAML point at something that doesn't exist?" |
| **Spook** | Broken references | "Are there ghosts in your automations and dashboards?" |
| **HA's native retry** | Entries that failed to load | "Should I retry the setup that failed?" |
| **Velador** | **Live runtime state + action** | **"Is what HA calls alive actually alive — and if not, can I revive it?"** |

They're complementary, not competing. Velador only claims the last row: what is happening
*right now*, and doing something about it.

## What it catches

- **Zombie integrations** — `loaded` with ≥90 % of entities `unavailable`. Event-driven
  detection (worst case ~1 min) with a 5-minute scan as safety net.
- **Stale sensors** — still "available", silently frozen. By explicit list, or **automatically
  by learned cadence**: it learns how often each numeric sensor normally reports and flags it
  when it goes quiet for more than 5× its own rhythm.
- **Partial death** — canary entities heal their integration without waiting for the 90 %
  ratio. One dead current-clamp out of four never reaches 90 %.
- **Dead devices** — every entity of one device gone, inside an otherwise healthy integration.
  Three dead out of forty is 7 %: invisible to any ratio, and yet the bathroom light won't turn on.
- **What the restart broke** — a snapshot of what was healthy, compared after every reboot.
  If the HA version also changed, it says **possible breaking change** out loud.

## How it heals — with judgment

Reloading blindly is worse than not reloading. Velador:

- **Backs off exponentially** with jitter instead of hammering.
- **Knows when reauth is pending** and stops burning reloads — credentials are not a
  connectivity problem.
- **Treats "incurable" as temporary**: a half-open probe retries once a day, because cloud
  outages heal themselves.
- **Detects storms**: if 3+ integrations drop in the same scan, that's an outage, not N
  failures. One aggregated repair, sequential reloads — no stampede against a router that
  just rebooted.
- **Detects flapping**: revives that keep recurring mean the problem is physical. It stops
  healing and says so.
- **Never reloads a hub** (mqtt, zha, zwave_js…) because one sensor went quiet.
- **Freezes judgment when the internet is down** — that failure belongs to the environment.
- **Never auto-heals from a heuristic.** Auto-detected stale sensors and dead devices are
  reported, not reloaded.

## Install

Via [HACS](https://hacs.xyz): add `https://github.com/proscar87/velador` as a custom
repository (type: Integration), install, restart HA, then **Settings → Devices & Services →
Add Integration → Velador**. Zero configuration needed to start.

## Entities

| Entity | What it is |
|---|---|
| `binary_sensor.velador_problema` | `on` when any zombie or incurable exists (device class: problem) |
| `sensor.velador_zombies` | Current zombies + incurables + dead devices, detail in attributes |
| `sensor.velador_congelados` | Stale sensors right now |
| `sensor.velador_reauth_pendientes` | Integrations waiting on credentials, with age |
| `sensor.velador_revividas_total` | Integrations healed since last HA start |
| `sensor.velador_integraciones_vigiladas` | How many entries are being watched (disabled by default) |

## Services

- **`velador.heal`** — force the heal cycle (resets strikes, cooldowns, incurable and
  flapping). Without `entry_id` it heals everything currently sick: wire it to "power is
  back" and the whole house self-recovers.
- **`velador.audit`** — returns the full watch table as response data, for scripts and
  conversation agents.

## Notifications, your way

Velador **never sends push notifications**. Signal lives in Repairs, entities and events —
by design, so it can never become the thing that wakes you at 3 a.m. for something it was
about to fix on its own.

If you do want to be told, there's a blueprint that lets you pick the service and exactly
which events deserve to interrupt you:

**`blueprints/automation/velador/notificacion.yaml`** — start with *incurable* and *storm*.
Those are the two that actually need hands.

There's also a copy-paste dashboard in **`lovelace/velador-dashboard.yaml`**, built entirely
with native cards: no custom card dependency.

## Options

| Option | Default | Meaning |
|---|---|---|
| Zombie threshold | 0.9 | Fraction of entities `unavailable` to consider an entry dead |
| Minimum entities | 3 | Entries with fewer live entities are ignored |
| Strikes | 2 | Consecutive bad scans before declaring zombie |
| Auto-heal | on | Reload the entry automatically |
| Cooldown | 6 h | Last step of the backoff ladder |
| Grace | 15 min | Ignore everything right after HA starts |
| Exclude domains | — | Integrations that are *expected* to be offline |
| Stale entities / minutes | — / 60 | Explicit staleness watch (these ones do get healed) |
| Canary entities / minutes | — / 20 | Critical entities that heal their integration directly |
| WAN entity | — | While it's down, cloud integrations are neither judged nor healed |
| Auto-stale | off | Learn each sensor's cadence and flag the quiet ones |
| Device-zombie hours | 0 (off) | Flag devices whose entities are ALL dead longer than this |

Helpers, `mobile_app`, HACS and similar meta-domains are always ignored.

## Why this exists

Born in a real smart home — 3,800 entities, 130 integrations — that survived a Mexican summer
of power cuts. After every outage or HA update, some integration would come back as a zombie:
energy monitoring, smart plugs, beds, vehicle APIs. We'd find out days later from a gap in the
graphs. We rebuilt this watchdog three times as YAML automations before accepting it should be
code in a repo.

Every feature here has a scar behind it. The reauth awareness exists because two reloads and
twelve hours of cooldown were burned on an expired token. The storm mode exists because ten
simultaneous reloads against a rebooting router create the very second strike they were meant
to prevent. The persistent memory exists because an HA update wiped everything Velador had
learned and it re-diagnosed known-incurable integrations from scratch.

See [ROADMAP.md](ROADMAP.md) for what's next and [CHANGELOG.md](CHANGELOG.md) for history.

## License

MIT — © proscar87

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/proscar87/velador
[release-url]: https://github.com/proscar87/velador/releases
[hassfest-badge]: https://img.shields.io/badge/hassfest-passing-brightgreen.svg
[license-badge]: https://img.shields.io/badge/license-MIT-blue.svg
