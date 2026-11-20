# Milestone 4 rollback

No rollback has been performed. Milestone 4 changed no frontend, API entry point, settings, locks, installed dependencies, skills, hooks or subscription. The repository still has no committed baseline, so do not use Git reset/clean to infer a prior milestone state.

Before rollback, archive the current `backend/app/data/`, `backend/tests/test_data_foundation.py`, `backend/tests/fixtures/synthetic_twelve_data.json`, current `docs/ARCHITECTURE.md`, the four new Milestone 4 data/schema/report/rollback documents, `.milestone-4/` and `graphify-out/` outside the project. Preserve any later edits separately. Also archive any local SQLite database **together with its journal/WAL/SHM sidecars after closing writers**; do not delete or downgrade market/research data. The only database created by this implementation run is `.milestone-4/synthetic-verification.sqlite3`, labelled synthetic; tests use temporary synthetic databases.

For a source rollback, move only these Milestone 4 additions outside the project:

- `backend/app/data/`
- `backend/tests/test_data_foundation.py`
- `backend/tests/fixtures/synthetic_twelve_data.json` (keep other fixture files if subsequently added)
- `docs/DATA_FOUNDATION.md`
- `docs/data-foundation.schema.json`
- `docs/MILESTONE_4.md`
- `docs/MILESTONE_4_ROLLBACK.md`

Restore `docs/ARCHITECTURE.md` from `.milestone-4/before/docs/ARCHITECTURE.md`. To restore the exact prior graph, archive the current graph directory and copy `.milestone-4/before/graphify-out/` back to `graphify-out/`; alternatively regenerate the graph against the rolled-back sources after restoring documentation. Keep `.milestone-4/` until all restoration and verification are finished, then retain it in the archive.

Verify the preserved backend from `backend/` with `.venv/bin/python -m pytest` (the pre-Milestone 4 baseline has 12 tests) and `.venv/bin/python -m pip check`. The health schema and route set require no rollback changes. Frontend code/build baselines were never overwritten; the Milestone 4 verification build is under `.milestone-4/build/dist/`.

There is no production database migration or automatic data deletion. SQLite schema v1 is new and explicit; older health-only code simply does not open it. Any later data foundation version needs a deliberate migration rather than silently resetting `PRAGMA user_version`.

Preserve all Milestone 1, 2 and any 2.5 evidence/rollback records, `.environment-preparation/`, `.agents/`, `.codex/`, `.venv-graphify/`, backend wheels/environments and installed hooks. Do not uninstall packages or run `git clean`. The `.milestone-4/preservation-before.json` manifest records 538 existing files; the final preservation report identifies the deliberately updated architecture and generated graph files.
