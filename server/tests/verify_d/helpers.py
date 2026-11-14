"""SSE parsing helper shared by V2 tests."""

import json


def parse_sse(text: str) -> list[tuple[str, str]]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data or ev != "message":
            events.append((ev, "\n".join(data)))
    return events


def sse_json(text: str, event: str):
    for ev, data in parse_sse(text):
        if ev == event:
            return json.loads(data)
    return None
