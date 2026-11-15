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

## 2026-11-15 · Phase 3 contracts (lead)
- **Generic across subjects.** No subject-specific checks (e.g. SymPy). Formulas are only checked for rendering.
- **Diagrams:** `DiagramRedraw` (LLM output) -> `DiagramFigure` on `BoardBlock.figure`. Redraw as a `ChartSpec`
  (rendered by our own code, never executed) or Mermaid (boxes and arrows) only when confident and it renders;
  otherwise `kind="crop"` from the best frame. The original crop is always reachable; redraws are labelled.
- **Stage order:** select_keyframes runs before transcribe so glance text can prime speech recognition
  (`Transcriber(audio, vocabulary)`); `BoardReader(keyframes, llm, transcript)` gets nearby speech as untrusted data.
  New stages: `FormulaRechecker`, `TermNormaliser`, `DiagramRedrawer` (see pipeline/interfaces.py).
- **Credits:** sponsor API credits are limited. Everything runs with `LLM_MODE=fake`; live runs need the user's OK.
  fal is used only for transcription.

## 2026-11-15 · Ask the lecture (lead)
- **Model:** Sonnet 5.5 (tier "board") at medium effort: explains and reasons well at about half Opus's price;
  ~1-2 cents per question on a 5-min lecture. `ASK_LLM_MODE=live` lets Ask use real calls while the pipeline stays
  offline; `ASK_EFFORT` tunes depth.
- **Tutor-style answers:** direct answer, then step-by-step reasoning in the lecture's own notation; general background
  allowed only as a labelled "Beyond this lecture:" paragraph; not-covered topics are refused; maths as `$...$`.
- **Follow-ups:** `AskIn.history` (last 6 turns) is sent as untrusted data. The lecture context is sent as a prompt-cached
  block (`LLMRequest.cached`), so follow-up questions re-read it cheaply.
