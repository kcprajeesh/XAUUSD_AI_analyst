# Milestone 2 — frontend UI foundation

Milestone 2 is complete in `~/projects/XAUUSD_AI_analyst`. This milestone extends the existing frontend in place. No dependencies, validated versions, backend code, API contracts, providers, or execution capabilities changed. The current Milestone 2 authorization supersedes the historical Milestone 1 stopping point in the preserved project documentation. Work stops here; Milestone 3 requires separate approval.

## Screen and components

One research workspace uses real in-page navigation rather than empty routes or nonfunctional toolbar actions.

| Area | Implementation |
| --- | --- |
| Application shell | Existing `App.tsx`, brand header, skip link, named section navigation, research-only footer |
| Gold overview | XAUUSD instrument identity, unavailable last price/daily change, disconnected source state |
| Chart | `MarketChart.tsx`, lazy-loaded Lightweight Charts 5.3.0, one empty candlestick series, automatic container resize and cleanup |
| Timeframe controls | Existing Daily, 4H, 1H, 15M and 5M buttons; selection updates chart context and the highlighted analysis row |
| Multi-timeframe analysis | Five semantic table rows, all explicitly unavailable/awaiting data |
| Central AI Analyst | Explicit `insufficient_evidence` UI state, unavailable conclusion and missing evidence explanation |
| Macro intelligence | Unavailable US dollar, Treasury-yield and inflation context; awaiting verified releases/calendar data |
| Sentiment and news | Unavailable sentiment, no verified news, awaiting source-backed headlines |
| Evidence quality | Unassessed quality, unavailable source coverage/freshness, no source timestamp |
| Display timezone | Existing Qatar default, optional India, UTC, London and New York; named-zone formatting with daylight saving handling |

`Navigation.tsx` contains the section links. `IntelligencePanels.tsx` groups the five related intelligence panels with a shared semantic panel structure. `chart.ts` isolates the small chart initialization and failure-cleanup path. App state remains in the existing root component; no router, state library or provider wrapper was added.

No prices, OHLC values, signals, headlines, market timestamps or confidence percentages are fabricated. The chart receives no market data. Price/time axes and gesture controls are disabled while empty. TradingView attribution remains enabled, with an accessible external link below the chart. Workspace-opened time remains clearly separate from source freshness. Preferences remain local to the current page session.

## Design and responsive behavior

- Obsidian `#080d14` background, `#0e151f` panels, `#141d29` raised surfaces, neutral `#edf0f5` text, `#9aa6b5` muted text, champagne `#d8c29a` accents and `#283343` borders.
- Existing Segoe UI / Noto Sans / sans-serif system stack; no external fonts or imagery. Restrained weights, balanced headings, tabular timestamp numbers, consistent 8/16/24/32px spacing and subtle corner radii.
- Green/red are reserved for future directional candles. Unavailable states use neutral tones; the central insufficient-evidence state uses champagne.
- Base layout targets widths from 320px: stacked header, wrapping section links, one content column and wrapping timeframe buttons. No drawer or gesture-only navigation.
- At 640px: header/overview align horizontally and contextual panels use two columns. At 1024px: navigation rail, chart/conclusion beside multi-timeframe context, and three lower context columns. Width is capped at 1440px.
- Grid tracks use `minmax(0, ...)`; the timeframe table has fixed columns and wraps content. Controls and navigation have 44px targets, visible focus styles, labeled fields and native keyboard behavior. Safe-area padding and reduced-motion handling are included.

The Web Interface Guidelines were retrieved and used for a code-level review. All nine foreground/muted/champagne text pairings on the three surfaces exceed 4.5:1; the minimum calculated ratio is 6.87:1. This is a source/token check, not a browser accessibility audit.

The installed shadcn CLI reported no configuration and no installed UI components. Its relevant composition and semantic-token guidance was applied to the existing controls; no shadcn initialization, registry installation, new primitive dependency, or component replacement occurred. React, frontend-design, UI/UX, ponytail and graphify guidance were also applied.

## Files and preservation

Existing files edited in place, with exact pre-change copies in `.milestone-2/originals/`:

- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- `frontend/index.html` (theme-color metadata only)

New frontend files:

- `frontend/src/chart.ts`
- `frontend/src/components/Navigation.tsx`
- `frontend/src/components/MarketChart.tsx`
- `frontend/src/components/IntelligencePanels.tsx`
- `frontend/tests/chart.test.mjs`
- `frontend/tests/shell.test.mjs`

New documentation: this report and [Milestone 2 rollback](MILESTONE_2_ROLLBACK.md). `.milestone-2/` holds local verification evidence, original copies, the separate build output and its own ignore file. Existing project/dependency configurations were preserved. The required Graphify update refreshed derived outputs in `graphify-out/`; original graph outputs were copied before the update.

The [actual directory tree](../.milestone-2/directory-tree.txt) is generated from the filesystem, with dependency caches, preparation/tooling contents and rollback copies collapsed. The preservation ledger checks 474 pre-existing files: none missing; only the three frontend files and derived graph outputs changed. Backend code, health schema, locks, skills, hooks, preparation records, Milestone 1 evidence and original `frontend/dist/` assets remain unchanged.

## Verification results

| Check | Result |
| --- | --- |
| TypeScript | Passed, exit 0 |
| Existing frontend tests | All five passed unchanged |
| New frontend tests | Three chart initialization/cleanup checks and one real React server-render check passed |
| Frontend suite | 9 passed, 0 failed |
| Final production build | Passed, exit 0; 2,131 modules, 1.23 seconds |
| Final build sizes | Application JS 236.22 kB / 74.07 kB gzip; lazy chart JS 194.80 kB / 62.63 kB gzip; CSS 12.79 kB / 3.67 kB gzip |
| Backend regression | 12 pytest tests passed in 4.05 seconds |
| Python dependencies | `pip check`: no broken requirements; installed lock versions unchanged |
| API contract | Real `/health` response and `/openapi.json` verified; committed schema and endpoint set unchanged |
| Independent frontend startup | HTTP 200 at `127.0.0.1:5173`, source modules/CSS served with backend stopped |
| Independent backend startup | HTTP 200 at `127.0.0.1:8000/health`, frontend stopped |
| Production preview | HTTP 200 at `127.0.0.1:4173`; application assets and lazy chart bundle served from the Milestone 2 output |
| Teardown | All owned verification services stopped and ports released |
| Graphify | AST update passed without an AI provider |

An initial new SSR test used the wrong loader for React's CommonJS entry. The test harness was corrected to use native Node React imports; the complete frontend suite then passed. The initial failure log is retained. No dependency or application workaround was needed.

Evidence: `.milestone-2/backend-checks.log`, `frontend-checks-summary.log`, `frontend-final-build.log`, `independent-startup.json`, `text-contrast.json`, `preservation-and-dependencies.json`, `verification.json` and `graphify-update.log`.

## Run and review

Development commands from Milestone 1 still work independently:

```sh
cd frontend
npm run dev
```

To preserve the Milestone 1 build output, this milestone builds and previews separately:

```sh
npm run build -- --outDir ../.milestone-2/build/dist --emptyOutDir false
npm run preview -- --outDir ../.milestone-2/build/dist
```

Backend startup remains `cd backend` followed by `.venv/bin/python -m app`. Health remains `GET http://127.0.0.1:8000/health`; no frontend API coupling was introduced.

## Limits and rollback

No compatible browser was verified. Browser interaction, screenshots, actual responsive rendering, keyboard/screen-reader behavior, canvas initialization and ResizeObserver behavior were not tested. Chart lifecycle tests use a fake library object; the real package is typechecked, bundled and served, and React markup is server-rendered. These checks do not establish successful browser mounting or visual quality.

Market sources, AI analysis, meaningful chart data, persistent preferences, production load and deployment remain outside Milestone 2. Follow [MILESTONE_2_ROLLBACK.md](MILESTONE_2_ROLLBACK.md) for a reversible rollback that preserves the backend and all earlier records.
