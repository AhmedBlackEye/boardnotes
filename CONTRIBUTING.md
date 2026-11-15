# Joining the project

1. Read `CLAUDE.md` (rules and layout), then `docs/architecture.md`.
2. `cp .env.example .env`, `make setup`, `make db`, `make check`. Everything runs without API keys.
3. See what's happening: `make progress`, the progress dashboard (link in the README), and open PRs on GitHub.
4. Pick a `todo` task in `orchestration/tasks.json` (or ask the lead), set `owner` to your name and `status` to `building`.
5. Branch `task/<ID>-short-name`, open a PR early, fill in the template. Merge only when checks pass and a reviewer approves.

History lives in: git log, PR descriptions and reviews, `docs/decisions.md`, and `orchestration/tasks.json`.

## Browser tests (`make e2e`)
Playwright tests in `web/e2e/` click through the Figma flows against the real API: lecturer upload → processing →
notes → review queue → view as student → PDF; student source → fix (AI verdict) → upvote → ask → course notes; and
role checks. They run offline (`LLM_MODE=fake`, `TRANSCRIBER=fixture`), so no keys or credits are used.

- Needs the local Postgres (`make db`). `web/e2e/api_server.py` creates a throwaway `boardnotes_e2e_<random>` database
  from `supabase/migrations` and drops it afterwards; the main `boardnotes` database is never touched.
- Servers: API on :8010, web (`next dev`, build folder `.next-e2e`) on :3010, so your dev servers on :3000/:8000 keep running.
- Video: `fixtures/video/demo.mp4` if you have it (or `E2E_VIDEO=/path.mp4`), otherwise ffmpeg makes a 5-minute stand-in.
- One file: `cd web && pnpm test:e2e e2e/student.spec.ts`. Watch it: add `--headed` or `--ui`. A failure keeps a trace
  in `web/test-results/` (`pnpm exec playwright show-trace <trace.zip>`).
