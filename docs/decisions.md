# Decisions

Newest first. Add an entry whenever you change a contract, a dependency, or how something fundamentally works.

## 2026-11-14 · Phase 0 foundations (lead)
- **Supabase cloud as hosted Postgres only.** The web app talks to our API, not to Supabase directly, so there's one
  auth path and one place for role checks. Live updates go over server-sent events from the API. Tests use the same
  schema on local Postgres (docker compose).
- **Offline by default.** `LLM_MODE=fake` replays recorded responses so agents and CI need no API keys.
- **Frames compared by text, not pixels.** Real lecture videos have camera movement; pixel diffs mark every frame as changed.
- **Model tiers.** Haiku 5.5 (glance), Sonnet 5.5 (board read, fix check, Q&A), Opus 5.5 (sections, notes).
- **No server-side refusal fallbacks yet.** Lecture maths is unlikely to trigger refusals; a refusal raises `RefusedError`
  and the stage is retried. Revisit if refusals show up in live runs.
- **Demo login instead of real auth.** Seeded users (one lecturer, three students) with a signed session cookie.
  University login is out of scope for the hackathon.
- **PDF via HTML + headless Chromium**, reusing the same layout as the web notes, plus a .tex export.
- **Local Postgres via Podman or Docker** (`make db` picks whichever works; docker compose isn't installed here).
- **Module paths for pipeline stages** (so parallel branches line up): `pipeline/video.py` (probe_video, extract_audio),
  `pipeline/keyframes.py` (select_keyframes), `pipeline/board.py` (read_board, merge_blocks), `pipeline/notes.py`
  (plan_sections, write_notes), `pipeline/citations.py` (validate_citations, check_latex), `pipeline/transcribe.py`
  (transcribe), `pipeline/pdf.py` (render_pdf, render_module_pdf), `pipeline/tex.py` (export_tex).
- **One branch + PR per agent workstream** during the parallel build (one commit per task), instead of one PR per task,
  to keep five agents from colliding on shared files. Only the lead edits `orchestration/tasks.json`.
