# Boursy - Specification

AI-assisted, medium-term stock trading bot for European healthcare stocks, held in a French PEA.
Version 1 is **semi-automatic**: the bot finds, tracks and proposes trades; the user places the orders
in their PEA broker app and confirms them in the dashboard.

Status: v0.2 (2026-11-11) - M1 to M6 implemented; M6 live trading starts once paper mode has run for a few days.

---

## 1. Goals

1. Screen PEA-eligible European healthcare stocks and keep a watchlist of the ones that fit the profile.
2. Track watchlist and open positions with technical indicators and AI analysis (news, fundamentals, upcoming events).
3. Propose buy / sell orders with a limit price, a stop-loss and a written rationale.
4. Notify the user on the phone (push) and by email.
5. Keep a full trade journal, portfolio value and performance history.
6. Run first as a simulation (paper money), then live with 200 EUR, then scale to about 10 000 EUR.

### Non-goals (v1)

- No automatic order placement (PEA brokers have no trading API).
- No intraday / high-frequency trading. Decisions use daily candles.
- No US stocks, no leverage, no short selling, no options.
- No multi-user support.

### Later (v2+, out of scope now)

- Full automation on a separate CTO account through a broker API (Interactive Brokers), behind the same broker interface.

---

## 2. Decisions and constraints

| Topic | Decision |
|---|---|
| Account | Existing PEA, orders placed manually by the user |
| Markets | EU/EEA exchanges only (PEA eligibility): Euronext Paris/Amsterdam/Brussels/Milan/Lisbon, Xetra, Copenhagen, Stockholm, Helsinki, Madrid |
| Sector | Healthcare in general: pharma, biotech, medtech, diagnostics, life-science tools, services |
| Holding period | Weeks to months |
| Positions | 1-2 at 200 EUR capital, up to 5-6 at 10 000 EUR |
| Max drawdown | -20 % from portfolio peak triggers the kill switch (configurable) |
| Hosting | Raspberry Pi 5 (arm64), Docker, **one container** |
| Frontend | React |
| Backend | Python |
| Notifications | Push (ntfy) and email (SMTP) |
| Running budget | about 20 USD / month for AI and data |

---

## 3. Operating modes

| Mode | Money | Orders | Purpose |
|---|---|---|---|
| `backtest` | none | simulated over history | Validate and tune the strategy on past data |
| `paper` | virtual capital | simulated fills on live data | Run the full daily loop for a few days/weeks with no risk |
| `semi_auto` | real PEA | user places orders manually, confirms fills in the dashboard | Live trading v1 |
| `full_auto` | real CTO | broker API | v2, not implemented |

The mode is a setting. `paper` and `semi_auto` can run at the same time on separate portfolios, to
compare the simulated result with reality.

---

## 4. Architecture

One Docker image, one container, one process:

```
+--------------------------------------------------------------+
|  boursy container (python:3.12-slim, linux/arm64)            |
|                                                              |
|  uvicorn (1 worker)                                          |
|   +-- FastAPI                                                |
|   |    +-- /api/*      REST API for the dashboard            |
|   |    +-- /*          React build (static files, SPA)       |
|   +-- APScheduler (in-process, Europe/Paris timezone)        |
|        +-- jobs: screening, daily analysis, monitoring       |
|                                                              |
|  /data (volume)                                              |
|   +-- boursy.db      SQLite                                  |
|   +-- logs/                                                  |
+--------------------------------------------------------------+
        |                 |                 |
   market data       Claude API        ntfy / SMTP
   (yfinance)        (Anthropic)       (notifications)
```

- Multi-stage Dockerfile: stage 1 builds the React app with Node, stage 2 is the Python runtime that copies the built `dist/` folder.
- uvicorn must run with **one worker**, otherwise the scheduler runs its jobs twice.
- SQLite in WAL mode on a mounted volume. A daily backup job copies the database file to `/data/backups/` (keep 14).
- Schema versioned with Alembic (sequential revisions `0001`, `0002`, ...). The app upgrades the database to the
  latest revision at start-up, after copying it to `/data/backups/pre-migrate-<from>-to-<to>-<timestamp>.db`.
  A database at a revision the code does not know (written by a newer version) stops the start-up untouched.
  A test fails when models and migrations differ.
- Config through environment variables (`.env`) for secrets, and through the dashboard (stored in the DB) for strategy and risk parameters.

### Components (backend modules)

| Module | Role |
|---|---|
| `universe` | Healthcare stock list, PEA eligibility, liquidity filters |
| `data` | Market data provider interface + yfinance implementation, daily OHLCV storage |
| `indicators` | SMA, EMA, RSI, MACD, ATR, Bollinger, volume averages, implemented with pandas (no TA-Lib, simpler on arm64) |
| `events` | Calendar of known events per stock: earnings, trial readouts, regulator decisions (FDA/EMA), shareholder meetings |
| `analyst` | Claude API calls: screening, thesis, news review, event extraction |
| `signals` | Rule engine: combines indicators + AI score + events into buy/sell/hold signals |
| `risk` | Position sizing, limits, kill switch, fee checks |
| `proposals` | Turns signals into trade proposals; lifecycle (pending, executed, rejected, expired) |
| `portfolio` | Positions, cash, fills, fees, P&L, equity curve, one portfolio per mode |
| `simulator` | Fill simulation for `paper` and `backtest` |
| `notifier` | ntfy push + SMTP email |
| `scheduler` | Job definitions, Euronext trading calendar (`exchange_calendars`) |
| `api` | FastAPI routes for the dashboard |

---

## 5. Stock universe

### Eligibility

- Company headquartered in the EU/EEA (PEA rule). First check uses the ISIN country prefix; a manual override flag exists for exceptions.
- Sector: healthcare (GICS 35 or equivalent from the data provider), plus manual additions.
- Liquidity: average daily traded value over 20 days >= 100 000 EUR (configurable). Below this, limit orders may not fill and spreads are wide.

### Buckets

Healthcare stocks move together, so the universe is split into two buckets with different risk rules:

| Bucket | Examples | Max weight per position |
|---|---|---|
| `core` (large caps, > 5 bn EUR) | Sanofi, EssilorLuxottica, Novo Nordisk, Siemens Healthineers, Philips, UCB, argenx, Merck KGaA, bioMerieux, Coloplast, Sartorius Stedim | 25 % |
| `growth` (small/mid caps, biotech) | Medincell, Valneva, Nanobiotix, Abivax, Virbac, Genmab, DiaSorin, Ipsen | 12 % |

The seed list is a starting point. The weekly screening job can add or remove stocks.

---

## 6. Strategy v1 (trend-following swing)

All thresholds are parameters, editable in the dashboard and validated by backtest before use.
The values below are starting defaults, not proven values.

### Buy signal (all must be true)

1. **Trend:** close > SMA200, and SMA50 > SMA200.
2. **Entry timing (one of):**
   - Pullback: RSI(14) went below 45 in the last 5 sessions and is now rising, close back above EMA20.
   - Momentum: MACD line crosses above the signal line while MACD > 0.
3. **Volume:** volume of the signal day >= 1.0 x 20-day average.
4. **AI score** >= 6/10 (from the latest analyst review, not older than 7 days).
5. **No binary event** (trial readout, regulator decision, earnings) in the next 5 trading days, unless the stock is in `core` and the event is a regular earnings release (configurable).
6. **Risk checks pass** (section 7).

### Sell signal (any one is enough)

1. **Stop-loss hit:** close below the stop price. Initial stop = entry - 3 x ATR(14), capped at -10 % (`core`) / -15 % (`growth`).
2. **Trailing stop:** once the gain is > 1.5 x initial risk, the stop rises to the highest close - 3.5 x ATR(14).
3. **Trend break:** close below SMA50 for 10 consecutive sessions.
4. **Exhaustion:** RSI(14) > 75 and MACD crosses below its signal line - propose selling half.
5. **Thesis break:** the AI flags a negative event (failed trial, regulator rejection, guidance cut, fraud, dilution).
6. **Event protection:** a binary event is in the next 2 trading days and the position is in `growth` - propose to sell or reduce to half.
7. **Time stop:** no progress (gain < +3 %) after 120 trading days.

### Backtest result and defaults (2026-11-11)

First backtest over Aug 2022 - Nov 2026 (4.2 years after the SMA 200 warm-up, 26 stocks, 10 000 EUR,
BoursoBank fees):

| Variant | Return | Max drawdown | Trades | Fees |
|---|---|---|---|---|
| Draft exits (2 ATR stop, 2.5 ATR trailing, 2-session trend break, 60-session time stop), no kill switch | -42 % | -47 % | 272 | 3 268 EUR |
| Current defaults (3 ATR stop, 3.5 ATR trailing, 10-session trend break, 120-session time stop), no kill switch | +19 % | -23 % | 168 | 2 420 EUR |
| Same, Trade Republic fees | +41 % | -14 % | 169 | 317 EUR |
| Current defaults with the -20 % kill switch | -19 % | -21 % | 54 | 827 EUR |
| Equal-weight buy-and-hold of the same stocks | +99 % | -25 % | - | - |

The draft exits were stopped out by normal noise, so the defaults were widened. Even so the strategy
trails buy-and-hold over this period, the kill switch triggers in late 2023, and fees at BoursoBank
take a large part of the gains. No AI filter and no event calendar exist in the backtest. Treat paper
mode as the real test before any live money.

### Proposal content

Every proposal has: stock, side, quantity, **limit price**, stop price, validity (end of next trading day),
signal reasons (which rules fired), indicator snapshot, AI rationale, expected fees, risk in EUR.

---

## 7. Risk rules (enforced by code, the AI cannot override them)

| Rule | Default |
|---|---|
| Max open positions | 2 if capital < 1 000 EUR, else 6 |
| Max weight per position | 25 % `core`, 12 % `growth` (100 % / 50 % below 1 000 EUR capital) |
| Max risk per trade (entry - stop) x qty | 2 % of capital |
| Min cash buffer | 5 % |
| Kill switch | Portfolio value <= 80 % of its peak: no new buys, alert sent, manual reset required |
| Daily proposal limit | 3 buys per day |
| Fee check | Reject a trade when estimated round-trip fees > 1.5 % of the order value |
| Order type | Limit orders only |
| Re-entry cooldown | 10 trading days after a stop-loss on the same stock |

The fee model is configurable (fixed + percentage + minimum per order + PEA cap) to match the user's PEA broker.
Default profile: BoursoBank Découverte on PEA - 1.99 EUR per order up to 500 EUR, 0.60 % above, capped at
0.50 % of the order (legal PEA cap). Presets for Bourse Direct and Trade Republic, in case the PEA is transferred
before scaling up (at ~2 000 EUR per order, BoursoBank costs ~10 EUR vs ~1-3 EUR there). Fees on non-French
exchanges are often higher and need their own values per exchange.
At 200 EUR capital, fees are a large part of each trade; the fee check prevents trades that cannot
make money after fees.

---

## 8. Semi-automatic workflow

```
signal -> proposal (pending) -> push + email -> user decides
                                                 |
               +---------------------------------+--------------------+
               |                                 |                    |
         user places order                 user rejects           no action
         in PEA app, then                  (reason optional)      before expiry
         confirms in dashboard                   |                    |
         (qty, price, fees)                  rejected              expired
               |
           executed -> position / cash updated -> stop price tracked
```

- Notification has an action button that opens the proposal page in the dashboard.
- The user enters the real fill (quantity, price, fees). Partial fills are allowed.
- After a buy, the dashboard reminds the user to place a stop order in the broker app as well. The bot
  also monitors the stop, but only on its schedule, so the broker-side stop is the real protection.
- The user can also record a trade the bot did not propose (manual trade), so the portfolio stays in sync.
- A weekly reconciliation reminder asks the user to check that dashboard cash and positions match the broker.

---

## 9. Simulation and backtest

### Paper mode

- Virtual capital (default 200 EUR, configurable).
- Proposals are auto-accepted.
- Fill rule: a buy limit fills at the next session open if open <= limit, else at the limit if low <= limit during the session, else not filled (proposal expires). Same logic mirrored for sells and stops.
- Same fee model as live.

### Backtest

- Runs the signal engine day by day over historical data (default: 5 years) with the same fill rules.
- AI score is not available historically: backtests run either without the AI filter, or with a neutral score, and the report says so.
- Output: equity curve, max drawdown, win rate, average gain / loss, profit factor, number of trades, fees paid, comparison with buy-and-hold of a healthcare index.
- Survivorship bias warning in the report (today's universe did not exist the same way 5 years ago).

---

## 10. Schedule (Europe/Paris, Euronext trading days only)

| Time | Job |
|---|---|
| 08:30 | Pre-open: news check on open positions (AI), event calendar refresh |
| 12:30 | Midday monitor: prices of open positions vs stops, alert on large moves (> 5 % / > 8 % for `growth`) |
| 17:45 | Post-close: download daily bars, compute indicators, signals, proposals, notifications |
| 18:00 | Paper mode fills for the day, equity snapshot |
| Saturday 09:00 | Weekly screening of the universe (AI, batch) and watchlist update |
| Daily 03:00 | Database backup |

Checking every 10 minutes is not needed: the strategy uses daily candles. The midday monitor is only
for alerts.

---

## 11. AI usage (Claude API)

### Rules

- The AI **never** decides alone and never places orders. It returns structured data; the rule engine and risk rules decide.
- All AI outputs use structured outputs (JSON schema) and are stored with the date, model, input summary and cost.
- The user can read every AI rationale in the dashboard.

### Tasks

| Task | When | Input | Output |
|---|---|---|---|
| Screening review | Weekly, batch | Company profile, financials summary, price trend, recent news (web search) | Score 0-10, bucket, thesis, key risks, upcoming events with dates |
| Signal review | When a buy signal fires | Indicators, latest news, events | Confirm / veto with reason, updated score |
| Position news check | Daily pre-open | Open positions, news since last check | Nothing / warning / thesis break |
| Event extraction | Weekly | News, company calendar | Dated list of binary events |

### Backends (selectable in Settings)

The analyst talks to Claude through an `AnalystBackend` interface with two implementations. Prompts,
JSON schemas and result storage are shared; only the transport differs.

| | `api` | `subscription` |
|---|---|---|
| Transport | Anthropic Python SDK, API key | Claude Code CLI in headless mode (`claude -p`), run as a subprocess |
| Auth | `ANTHROPIC_API_KEY` | `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (valid one year, needs a Pro/Max plan) |
| Cost | Pay per token | Included in the subscription, shares the plan's usage limits with the user's normal Claude use |
| Structured output | `output_config.format` (JSON schema) | `--output-format json --json-schema '<schema>'`, result in `structured_output` (absent when the run fails - check it) |
| News search | `web_search_20260209` server tool | `--tools "WebSearch,WebFetch"` + `--permission-mode dontAsk` (test that these tools are accepted) |
| Batch discount | Yes (weekly screening) | No - screening runs as sequential calls |
| Limits | `--max-turns` equivalent in code | `--max-turns 8`, `--model <name>`, timeout on the subprocess |

Subscription backend rules:

- Personal use only: the dashboard stays private (single user), never shared or offered to others. Anthropic's terms allow an end user to sign in to the unmodified Claude Code binary with their own subscription, and forbid routing subscription credentials on behalf of other users.
- Never run with `--bare` (it ignores OAuth credentials).
- The subprocess environment must **not** contain `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`: in `-p` mode an API key silently takes precedence over the subscription token. The backend builds an explicit environment for the subprocess.
- Claude Code is installed in the image with the native installer, version pinned, `DISABLE_UPDATES=1`.
- `total_cost_usd` in the CLI output is an estimate of what the API would cost, not what the plan uses. The budget cap in this mode counts calls per day (default 40) instead of dollars.
- If the subscription hits its usage limit, the call fails: the job logs it, sends a push alert and continues without AI confirmation, same as the budget cap. Optional setting: fall back to the `api` backend when an API key is configured.

### Configuration

- Model: `claude-opus-5-5` by default, configurable per task in Settings (cheaper models such as `claude-sonnet-5-5` or `claude-haiku-5-5` can be selected by the user to lower cost).
- Effort set explicitly per task (`output_config.effort`): `medium` for daily checks, `high` for screening.
- Web search server tool (`web_search_20260209`) for news, with a `max_uses` cap per call.
- Weekly screening goes through the Message Batches API (50 % cheaper, not time-sensitive).
- Prompt caching on the shared system prompt and strategy description.
- Server-side refusal fallback enabled (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`).
- **Monthly budget cap** (default 15 USD): cost is computed from `usage` on every response; when the cap is reached, AI calls stop, the signal engine runs without AI confirmation and new buy proposals are marked "AI unavailable".

### Cost estimate (Claude Opus 5.5: 4 USD / 1M input tokens, 20 USD / 1M output tokens)

| Task | Volume per month | Estimate |
|---|---|---|
| Weekly screening, ~40 stocks, batch | ~160 calls x 8k in / 1k out, -50 % | ~4-5 USD |
| Signal reviews | ~20 calls x 10k in / 1.5k out | ~1.5 USD |
| Daily news checks | ~22 calls x 8k in / 1k out | ~1.2 USD |
| Web searches | a few hundred | a few USD |
| **Total** | | **~8-12 USD** |

To be measured during paper mode; the dashboard shows real cost per task.

---

## 12. Market data

- Provider interface `MarketDataProvider` with methods `daily_bars(symbol, start, end)`, `quote(symbol)`, `profile(symbol)`.
- v1 implementation: `yfinance` (free; data delayed about 15 min; unofficial, may break). Symbols use Yahoo suffixes (`.PA`, `.AS`, `.BR`, `.DE`, `.CO`, `.MI`, `.MC`, ...).
- Optional paid provider later (EODHD or similar) through the same interface.
- Daily bars are stored in SQLite; only missing days are downloaded.
- Data quality checks: missing days, zero volume, split/dividend adjustments (use adjusted prices for indicators, raw prices for orders).
- Prices in other currencies (DKK, SEK) are converted to EUR for portfolio values; orders stay in the local currency.

---

## 13. Notifications

| Event | Push | Email |
|---|---|---|
| New proposal | yes (high priority) | yes |
| Stop-loss hit / large move on a position | yes (urgent) | yes |
| Thesis break from AI | yes | yes |
| Kill switch triggered | yes (urgent) | yes |
| Proposal about to expire | yes | no |
| Weekly summary (performance, watchlist changes, AI cost) | no | yes |
| Job failure (data download, AI error) | yes | no |

- Push: ntfy (Android/iOS app). Use the public `ntfy.sh` server with a long random topic name and an access token, or self-host ntfy later. Messages contain a link to the dashboard, and only basic data (ticker, side, price).
- Email: SMTP settings in `.env`.

---

## 14. Dashboard (React)

| Page | Content |
|---|---|
| Overview | Portfolio value, cash, P&L (day / total), equity curve, drawdown vs kill switch, mode badge, pending proposals |
| Proposals | Pending / history; actions: confirm fill (qty, price, fees), reject, record manual trade |
| Positions | Open positions, entry, current price, stop, trailing stop, P&L, days held, next event |
| Watchlist | Stocks with AI score, bucket, trend state, last signal, next event; add / remove / pin |
| Stock detail | Candlestick chart with SMA/EMA, RSI and MACD panels, buy/sell markers, AI thesis history, events |
| Journal | All trades, fees, realized P&L, CSV export |
| Backtest | Run a backtest with chosen parameters, show the report and the equity curve |
| Settings | Strategy parameters, risk rules, fee model, schedule, AI model / effort / budget, notification tests |
| System | Job runs and errors, AI calls and cost per month, data freshness, logs |

- Responsive: used mostly from the phone.
- Login: single user, password from `.env`, session cookie. Dashboard is exposed on the LAN only (remote access through the user's existing VPN if needed, never port-forwarded directly).

---

## 15. Tech stack

**Backend:** Python 3.12, FastAPI, uvicorn, SQLAlchemy 2 + Alembic (migrations), SQLite, APScheduler,
pandas, numpy, yfinance, exchange_calendars, anthropic (official SDK), httpx, pydantic-settings, pytest.

**Frontend:** React + TypeScript + Vite, TanStack Query, React Router, `lightweight-charts` (financial
charts), Tailwind CSS.

**Container:** multi-stage Dockerfile (node:22-alpine build stage, python:3.12-slim runtime), built for
`linux/arm64` (on the Pi directly, or with `docker buildx` from the PC), Claude Code CLI installed in the
runtime stage (native installer, pinned version) for the `subscription` backend, one `docker-compose.yml` service
with a `/data` volume, `.env` file, restart policy `unless-stopped`, healthcheck on `/api/health`.

### Repository layout

```
Boursy/
  SPEC.md
  Dockerfile
  docker-compose.yml
  .env.example
  backend/
    pyproject.toml
    boursy/
      main.py            FastAPI app, static files, scheduler start
      config.py
      db/                models, session, alembic migrations
      universe/
      data/
      indicators/
      events/
      analyst/           prompts, schemas, Claude client, cost tracking
      signals/
      risk/
      proposals/
      portfolio/
      simulator/
      notifier/
      scheduler/
      api/
    tests/
  frontend/
    package.json
    src/
      pages/
      components/
      api/
```

---

## 16. Milestones

| # | Milestone | Done when |
|---|---|---|
| M1 | Skeleton | Container builds for arm64, runs on the Pi, dashboard login works, `/api/health` OK |
| M2 | Data + indicators | Seed universe loaded, daily bars stored, indicators computed and tested against known values, stock detail chart works |
| M3 | Signals + risk + backtest | Strategy v1 and risk rules implemented with unit tests; backtest report for 5 years |
| M4 | Paper mode | Full daily loop on the scheduler with simulated fills; notifications work; runs for a few days without errors |
| M5 | AI analyst | Screening, signal review and news check; budget cap; cost visible in the dashboard |
| M6 | Semi-auto live | Proposal workflow with manual fill confirmation; start with 200 EUR |
| M7 | Scale | Capital raised step by step toward 10 000 EUR when results justify it |
| M8 (v2) | Full auto on CTO | Broker adapter for Interactive Brokers; separate decision |

M4 can run before M5 (paper mode without AI filter) to start collecting results earlier.

---

## 16b. Implementation notes (differences from the draft)

- Paper fills run inside the 17:45 post-close job (before new signals), not in a separate 18:00 job:
  proposals from the previous session fill against today's bar, then today's signals are computed.
- Paper and backtest simulate the resting stop order at the broker (a gap below the stop fills at the
  open). Live positions are checked against the stop at 12:30 and on the close.
- Weekly screening runs as sequential calls on both backends; the Message Batches API and the
  server-side refusal fallback are not used yet. A refusal is logged and the stock is skipped.
- The Docker runtime is Alpine; Claude Code is installed with the native installer (musl build).

## 17. Open points

1. PEA is at BoursoBank (Découverte). Decide before M7 whether to transfer it to a cheaper broker (Bourse Direct, Trade Republic); check that target stocks (Medincell, Nordic stocks) are tradable there.
2. Is a 15-minute data delay acceptable for the midday monitor? (Yes for daily strategy; affects only alerts.)
3. ntfy on `ntfy.sh` vs self-hosted ntfy on the NAS (a second container, optional).
4. Monthly AI budget cap: 15 USD default - confirm.
5. Starting watchlist: confirm or edit the seed list in section 5.

---

## 18. Disclaimer

This software is a decision-support tool, not financial advice. Indicators and AI analysis are often
wrong, and small-cap biotech stocks can lose a large part of their value in one day. Only invest money
you can afford to lose.
