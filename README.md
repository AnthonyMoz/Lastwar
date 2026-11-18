# Lastwar

Python client for the [lastwar.farm](https://lastwar.farm) (FarmOps) Public API v1.
No third-party dependencies; Python 3.9+.

Our alliance: **Reborn in Strength** (slug `kingbob`), public page
<https://kingbob.lastwar.farm>. That subdomain is only the public page; the API
is always called at `https://www.lastwar.farm/api/v1/...` (the host used in the
[official docs](https://www.lastwar.farm/docs/api)).

## Setup

1. Get an API key (`fops_live_...`):
   - **Alliance key**: Alliance settings → API keys (`READ` or `WRITE` scope).
     Needs Alliance Pro plus Auto Sync.
   - **Server key**: the server's **API Access** page (always `READ`).
     Needs Server Pro or a trial.
2. Provide the key. In Claude cloud sessions it is already stored as the
   `API_Key` secret and is picked up automatically. Locally, `cp .env.example .env`
   and paste the key into `LASTWAR_FARM_API_KEY` (`.env` is git-ignored).
3. Check the connection:

   ```sh
   python -m lastwar_farm ping
   ```

   It prints which kind of key you have plus your remaining rate limit.

Optional: `pip install -e .` adds a `lastwar-farm` command.

## Usage

```python
from lastwar_farm import LastWarFarmClient, ApiError

client = LastWarFarmClient()          # reads LASTWAR_FARM_API_KEY or API_Key from env / .env

# Alliance key
info = client.get_alliance()
members = client.list_members()
csv_text = client.export_power(format="csv")
client.import_power([{"memberId": "ckxyz123", "power": 12_500_000}])     # needs WRITE
client.import_duels([{"name": "PlayerOne", "score": 4_200_000}], scored_on="2026-11-16")

# Server key
stats = client.get_server()
for player in client.iter_server_players(sort_by="currentPower"):
    print(player)

try:
    client.get_server()
except ApiError as e:
    print(e.status, e.code)  # switch on e.code, e.g. "TENANT_MISMATCH"
```

Every endpoint in the spec has a method; see `lastwar_farm/client.py`.

## Things to know

- **One key, one tenant.** An alliance key gets `TENANT_MISMATCH` on `/server`
  endpoints, and a server key gets it on `/alliance` endpoints.
- **Rate limits:** 60 requests/minute and 5,000/day per key. The client retries
  HTTP 429 up to `max_retries` times (default 3), honouring `Retry-After`.
  `client.rate_limit` shows the remaining counts from the last response.
- **Big numbers come back as strings** (power, kills, THP, VS score, donations).
  Use `int(value)`.
- **Day and week buckets** reset at 02:00 UTC, matching the in-game reset.
- **`AUTO_SYNC_REQUIRED` / `TRIAL_EXPIRED`** mean the alliance's Auto Sync or Pro
  access has lapsed, not that the key is wrong.
- **Train history** exports page newest-first, 100 dates at a time
  (`iter_train_history()` follows the cursor for you). Imports replace each
  date's whole roster and need the date's current exported `version`. Always
  run with `preview=True` first, and retry a failed commit with the same
  `idempotency_key`.
- **Imports** match members by `memberId` (exact, preferred) or `name` (fuzzy).
  The result includes `activityLogId`, which lets you undo the import in the web
  UI within 24h.
- The OpenAPI spec is saved in `openapi/openapi.json` (v1.5.0). To refresh it:
  `curl -o openapi/openapi.json https://www.lastwar.farm/api/v1/openapi.json`.
  Docs: <https://www.lastwar.farm/docs/api>.

## Tests

```sh
python -m unittest discover -s tests
```

The tests run against a local fake server and never call the real API.

## Weekly report

```sh
python reports/weekly_summary.py                 # last full week
python reports/weekly_summary.py --week-start 2026-11-09
```

Writes `settings.json`, `members.json`, `vs_daily.json` and `storms.json` to
`reports/out/` (git-ignored). These feed the "Reborn in Strength Weekly Report"
page on claude.ai.

## Kick rank

```sh
python reports/kick_rank.py                                  # show the ranking
python reports/kick_rank.py --event-id <id>                  # preview the upload
python reports/kick_rank.py --event-id <id> --commit         # load into lastwar.farm
python reports/kick_rank.py --excuse "Name" --excuse <memberId>
```

Scores the last 4 full weeks: 55% VS days under the minimum, 35% donation
shortfall against the weekly target, 10% falling power. Rank 1 is most at risk.
Members who joined in the last 14 days, or who have no VS record on more than a
quarter of days (usually away or rejoined), are not ranked. The custom event
needs two metrics named `rank` and `score`.
