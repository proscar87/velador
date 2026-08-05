# Velador

**Watches over your Home Assistant integrations and revives the ones that die silently.**

A *velador* is a night watchman. This one guards against the most annoying failure mode in Home Assistant: the **zombie integration** — a config entry that reports as `loaded` while most or all of its entities sit `unavailable`. Home Assistant shows everything green; your automations silently stop working. It happens after power outages, HA restarts, cloud hiccups and token expirations, and nothing in core or HACS detects it.

Velador does three things:

1. **Detects** — every 5 minutes it scans all loaded config entries. If an integration with enough entities has ≥90% of them `unavailable` for 2 consecutive scans, it's declared a zombie. A grace period after HA start avoids false positives from boot transients.
2. **Heals** — it reloads the zombie config entry automatically (with a cooldown so it never hammers). Most zombies revive with a single reload.
3. **Escalates** — if 2 reloads don't fix it, the integration is marked *incurable* (expired token, pending reauth, dead hardware) and Velador stops reloading and raises a Repair issue asking for human attention. No notification spam, no push — just Repairs, entities and events.

## Entities

| Entity | What it is |
|---|---|
| `binary_sensor.velador_problema` | `on` when any zombie or incurable exists (device class: problem) |
| `sensor.velador_zombies` | Count of current zombies + incurables, with full detail in attributes |
| `sensor.velador_congelados` | Stale sensors currently detected, detail in attributes |
| `sensor.velador_revividas_total` | Integrations healed since last HA start |
| `sensor.velador_integraciones_vigiladas` | How many entries are being watched (disabled by default) |

## Events (for your own automations)

- `velador_zombie_detected` — `{entry_id, domain, title, dead, total, examples, zombie_since}`
- `velador_healed` — `{entry_id, domain, title}`
- `velador_incurable` — same payload as detected
- `velador_stale_detected` — `{entity_id, state, last_reported, minutes_stale}`
- `velador_stale_recovered` — `{entity_id}`

## Options

| Option | Default | Meaning |
|---|---|---|
| Zombie threshold | 0.9 | Fraction of entities `unavailable` to consider an entry dead |
| Minimum entities | 3 | Entries with fewer live entities are ignored |
| Strikes | 2 | Consecutive bad scans before declaring zombie |
| Auto-heal | on | Reload the entry automatically |
| Cooldown | 6 h | Minimum time between reloads of the same entry |
| Grace | 15 min | Ignore everything right after HA starts |
| Exclude domains | — | Comma-separated domains you never want touched (e.g. integrations that are *expected* to be offline) |
| Stale entities | — | Entities watched for **staleness**: still "available" but silently frozen. Uses `last_reported`, so a healthy sensor repeating the same value is NOT stale |
| Stale minutes | 60 | Minutes without reporting before declaring an entity stale |

Helpers, `mobile_app`, HACS and similar meta-domains are always ignored.

## Install

Via [HACS](https://hacs.xyz): add `https://github.com/proscar87/velador` as a custom repository (type: Integration), install, restart HA, then **Settings → Devices & Services → Add Integration → Velador**. Zero configuration needed.

## Why this exists

Born in a real smart home (1,800+ entities, 130+ integrations) that survived a Mexican summer of CFE power outages. After every outage or HA update some integration would load as a zombie — Emporia, VeSync, Eight Sleep, Tuya, vehicle APIs — and we'd find out days later from a hole in the data. We rebuilt this watchdog three times as YAML automations before accepting it should be code in a repo.

**0.2** added stale-entity detection: a sensor frozen for hours is a liar, not a healthy sensor — the failure mode that blinded our edge-triggered watchdogs for 3 hours after an outage. See [ROADMAP.md](ROADMAP.md) for what's next and [CHANGELOG.md](CHANGELOG.md) for history.

## License

MIT — © proscar87
