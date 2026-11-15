# Architecture

```
Browser (Next.js) ──HTTP/SSE──► FastAPI ──► Postgres (Supabase cloud / local)
                                  │  └────► video & images on disk (data/)
                                  └─ job runner ─► pipeline stages ─► Claude (via app/llm) · ElevenLabs
```

The web app only talks to the API. The API enforces roles, so the database is never exposed to browsers.

## Pipeline (offline, after upload)
1. **Check video**: ffprobe: needs picture + sound; warn under 720p. Extract mono 16 kHz audio.
2. **Transcribe**: `TRANSCRIBER` = fal Whisper (board vocabulary as prompt) or ElevenLabs Scribe, or the fixture offline; word timestamps, speakers (main speaker = lecturer).
3. **Select keyframes**: one frame every 3 s. Haiku reads each small frame ("which lines of writing are visible?").
   Frames are compared **by the text read, not by pixels**, because the camera pans and the lecturer moves.
   For each piece of new writing, keep the clearest frame that shows it fully. Typically 80–200 frames per 2 h.
4. **Read board**: Sonnet reads each keyframe at full resolution → blocks with LaTeX, confidence and position.
5. **Merge blocks**: the same writing seen in many frames becomes one block. Fuller readings replace partial ones
   (e.g. an equation cut off by the top of the frame).
6. **Sections**: Opus splits the lecture at topic changes and board erases.
7. **Notes**: Opus writes each section's bullets from its board blocks + transcript, citing both.
8. **Citation check**: code removes bullets without valid citations and flags low-confidence ones.
9. **PDF**: HTML → PDF per lecture and for the whole module. Unverified sections carry a Draft mark.

## Review priority
Open review items are sorted by:
```
priority = 2 × (1 − confidence) + log2(1 + upvotes) + (1 if AI agrees) − (2 if flagged)
```

## Guardrails
- Untrusted text (board, transcript, student fixes, questions) is passed as data in `<data>` tags, never as instructions.
- Models have no tools, so the worst a prompt injection can do is produce a wrong answer, which citations and lecturer review catch.
- Structured outputs everywhere; responses are validated against `app/contracts`.
- Upload limits: size (4 GB), container/codec checked with ffprobe before any processing.
- Approved fixes are stored in `training_examples` for later fine-tuning (Adaption).
