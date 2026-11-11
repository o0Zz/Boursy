# Boursy

AI-assisted, medium-term trading assistant for European healthcare stocks held in a French PEA.
See [SPEC.md](SPEC.md) for the full specification and milestones.

Current state: **M1 to M6** implemented.

- **Data and indicators:** 26 PEA-eligible healthcare stocks, daily bars from Yahoo Finance, EMA 20,
  SMA 50/200, RSI 14, MACD, ATR 14, Bollinger.
- **Strategy v1 and risk rules:** trend-following swing entries (pullback or MACD momentum in an
  uptrend), ATR stops with trailing, trend break, exhaustion, event protection, time stop; position
  sizing by weight and risk per trade, cash buffer, fee check, kill switch, re-entry cooldown.
- **Backtest:** day-by-day replay with the live fill, fee and risk rules; equity curve against an
  equal-weight buy-and-hold benchmark.
- **Paper portfolio:** proposals fill automatically at the next session; resting stop orders.
- **Live PEA portfolio (semi-automatic):** proposals, push and email, fill confirmation (partial
  fills), rejection, manual trades, cash movements, stop edits, journal with CSV export.
- **AI analyst (Claude):** weekly screening, signal review before each buy, pre-open news check on
  open positions, event extraction. Backends: Anthropic API (monthly USD budget) or the user's own
  Claude subscription through Claude Code (daily call cap).

## Run on the Raspberry Pi (Docker)

CI publishes a multi-arch image (amd64 + arm64) to `ghcr.io/o0zz/boursy`. On the Pi, only
`docker-compose.yml` and `.env` are needed:

```sh
mkdir boursy && cd boursy
# copy docker-compose.yml and .env.example here
cp .env.example .env                     # set BOURSY_APP_PASSWORD
docker compose pull
docker compose up -d
```

Open `http://<pi-address>:8090`. On first start the app downloads 5 years of history for every stock
(about 30 seconds). If the package is private, run `docker login ghcr.io` first with a GitHub token
that has `read:packages`.

To build from source instead: `docker compose up -d --build`.

Data (SQLite database, backups, logs, session key, caches) lives in the `boursy-data` Docker volume.

## Versions and releases

The version comes from git, the same way in CI, in the Dockerfile and in `npm run dev`:

| Ref | Version | Image tags |
|---|---|---|
| `main` | `0.0.0-main+<commit count>` | `latest`, `main`, `sha-<short>` |
| branch `release/X.Y` or `release/X.Y.Z` | `X.Y.Z+<commit count>` | `release-X.Y.Z`, `X.Y.Z-<count>`, `sha-<short>` |
| tag `vX.Y.Z` | `X.Y.Z` | `X.Y.Z`, `X.Y`, `X`, `sha-<short>` |

The version is shown next to the logo in the dashboard and returned by `GET /api/health`.
CI (`.github/workflows/ci.yml`) runs lint, migration check, tests and the frontend build on every
push and pull request, then builds and pushes the image for pushes to `main`, `release/**` and `v*` tags.

### Updates and database migrations

The database schema is versioned with [Alembic](https://alembic.sqlalchemy.org/). On every start the
app upgrades the database to the latest revision by itself, so an update is only:

```sh
docker compose pull && docker compose up -d
```

Before a migration changes an existing database, the app writes a copy to
`/data/backups/pre-migrate-<from>-to-<to>-<timestamp>.db`. If the database was written by a newer
version than the running image (after a rollback), the app refuses to start rather than touch it:
run the newer image again, or restore the pre-migration copy.

Inspect the schema version inside the container:

```sh
docker compose exec boursy alembic current
docker compose exec boursy alembic history
```

### Build on the PC, run on the Pi (without the registry)

```sh
docker buildx build --platform linux/arm64 -t ghcr.io/o0zz/boursy:latest --load .
docker save ghcr.io/o0zz/boursy:latest | gzip | ssh <user>@<pi-address> 'gunzip | docker load'
# on the Pi, next to docker-compose.yml and .env:
docker compose up -d --no-build
```

## Development

Backend (Python 3.12, managed with [uv](https://docs.astral.sh/uv/)):

```sh
cd backend
uv sync
uv run pytest
BOURSY_APP_PASSWORD=dev uv run uvicorn boursy.main:app --reload --port 8000
```

After changing `boursy/db/models.py`, generate a migration, read it, and commit it with the change.
Revision ids are sequential (`0001`, `0002`, ...):

```sh
uv run alembic -x db_url=sqlite:///scratch.db upgrade head      # scratch DB at the current head
uv run alembic -x db_url=sqlite:///scratch.db revision --autogenerate --rev-id 0002 -m "add orders"
uv run pytest tests/test_migrations.py                          # fails if models and migrations differ
```

SQLite cannot alter most column properties, so migrations run in batch mode (table rebuilt and
copied). Data migrations (filling a new column, for example) go in the same revision file.

Frontend (React + Vite), with `/api` proxied to port 8000:

```sh
cd frontend
npm install
npm run dev
```

## Schedule (Europe/Paris)

| When | Job |
|---|---|
| 08:30 trading days | AI news check on open positions (when AI is on) |
| 12:30 trading days | Open positions vs stops, large moves, proposals expiring today |
| 17:45 trading days | Download bars and FX, paper fills, sell and buy proposals, equity snapshot, notifications |
| Saturday 09:00 | AI screening of the watchlist, reconciliation reminder (live), weekly summary email |
| Every day 03:00 | SQLite backup to `/data/backups` (14 kept) |
| On startup, if a stock has no data | Initial history download (6 years) |

Every job can also be run from the System page.

## AI analyst setup

Pick the backend in Settings > AI analyst, then set the matching secret in `.env` and restart:

- **API:** `ANTHROPIC_API_KEY`. Cost is computed from token usage; calls stop at the monthly budget.
- **Subscription:** run `claude setup-token` on your PC and set `CLAUDE_CODE_OAUTH_TOKEN`. The image
  ships the Claude Code CLI (pinned version, no auto-update). Personal use only: keep the dashboard
  private. Calls stop at the daily cap.

With AI off, the strategy runs on technical signals only and proposals say so.

## Notifications

Push through [ntfy](https://ntfy.sh): set `BOURSY_NTFY_TOPIC` to a long random name and subscribe to it
in the ntfy app. Email through any SMTP server (`BOURSY_SMTP_*`, `BOURSY_MAIL_TO`). Use the test
button in Settings.

## Disclaimer

Decision-support tool, not financial advice.
