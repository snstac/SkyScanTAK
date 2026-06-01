# cot-track-fusion

Merges **object-ledger** (ADS-B) MQTT **`ObjectLedger`** with live **CoT** tracks received over PyTAK. **`COT_URL`** comes from [`cot-bridge.env`](../../cot-bridge.env) (same **output** / bridge TAK enrollment). Set **`COT_RX_URL`** or **`COT_INPUT_URL`** in [`cot-track-fusion.env`](../../cot-track-fusion.env) to use a **different** TAK stream for **inbound** tracks only (e.g. `adsbcot_*` read-only enrollment while the bridge keeps publishing on **`COT_URL`**). Adds **`skyscan_priority`** so **skyscan-c2** (patched) prefers higher-priority types (e.g. UAS SIDC `a-*-A-M-H-Q`) over closer ADS-B traffic when both are in range.

## Topics

| Env | Role |
|-----|------|
| **`OBJECT_LEDGER_TOPIC`** | Subscribe: raw ledger from object-ledger (same path object-ledger publishes to). |
| **`SOURCE_LEDGER_TOPIC`** | Optional override; defaults to `OBJECT_LEDGER_TOPIC`. |
| **`MERGED_LEDGER_TOPIC`** | Publish: merged ledger consumed by **skyscan-c2** (`LEDGER_TOPIC` in `.env`). |
| **`COT_URL`** | Default PyTAK RX URL when loaded from **`cot-bridge.env`** (same TAK enrollment the bridge uses for **output**). |
| **`COT_RX_URL`** | Optional: PyTAK **inbound** URL only; overrides **`COT_URL`** for RX when non-empty. |
| **`COT_INPUT_URL`** | Optional alias for **`COT_RX_URL`** (used only if **`COT_RX_URL`** is empty). |
| **`COT_LEDGER_EXCLUDE_COT_TYPES`** | Comma-separated CoT **`type`** values dropped from the merged ledger (default: mapping sensor, equipment, FOV polyline). Prevents **skyscan-c2** from selecting your own tripod/sensor echoes from the RX feed. |
| **`COT_LEDGER_EXCLUDE_UID_SUFFIXES`** | Comma-separated UID suffixes (case-insensitive) to drop (default: **`-ping,-fov,-poi`**). |
| **`COT_LEDGER_EXCLUDE_COT_TYPE_GLOBS`** | Comma-separated **`fnmatchcase`** patterns on CoT **`type`** to drop. **Unset** → defaults **`a-*-G-*`,`a-*-G`** (ground / land tracks). **Set to empty** (``COT_LEDGER_EXCLUDE_COT_TYPE_GLOBS=`` in env) → no glob exclusions. Air (**`a-*-A-*`**) and surface (**`a-*-S-*`**) CoT rows are not matched by these defaults. |

## CoT RX

- **`COT_URL`** (from **`cot-bridge.env`**) is the default PyTAK endpoint for RX when no override is set—the same enrollment the bridge uses for **sending** CoT.
- For **split INPUT vs OUTPUT** TAK enrollments, set **`COT_RX_URL`** or **`COT_INPUT_URL`** in [`cot-track-fusion.env`](../../cot-track-fusion.env). PyTAK RX then uses that URL only; **`COT_URL`** is unchanged for compose consistency and fallback. If both overrides are set, **`COT_RX_URL`** wins.
- Compose mounts **`./data/cot-bridge-pytak:/root/.pytak`** (same volume as **cot-bridge**). Bridge and fusion may each run a **`tak://…enroll…`** flow; PyTAK stores **separate** client material per enrollment under **`~/.pytak`** on that volume.
- If **`COT_RX_URL`**, **`COT_INPUT_URL`**, and **`COT_URL`** are all unset or empty, only ADS-B is merged (no PyTAK RX thread).

When the TAK server **reflects your own bridge CoT** onto the RX stream, **mapping-sensor / equipment / FOV / ping / POI** events can appear at the tripod with **~0 m** ground range and **win C2 sorting** before real traffic. Defaults for **`COT_LEDGER_EXCLUDE_*`** strip those so **skyscan-c2** can pick **aircraft / UAS** CoT instead.

**Ground tracks:** by default **`COT_LEDGER_EXCLUDE_COT_TYPE_GLOBS`** removes MITRE-style **ground** SIDCs (third token **`G`**, e.g. **`a-f-G-U-C`**). **Air** (`a-*-A-*`) and **surface** (`a-*-S-*`) CoT rows are the only CoT types ingested for C2 selection (see **`lib/cot_select.py`** / **`SKYSCAN_COT_ALLOW_TYPE_GLOBS`**). Bridge markers (**`b-i-v`**, **`-video`** uid suffix, equipment types) are excluded by default.

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
