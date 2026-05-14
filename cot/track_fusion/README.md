# cot-track-fusion

Merges **object-ledger** (ADS-B) MQTT **`ObjectLedger`** with live **CoT** tracks received over PyTAK using the same endpoint as **cot-bridge** (**`COT_URL`** from [`cot-bridge.env`](../../cot-bridge.env)), or **`COT_RX_URL`** if set to override RX only. Adds **`skyscan_priority`** so **skyscan-c2** (patched) prefers higher-priority types (e.g. UAS SIDC `a-*-A-M-H-Q`) over closer ADS-B traffic when both are in range.

## Topics

| Env | Role |
|-----|------|
| **`OBJECT_LEDGER_TOPIC`** | Subscribe: raw ledger from object-ledger (same path object-ledger publishes to). |
| **`SOURCE_LEDGER_TOPIC`** | Optional override; defaults to `OBJECT_LEDGER_TOPIC`. |
| **`MERGED_LEDGER_TOPIC`** | Publish: merged ledger consumed by **skyscan-c2** (`LEDGER_TOPIC` in `.env`). |

## CoT RX

- By default **`cot-track-fusion`** loads **`cot-bridge.env`** and uses **`COT_URL`** (same TAK stream you already use to send CoT from the bridge). Set **`COT_RX_URL`** in [`cot-track-fusion.env`](../cot-track-fusion.env) only if receive must use a different URL.
- Compose mounts **`./data/cot-bridge-pytak:/root/.pytak`** (same volume as **cot-bridge**) so enrollment and client identity match.
- If **`COT_URL`** and **`COT_RX_URL`** are both unset, only ADS-B is merged (no PyTAK RX thread).

## Priority rules

- **`SKYSCAN_COT_PRIORITY_RULES`**: JSON list of `[ "fnmatch_pattern", number ]`, e.g. `[["a-*-A-M-H-Q", 1000], ["a-f-A-C*", 50]]`. Higher number wins. Patterns use `fnmatchcase` on CoT **`type`**. If unset, built-in defaults favor friendly UAS types over generic air.
- **`ADS_B_PRIORITY`**: Priority assigned to non-CoT ledger rows (default **0**).
- CoT rows use **`object_type`** = `cot` and **`cot_event_type`** for the raw CoT type string.

## Caveats

- CoT tracks without **`<track>`** use zero velocity; slow movers are still usable.
- Stale or TTL-expired CoT rows are dropped (`COT_TRACK_TTL_SECONDS`, event `stale`).
- Deduping ADS-B vs CoT for the same physical target is not implemented.

## skyscan-c2

Local image build ([`../../skyscan-c2/`](../../skyscan-c2)) patches selection to sort by **`skyscan_priority`** then **`relative_distance`**, with distance hysteresis only when priorities tie.
