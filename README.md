# Boursy

AI-assisted, medium-term trading assistant for European healthcare stocks held in a French PEA.
See [SPEC.md](SPEC.md) for the full specification and milestones.

Current state: **M1 + M2** - app skeleton, login, healthcare universe (26 stocks), daily market data
from Yahoo Finance, indicators (EMA 20, SMA 50/200, RSI 14, MACD, ATR 14, Bollinger), dashboard with
watchlist and charts, scheduler (post-close refresh, nightly backup).

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
| Mon-Fri 17:45, Euronext trading days | Download new daily bars |
| Every day 03:00 | SQLite backup to `/data/backups` (14 kept) |
| On startup, if a stock has no data | Initial 5-year history download |

A manual refresh is available on the System page.

## Disclaimer

Decision-support tool, not financial advice.
