# Wind Procurement Decision Support

Decision-support dashboard for day-ahead electricity procurement, built on **Elexon Insights (BMRS)** national wind data:
**WINDFOR** hourly forecast vintages and **FUELHH** half-hourly outturn (fuel type `WIND`).

It is a *retrospective simulation* of decisions made in **January 2026**. For a delivery day and a forecast cutoff on the
previous day it selects the forecast that was actually available at that moment, combines it with a persisted, versioned
historical calibration of forecast error, and shows the wind forecast, its uncertainty and a conservative wind-shortfall buffer.

> **Purchase volume:** enter your own expected demand (flat or per hour), optional existing contracted supply, and the share of GB wind you can count on, and the Plan page works out the volume still to buy per hour: `buy = max(0, demand - contracted - wind)`, for three wind cases (as published, expected = bias-corrected, cautious = forecast minus the P90/P95 shortfall buffer). The cautious case is the recommendation. Hours stand alone (surplus wind never offsets another hour) and hours without a forecast are reported, never filled. Your inputs are remembered in the browser only (localStorage convenience; nothing is stored on the server).
>
> **What it is not:** Elexon wind data alone cannot give an optimal purchase quantity (demand, contracts, other generation, price and
> risk policy are missing). The app never invents these: nothing is calculated until you supply demand, and prices, imbalance costs and your risk policy are not modelled. It is a volume estimate, not a trading recommendation.

## Conventions

- `error = forecast_mw − actual_mw`. **Positive = over-forecast** (wind fell short); negative = under-forecast.
- Timestamps are stored in UTC. Business dates, cutoffs and chart labels use `Europe/London`. A UK day can start on the previous UTC date (BST) and has 23/25 hours on DST days.
- Actuals (30 min) are aggregated to **hourly mean MW** (two half-hours averaged, never summed). Hours missing a half-hour are excluded and counted.
- Forecast and actual are matched on **delivery time**, never by row order or publication time.
- Percentiles use linear interpolation (numpy type 7).

## Decision-time correctness (no future leakage)

- Cutoff = the chosen UK time on the **day before** delivery. Eligible vintages: `publishTime <= cutoff` (inclusive). Vintages published later are never loaded for a decision.
- Policy `latest_complete_vintage`: latest eligible vintage if it covers all required hours; otherwise the most recent earlier *complete* vintage (flagged as a fallback); otherwise the best partial vintage with the missing hours reported. Missing hours are never filled from actuals, later forecasts or defaults, and vintages are never mixed per hour.
- Calibration observations used by a decision must have been **observed by the cutoff** (`actual_available_at <= cutoff`). A calibration ending 31 Dec therefore loses the last evening hours of 31 Dec when used for the 1 Jan decision (17:00 cutoff on 31 Dec). A custom range running into January is trimmed per decision; if fewer than `MIN_CALIBRATION_PAIRS` remain the API answers `422 CALIBRATION_UNAVAILABLE_AT_CUTOFF` with an explanation. Trimming is always disclosed in `warnings`.
- Realised actuals are used only by the *Evaluation* endpoint (retrospective scoring).

## Risk maths

For the active calibration (effective observations at the cutoff) and percentile `q` (90 or 95):

- `bias = mean(error)`; bias-adjusted estimate = `forecast − bias`.
- `Q = q-th percentile of error over all hours`; **shortfall buffer = max(0, Q)**; conservative estimate = `forecast − buffer` (floored at 0 MW).
- The bias is *part of* the buffer (`buffer = bias + residual margin`), shown as separate steps and never added twice.
- Uncertainty range = `forecast − P(q)` to `forecast − P(100−q)` of the error.
- Also reported: MAE, RMSE, bias, P90/P95 **absolute** error, and P90/P95 **positive** error (over-forecast hours only). These are different statistics and labelled as such.

## Architecture

```
backend/app
  api/            FastAPI routers (calibrations, decisions, coverage, health)
  services/
    elexon_client.py       HTTP, bounded retry/backoff, response validation (no business logic)
    data_store.py          read-through DB cache of closed historical ranges
    data_normalization.py  frames, dedupe, half-hourly -> hourly mean
    forecast_selection.py  decision-time vintage selection (pure)
    metrics.py             error metrics (pure)
    calibration.py         reconstruct historical forecasts, align, breakdowns (pure)
    calibration_jobs.py    versions, background job, activation
    decision_analysis.py   leakage guards, risk maths, decision + evaluation
  models/ db/ schemas/ core/   SQLAlchemy models, session, Pydantic schemas, time + errors
frontend/src  pages: Decision, Evaluation, Calibration (features/*), services/api.ts
```

Calibration runs in a single background thread; the UI polls `GET /api/calibrations/{id}` for progress. Only one job may be pending/running
(checked in the database). Every run creates a new immutable **version**. The first completed version is auto-activated; later ones must be
activated explicitly. A failed run never touches other versions. Jobs interrupted by a restart are marked `failed` on startup.

### API (OpenAPI at `/docs`)

| Method & path | Purpose |
|---|---|
| `GET /api/health` | app, DB and Elexon reachability |
| `GET /api/config` | defaults and limits used by the UI |
| `GET /api/calibrations` | list versions |
| `GET /api/calibrations/active` | active version (`404 NO_ACTIVE_CALIBRATION` on first run) |
| `POST /api/calibrations` | start a run `{start_date, end_date, cutoff_time}` → `202` |
| `GET /api/calibrations/{id}` | status/progress, metrics, breakdowns, quality, warnings |
| `GET /api/calibrations/{id}/observations` | stored matched hourly pairs (provenance for reproduction) |
| `POST /api/calibrations/{id}/activate` | activate a completed version |
| `GET /api/decisions/{date}?cutoff=17:00&percentile=95` | decision support |
| `POST /api/decisions/{date}/procurement` | purchase volume for the demand you supply (`demand_mw` or `demand_by_hour_mw`, `contracted_mw`, `wind_share_pct`) |
| `GET /api/decisions/{date}/evaluation` | retrospective forecast vs actual |
| `GET /api/data-coverage` | locally stored data and gaps |

Errors always have the shape `{"error": {"code", "message", "details"}}`; stack traces are logged, never returned.

## Elexon API facts (verified against the live API)

- `WINDFOR/stream`: params `publishDateTimeFrom/To` (both inclusive). Rows `{publishTime, startTime, generation}`. **Hourly** targets; a snapshot is published roughly every 2-4 h and covers ~73 hours.
- `FUELHH/stream`: params `settlementDateFrom/To`, `fuelType=WIND`. Half-hourly. Combining settlement-date and publish-time filters returns HTTP 400, so each dataset only uses its own supported filter. The client also discards any non-WIND row.
- Stream endpoints return one JSON array (no pagination). Timeouts, connection errors, 429 (honours `Retry-After`) and 5xx are retried with capped exponential backoff; 4xx are not. An empty or malformed response is an error, never replaced by placeholder data.

### Data finding worth knowing

On the live default calibration (1 Oct - 31 Dec 2025, 2,209 hours) WINDFOR exceeded FUELHH wind by ≈ **+1.45 GW on average** (73% of hours over-forecast), and
even forecasts issued < 2 h ahead show a similar offset. Testing shifted alignments showed no sharper minimum at lag 0, so this is a systematic scope/definition
difference between the two datasets (e.g. what generation each includes), not a timing or leakage bug. The bias adjustment and buffer exist partly to absorb it.
Treat the numbers as "WINDFOR versus FUELHH", which is what the app measures.

## Run locally

Prerequisites: Python ≥ 3.12 (tested 3.14), Node ≥ 20 (tested 24).

```powershell
# Backend  (http://127.0.0.1:8000, docs at /docs). SQLite file: backend/data/wind.db
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt     # Linux/macOS: .venv/bin/python
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# Frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173, go to **Calibration → Run initial calibration** (about 5-10 s, real Elexon data), then use **Decision**.

## Test, lint, build

```powershell
cd backend
.venv\Scripts\python -m pytest                # 117 tests, mocked Elexon (no network)
.venv\Scripts\python -m ruff check app tests
.venv\Scripts\python -m mypy app
# Same suite on PostgreSQL:
$env:TEST_DATABASE_URL="postgresql+psycopg://user:pw@localhost:5432/windtest"; .venv\Scripts\python -m pytest

cd frontend
npm test            # vitest, 55 tests
npm run typecheck
npm run lint
npm run build       # type-checks, outputs frontend/dist
```

## Deploy (Docker Compose)

```bash
cp .env.example .env        # set POSTGRES_PASSWORD (required) and CORS_ORIGINS
docker compose up -d --build
# UI on http://localhost:${WEB_PORT:-8080}; nginx serves the SPA and proxies /api to the backend
```

- **Persistence:** PostgreSQL data is on the named volume `pgdata`; calibrations survive restarts and re-creation. The DB port is not published. Without `DATABASE_URL` the backend falls back to SQLite at `/srv/data/wind.db`, which is **ephemeral unless you mount a volume** there.
- **Single backend process:** run exactly one backend replica/worker (see the comment in `backend/Dockerfile`).
- **Separate hosting:** build the frontend with `VITE_API_BASE_URL=https://api.example.com` and set the backend `CORS_ORIGINS` to the site origin.
- **Environment variables:** see `.env.example` and `backend/app/config.py` (`DATABASE_URL`, `CORS_ORIGINS`, `ELEXON_*` timeouts/retries, calibration defaults and limits, `LOG_LEVEL`). No secrets are in the code; the browser never calls Elexon.
- **No authentication:** the API and UI are unauthenticated. Put them behind your own access control (VPN, reverse-proxy auth) before exposing publicly. The API is read-mostly, but `POST /api/calibrations` triggers Elexon fetches.
- **Schema:** tables are created on start (`create_all`); there is no migration tool yet, so schema changes need a manual migration or a fresh database.

## Verification status

Verified: backend tests (SQLite and PostgreSQL 18), frontend tests, ruff, mypy, tsc, eslint, production build; full calibration, decision and evaluation
against the **live Elexon API**; restart persistence; cutoff boundaries (a vintage published exactly at the cutoff is eligible, one second later is not); screenshots of all three pages.

**Not verified:** the Docker images and `docker-compose.yml` were not built or run (the Docker daemon was not running in the development environment); behaviour under
real Elexon rate limiting (covered by mocked tests only); multi-user or multi-process use.

## Limitations

One calibration distribution is applied to every hour (no dependence on wind level, hour or season); hourly errors are correlated, so a daily total shortfall can differ from "buffer × hours".
A calibration of one quarter is a modest sample, so the P95 is an indicator rather than a guarantee. FUELHH values can be revised after first publication; cached actuals are refreshed only if the cached range was not closed when fetched.
