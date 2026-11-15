# Test fixtures

- `video/` — put the demo clip here as `demo.mp4` (3–5 min of the MIT recitation). Video files are git-ignored; share them separately.
- `frames/` — hand-labelled board frames for accuracy tests: `NN.jpg` plus `NN.json` with the correct reading (`{"lines": [...], "latex": [...]}`).
- `llm/<task>/*.json` — recorded model responses used by `FakeLLM` (no API key needed). Each must validate against its contract (`tests/test_contracts.py` checks this).
- `transcript.json` — a small fake transcript matching the demo clip's opening.
- `elevenlabs/sample_response.json`, `fal/sample_response.json` — recorded-style speech-to-text responses for the same opening (mapping tests).

## Demo video source
`fixtures/video/full.mp4` (16.5 min) and `demo.mp4` (first 5 min) come from "Geometry of Linear Algebra", MIT 18.06SC
Linear Algebra, Fall 2011, MIT OpenCourseWare (https://www.youtube.com/watch?v=uNKDw46_Ev4), licensed CC BY-NC-SA 4.0.
Credit MIT OpenCourseWare in any demo. Only 360p exists for this recording; the board is still readable.
Re-download: `yt-dlp --js-runtimes node --remote-components ejs:github -f "bv*[height<=1080]+ba/b" --merge-output-format mp4 -o fixtures/video/full.mp4 <url>`
