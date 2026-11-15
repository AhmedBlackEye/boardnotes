# Labelled board frames (accuracy test set)

15 frames from `fixtures/video/demo.mp4` (MIT OCW 18.06SC, CC BY-NC-SA). `NN.jpg` is the frame, `NN.json` the label:

- `time_s` – where the frame is in the clip
- `lines` – writing that is fully visible and readable, as written (plain text)
- `partial` – writing that is cut off, covered by the lecturer or still being written (`…` marks missing parts)
- `latex` – the formulas that are fully visible, in LaTeX
- `diagrams` – one short description per diagram
- `status` – `draft: needs human check` until someone has checked it, then `checked`

Labels describe only what is on the board in that frame, never what is said.
