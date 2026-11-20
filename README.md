# XAUUSD AI Analyst

Gold market intelligence, with evidence before conclusions. The React research workspace and FastAPI health service run locally. Backend libraries provide provider normalization/staging, SQLite v1 persistence, deterministic technical analysis and provider-neutral AI foundations. Market retrieval, immutable evidence and AI research are not yet integrated into the running application; unavailable states remain explicit. No trading functionality exists.

## Run the frontend

Requirements: the validated Node 24.17.0 / npm 11.17.0 environment and Android ARM64 native dependencies on this device. Dependencies are already installed locally.

```sh
cd frontend
npm run dev
```

Open http://127.0.0.1:5173. The workspace remains usable when the backend is unavailable. Its health indicator uses `/api/health`, proxied locally to `127.0.0.1:8000`, with a ten-second deadline and retry. Backend health does not imply market or analyst readiness. Optional public configuration: copy `.env.example` to `.env` and choose `VITE_DISPLAY_TIMEZONE`. Only this public variable is accepted; never put credentials in any `VITE_` variable. Timeframe and timezone selections last for the current page session.

```sh
npm run typecheck
npm test
npm run build
npm run preview
```

Preview binds to http://127.0.0.1:4173 and uses the same local health proxy. Vite uses strict ports and binds to loopback by default. No external fonts, images, provider APIs, or browser analytics are requested by the shell. TradingView Lightweight Charts loads lazily as an empty chart surface; no fabricated candles are supplied.

## Run the backend

Requirements: Python 3.13.13, Termux NumPy 2.4.4, and the validated Android wheels. The permanent virtual environment is `backend/.venv`; it does not depend on the temporary compatibility environment.

```sh
cd backend
.venv/bin/python -m app
```

Health: http://127.0.0.1:8000/health. API documentation: http://127.0.0.1:8000/docs. The frontend is not needed. `.env.example` documents shell variables; it is not loaded automatically. To change the port, export `XAUUSD_PORT=8123` before starting; the frontend health proxy targets the default port 8000. `XAUUSD_HOST` accepts only `127.0.0.1`; invalid or unknown `XAUUSD_` settings stop startup. Ordinary import/startup/shutdown do not discover provider credentials, make provider/AI requests, or construct/open market storage, even when a provider credential is present. The existing `/api/v1/market-data/status` route returns a secret-free unavailable state with `startup_ingestion_disabled`; the analysis-ID lookup defaults to `503 analysis_projection_unavailable`. Health confirms reachability only. See [API behavior](docs/API.md).

```sh
.venv/bin/python -m pytest
.venv/bin/python -m pip check
```

## Recreate dependencies

Frontend `package.json` preserves all validated exact dependency versions; `package-lock.json` preserves every dependency entry, integrity hash and native optional package. Only project name/version metadata changed. The inherited shadcn CLI remains in the baseline; no shadcn components or additional packages were added.

For a repeatable Termux frontend install, isolate global npm configuration without modifying it:

```sh
cd frontend
mkdir -p .npm-cache
: > .npm-cache/user.config
: > .npm-cache/global.config
env npm_config_userconfig="$PWD/.npm-cache/user.config" \
  npm_config_globalconfig="$PWD/.npm-cache/global.config" \
  npm_config_omit= npm_config_include=optional \
  npm ci --ignore-scripts --cache "$PWD/.npm-cache"
```

Backend `requirements.lock` is a byte-for-byte copy of the approved hash-pinned runtime/test lock. NumPy is supplied by Termux, not pip. Do not install generic Linux ARM64 wheels on Android. The local `backend/wheelhouse/` contains all 22 hash-verified lock artifacts and is ignored by Git; preserve it for offline recreation. The original native wheels and source provenance remain in the preparation records.

```sh
cd backend
python -m venv --system-site-packages --without-pip .venv
PIP_CONFIG_FILE=/dev/null .venv/bin/python -m pip install \
  --no-index --find-links wheelhouse --require-hashes --no-deps \
  -r requirements.lock
```

This lock is specific to the validated Python 3.13 Android ABI. A fresh clone does not contain the ignored wheelhouse: restore the approved artifacts before using the offline command. A different platform or Python ABI needs separate validation. No global packages were installed, upgraded, or removed during Milestone 1.

## Project records

- [Architecture and scope](docs/ARCHITECTURE.md)
- [Health API contract](docs/API.md)
- [Milestone completion evidence](docs/MILESTONE_1.md)
- [Rollback](docs/ROLLBACK.md)
- [Development rules](AGENTS.md)
- [Master execution tracker](docs/MASTER_PROJECT_TRACKER.md)
- [Phase 2.5.18 contract and approval register](docs/PHASE_2_5_18_ARCHITECTURE_CLOSURE.md)

Existing `.agents/`, `.codex/`, `.environment-preparation/`, and `.venv-graphify/` remain in place. `.milestone-1/` holds initialization evidence and copies of the original project rules. Preparation logs and binary artifacts remain on disk even where `.gitignore` excludes them from Git.

The current master directive authorizes implementation covered by approved decisions. Deferred DEC-04 resource values and H4-03 policy, retention/source permissions, real database migrations and production activation remain gated as recorded in the master tracker. This application is not yet working-ready or production-ready; live end-to-end research, browser/device behavior, production load and Android background-service persistence remain unverified.
