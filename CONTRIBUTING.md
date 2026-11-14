# Joining the project

1. Read `CLAUDE.md` (rules and layout), then `docs/architecture.md`.
2. `cp .env.example .env`, `make setup`, `make db`, `make check`. Everything runs without API keys.
3. See what's happening: `make progress`, the progress dashboard (link in the README), and open PRs on GitHub.
4. Pick a `todo` task in `orchestration/tasks.json` (or ask the lead), set `owner` to your name and `status` to `building`.
5. Branch `task/<ID>-short-name`, open a PR early, fill in the template. Merge only when checks pass and a reviewer approves.

History lives in: git log, PR descriptions and reviews, `docs/decisions.md`, and `orchestration/tasks.json`.
