# BoardNotes: guide for agents and teammates

Lecture video → board reading + transcript → cited notes and PDFs. Students suggest fixes and upvote them; lecturers approve.
Design source of truth: Figma file "BoardNotes Prototype" (pages Foundations, Components, Student screens, Lecturer screens).

## Layout
- `server/app/contracts/`: **shared data shapes**. Everything else depends on them. Don't change them in a feature branch;
  if you need a change, stop and note it in your PR. The lead updates contracts on `main` and runs `make contracts`.
- `server/app/llm/`: the only place that calls models. Use `LLM.structured(LLMRequest(...), Schema)`.
- `server/app/pipeline/`: processing stages. Signatures are fixed in `pipeline/interfaces.py`.
- `server/app/api/`, `server/app/jobs/`: FastAPI routes and the job runner.
- `web/`: Next.js app. Types in `web/src/contracts` are generated: never edit them by hand.
- `supabase/migrations/`: database schema (Supabase cloud in the demo, local Postgres in tests).
- `fixtures/`: demo clip, labelled frames, recorded model responses, fake transcript.
- `orchestration/tasks.json`: task list and status. `make progress` prints it.

## Rules
1. **Untrusted text never goes in instructions.** Board readings, transcripts, student fixes and questions go in
   `LLMRequest.untrusted`; they are wrapped in `<data>` tags and the model is told to treat them as data only.
2. **Every note cites its source.** A bullet needs ≥1 board block id or transcript range; the citation checker removes
   or flags anything else.
3. **No keys needed to build or test.** Default `LLM_MODE=fake` replays `fixtures/llm/<task>/*.json`. Add a fixture for
   every new LLM task, and keep it valid against the contract (tests enforce this). Mark real-API tests `@pytest.mark.live`.
4. **Roles are enforced on the server.** Students can never reach lecturer routes; the web app hides controls but is not the check.
5. **Times are seconds (float)** everywhere; format as mm:ss only in the UI.
6. **UI uses design tokens** (`bg-surface`, `text-secondary`, `rounded-lg`, …) from `web/src/styles/tokens.css`, never raw hex.
7. Models: Haiku 5.5 for the cheap frame pass, Sonnet 5.5 for board reading / fix checks / Q&A, Opus 5.5 for notes.
   Choose via `tier=` in `LLMRequest`, never by model id in feature code.

## Commands
- `make setup`, `make db` (local Postgres on :5433), `make migrate` (apply new migrations; `ENV=SUPABASE_DATABASE_URL` for the hosted db), `make check` (must pass before review), `make contracts`, `make progress`.
- Server tests: `cd server && uv run pytest`. Web: `cd web && pnpm typecheck && pnpm lint`.

## Workflow
One task per branch (`task/<ID>-short-name`) and one PR per task. The PR description says what changed, how it was
tested, and anything the lead must know. Reviewers: V1 code review, V2 independent tests, V3 security. A task is done
when all three pass and it's merged. Update the task's status in `orchestration/tasks.json` in the same PR.
