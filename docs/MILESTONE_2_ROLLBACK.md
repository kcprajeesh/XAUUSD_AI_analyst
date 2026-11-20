# Milestone 2 rollback

No rollback was performed. Verification services have been stopped. Stop any development or preview process you started with Ctrl-C before restoring files.

1. Archive the current `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/index.html`, the six new frontend files listed in `MILESTONE_2.md`, both Milestone 2 documents and `.milestone-2/` outside the project. Retain any subsequent user edits separately.
2. Restore only the three modified frontend files from their exact copies under `.milestone-2/originals/frontend/`, keeping their original paths.
3. Move the new `frontend/src/chart.ts`, the three files in `frontend/src/components/`, and the two new test files outside the project. Keep the archived copies. Leave `components/` in place if it contains later user work.
4. Either restore the saved generated graph from `.milestone-2/originals/graphify-out/`, or run `. .venv-graphify/bin/activate` and `graphify update .` after restoring source. Original graph copies exclude disposable caches.
5. Keep this rollback record until restoration is verified. Archive/move the Milestone 2 evidence and report afterward if desired. The separate `.milestone-2/build/dist/` can be archived with that directory; the original `frontend/dist/` was not changed.
6. Run the restored frontend's TypeScript check and tests. If rebuilding, use a separate output directory again to retain existing generated artifacts.

Do not use the Milestone 1 whole-project rollback for this change. Leave the backend, `.milestone-1/`, `.agents/`, `.codex/`, `.environment-preparation/`, `.venv-graphify/`, dependency locks, environment templates and runtime environments in place. Do not run `git clean`, package uninstalls, APT removal, or autoremove.

There is no market database, provider configuration, AI service, or application data to migrate. Git remains initialized on `main` with no commits or remote, so exact pre-change copies are the rollback baseline for this milestone.
