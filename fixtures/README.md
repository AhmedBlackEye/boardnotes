# Test fixtures

- `video/` — put the demo clip here as `demo.mp4` (3–5 min of the MIT recitation). Video files are git-ignored; share them separately.
- `frames/` — hand-labelled board frames for accuracy tests: `NN.jpg` plus `NN.json` with the correct reading (`{"lines": [...], "latex": [...]}`).
- `llm/<task>/*.json` — recorded model responses used by `FakeLLM` (no API key needed). Each must validate against its contract (`tests/test_contracts.py` checks this).
- `transcript.json` — a small fake transcript matching the demo clip's opening.
