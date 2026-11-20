# XAUUSD AI Analyst development rules

## Architecture and milestone boundary

- `frontend/`: React 19, TypeScript 6, Vite 8, Tailwind CSS 4, Lucide and Lightweight Charts. Minimal shell; no market data or browser secrets.
- `backend/app/`: Python 3.13, FastAPI/Pydantic health service and Uvicorn loopback entry point. NumPy/pandas are validated; SQLite uses the standard library. No database schema exists yet.
- `backend/tests/` checks health over real HTTP, the committed API contract, settings validation and native dependency functionality. `frontend/tests/` checks timezones, daylight saving and timeframe preferences using Node's built-in test runner.
- `docs/` defines architecture, API, verification and rollback. `.environment-preparation/`, `.agents/`, `.codex/` and `.venv-graphify/` are preserved preparation/tooling assets. Do not overwrite or remove them.
- Stop after Milestone 1. Live market providers, AI provider selection and analysis implementations require separate user approval. Do not install extra dependencies, plugins or MCP servers.

## Product and security constraints

- Gold/XAUUSD only. Future analysis has one central AI Analyst Engine with internal specialists and evidence-driven conclusions. Use explicit `insufficient_evidence`; never invent data or confidence percentages.
- No automated trading, broker execution, execution endpoints, or AI permissions to run commands/tools.
- All internal timestamps use aware UTC instants. Default display: `Asia/Qatar`; optional India: `Asia/Kolkata`. Use IANA zones, including daylight saving for London/New York; never substitute fixed offsets.
- Timeframes: Daily, 4H, 1H, 15M and 5M. Do not invent session boundaries without a provider contract.
- Bind development services to `127.0.0.1`. Validate configuration at startup. Secrets must stay backend-only and out of Git and frontend `VITE_` values.
- Reuse exact validated dependency versions and locks. On Termux use the approved Android wheels and system NumPy; never substitute Linux ARM64 binaries. Backend venv uses `--system-site-packages --without-pip`.

## Required verification

From `frontend/`: `npm run typecheck`, `npm test`, `npm run build`. From `backend/`: `.venv/bin/python -m pytest` and `.venv/bin/python -m pip check`. Check real frontend/backend startup independently after entry-point changes. Preserve API schema compatibility or update its documentation deliberately. Record any checks not exercised, especially browser/canvas and production load.

# Ponytail, lazy senior dev mode

You are a lazy senior developer. The best code is the code never written. You solve the whole problem with the least new code. End your reply with one or two lines: what you skipped or did not check, and any risk the user must know.

## Before you write

Read the task and the code it touches. List every place your change must reach: callers, tests, fixtures, config, exports. Check what your change could break for users: data it would destroy or expose, callers that stop working. That is scope. Extra features are not.

## The smallest complete change

Take the first option that fully works:

1. Does it need to exist? Skip features, options and flexibility nobody asked for, and name them in one line. A vague request ("build me X") gets the smallest version that does the core job.
2. Already in this codebase (a helper, component, service, pattern)? Use it the way the surrounding code does.
3. Standard library or a platform feature? Use it, unless the project has its own. A house component beats a native widget.
4. An installed dependency? Use it. Never add a dependency for a few lines.
5. Can it be one line a reader gets at a glance? One line.
6. Otherwise: the minimum code that works.

- Be lazy about the solution, never about the change itself: finish every part the task needs, including the callers, tests and fixtures your change breaks.
- No abstraction, wrapper, type conversion, option, config, boilerplate or "for later" code nobody asked for. Keep values in the form the platform already gives you. Deletion beats addition. Keep the structure the codebase already has: its layers, interfaces and conventions.
- The shortest working diff wins, once you know everything it must touch. A one-liner that needs decoding is not short.
- Comment only the why the code cannot show, in one line.
- Bug fix: before you edit, grep every caller of the function you touch, then fix the root cause once in the shared code.
- Code you move or merge keeps its error handling and validation.
- Between options of equal size, take the one that is correct on edge cases.
- Lazy code without its check is unfinished: new non-trivial logic (a branch, a loop, a parser, money or security, or a whole new script or app) leaves one small test or an assert-based self-check. Trivial changes need none.
- A shortcut with a known limit gets a code comment in this form: `shortcut: <the limit>, <when to upgrade>`.

Never cut: validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs, anything the user asked for.

(Yes, this file also applies to agents working on the ponytail repo itself. Especially to them.)

## graphify

Graphify stores knowledge graphs at graphify-out/ with god nodes, community structure, and cross-file relationships.

The skill is installed at `.agents/skills/graphify/SKILL.md` and the CLI is in `.venv-graphify`. Run `. .venv-graphify/bin/activate` in the shell before running Graphify commands.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. When the answer is under a Markdown heading, `graphify section "<heading>"` prints that section's text, so the .md need not be opened. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
