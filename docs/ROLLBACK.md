# Milestone 1 rollback

No rollback was performed. Stop only the frontend/backend processes you started, using Ctrl-C. Verification starts subprocesses and stops them automatically.

For a reversible rollback, make an archive outside this project containing `frontend/`, `backend/`, `docs/`, `.milestone-1/`, `.git/`, `.gitignore` and the generated `graphify-out/`. Then move these Milestone 1 additions outside the project; do not delete the archived files. Restore `AGENTS.md` from `.milestone-1/AGENTS.before.md` and `.graphifyignore` from `.milestone-1/graphifyignore.before` before moving the evidence directory. Keep later user edits separately if present.

Leave `.agents/`, `.codex/`, `.environment-preparation/` and `.venv-graphify/` in place. Do not run `git clean`, global npm/pip uninstall, APT removal, or autoremove. Milestone 1 changed no system packages or global configuration. Rollback of earlier environment preparation is a separate operation documented in the existing preparation records.

To discard only generated runtime environments, first retain `backend/wheelhouse/` and the native preparation artifacts, then move `frontend/node_modules/`, `frontend/dist/` and `backend/.venv/` into an archive. Recreate them with README commands when needed. There is no market database or application data to migrate in this milestone.
