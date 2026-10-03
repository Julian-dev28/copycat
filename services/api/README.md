# services/api

FastAPI over HTTP/JSON for the web UI. Owns `data/settings.json` (the only
writer) and the bearer token. Never signs orders, never holds the agent key.

    COPYCAT_SKIP_DOTENV=1 .venv/bin/python -m api      # binds COPYCAT_BIND:COPYCAT_API_PORT
    .venv/bin/python -m pytest services/api            # gate, <1s
    .venv/bin/python -m api.openapi_export             # regenerate openapi.json (gate checks it)

## Routes (prefix /api)

| method | path | notes |
|---|---|---|
| GET | /health | `{ok, version}`, no auth |
| GET / PUT / PATCH | /settings | `Settings`. PATCH semantics below |
| POST | /leaders | `{address}`; 400 bad address or our own account, 409 at 10 leaders |
| DELETE | /leaders/{address} | also drops its override; idempotent |
| GET | /status | `EngineStatus` from `engine.public.status()`; 503 if the engine package is missing |
| GET | /events?limit=&since_ms= | newest first |
| GET | /events/stream | SSE, tails `data/events.jsonl` from its end, one `EngineEvent` JSON per message |
| POST | /engine/halt | `enabled=false`; exits keep mirroring |
| POST | /engine/close-all | `enabled=false`, then writes `data/close_all.flag`; returns `{requested_ms, pending, settings}`. The engine's next cycle closes every copy |
| POST | /discovery/runs | `{sim_equity_usd, top_n, settings?}` -> `{run_id}`; 409 if one is running |
| GET | /discovery/runs/latest, /discovery/runs/{id} | `DiscoveryRun`; 404 when none / unknown |

## Auth

Every route but `/health` needs `Authorization: Bearer <token>`, on every
bind. No unauthenticated mode. Token: `COPYCAT_API_TOKEN` (>= 32 chars,
"change-me" refused at startup); if empty, one is generated into
`$COPYCAT_DATA_DIR/api_token` (mode 0600, created with O_EXCL), its path is
printed (never the token), and it is reused on restart. Compared in constant
time. `TrustedHostMiddleware` rejects any Host other than `localhost`,
`127.0.0.1` or `COPYCAT_ALLOWED_HOSTS` with 400 (DNS rebinding). CORS allows
only `COPYCAT_WEB_ORIGIN`. `create_app()` pops `COPYCAT_AGENT_KEY` from the
process env.

## Settings file

`SettingsStore`: every write is tmp file + fsync + `os.replace`, every
read-modify-write under an flock on `settings.json.lock`, so concurrent
PATCHes never lose an update. A missing file serves defaults
(`enabled=false, dry_run=true`). PATCH:
- only fields present in the body change (`model_fields_set`, not `is None`)
- `leaders`, if present, replaces the whole list
- `leader_overrides` merges per leader: a value replaces that leader's whole
  override, `null` clears it
- the merged result is validated through `Settings` before writing; invalid
  is 422 and nothing is written
- a `leaders` list containing `COPYCAT_ACCOUNT_ADDRESS` is 400

## Discovery

Runs execute in a spawned child process (`api.discovery_client.run_child`)
with `COPYCAT_HL_PRIORITY=background`, the absolute data dir, and no agent
key. The child sends back the run id (or busy/error) over a pipe and lives
until the run finishes. The api reads progress from `discovery.db` via
`discovery.public.get_run/latest`. Keeps discovery's CPU and HL reads away
from the halt/close-all routes and the engine's rate reserve.
