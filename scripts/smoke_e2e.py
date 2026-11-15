"""End-to-end smoke test against a running API: upload a video as the lecturer, wait for processing, check the notes.

Usage: uv run --project server python scripts/smoke_e2e.py [video] [api_url]
Runs offline when the API has LLM_MODE=fake (no credits). Exits non-zero on any failure.
"""

import json
import sys
import time
from pathlib import Path

import httpx

video = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures/video/demo.mp4")
api = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
TITLE = sys.argv[3] if len(sys.argv) > 3 else "Smoke test · Geometry of Linear Algebra"
c = httpx.Client(base_url=api, timeout=60)


def ok(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 400:
        sys.exit(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}")
    return r


t0 = time.time()
ok(c.post("/auth/demo-login", json={"user_id": "u_lecturer"}))
size = video.stat().st_size
up = ok(c.post("/uploads", json={"filename": video.name, "size_bytes": size, "title": TITLE})).json()
chunk = up["chunk_size"]
with video.open("rb") as f:
    pos = 0
    while pos < size:
        data = f.read(chunk)
        ok(c.put(f"/uploads/{up['upload_id']}", content=data, headers={"Content-Range": f"bytes {pos}-{pos + len(data) - 1}/{size}"}))
        pos += len(data)
done = ok(c.post(f"/uploads/{up['upload_id']}/complete")).json()
lecture_id = done["lecture_id"]
print(f"uploaded {size / 1e6:.1f} MB in {time.time() - t0:.1f}s -> {lecture_id}")

last = None
deadline = time.time() + 900
with c.stream("GET", f"/lectures/{lecture_id}/progress", timeout=None) as r:
    for line in r.iter_lines():
        if not line.startswith("data:"):
            continue
        p = json.loads(line[5:])
        if (p["stage"], round(p["progress"], 2)) != last:
            last = (p["stage"], round(p["progress"], 2))
            print(f"  {time.time() - t0:6.1f}s  {p['stage']:<14} {p['progress']:.2f}  {p['detail']}")
        if p.get("error"):
            sys.exit(f"job failed: {p['error']}")
        if p["stage"] == "done" or time.time() > deadline:
            break

d = ok(c.get(f"/lectures/{lecture_id}")).json()
secs, blocks = d["sections"], d["board_blocks"]
bullets = [b for s in secs for b in s["bullets"]]
print(f"status={d['summary']['status']} sections={len(secs)} bullets={len(bullets)} board_blocks={len(blocks)}")
for s in secs:
    print(f"  · {s['heading']} ({s['status']}, {len(s['bullets'])} bullets)")
assert secs and bullets, "no notes produced"
assert all(b["board_block_ids"] or b["transcript_ranges"] for b in bullets), "uncited bullet"
src = ok(c.get(f"/bullets/{bullets[0]['id']}/source")).json()
print(f"source view: {len(src['board_blocks'])} blocks, {len(src['transcript'])} transcript lines, {len(src['snapshot_urls'])} snapshots")
pdf = ok(c.get(f"/lectures/{lecture_id}/pdf"))
print(f"pdf: {len(pdf.content) / 1e3:.0f} kB, starts with {pdf.content[:5]!r}")
print(f"OK in {time.time() - t0:.0f}s")
