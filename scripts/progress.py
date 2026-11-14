"""Print a progress summary from orchestration/tasks.json (`make progress`)."""

import json
from collections import Counter
from pathlib import Path

data = json.loads((Path(__file__).resolve().parents[1] / "orchestration" / "tasks.json").read_text())
tasks = data["tasks"]
order = ["todo", "building", "in_review", "changes_requested", "verified", "merged", "blocked"]
counts = Counter(t["status"] for t in tasks)
done = counts["merged"]
print(f"{data['project']} · {done}/{len(tasks)} merged")
print("  " + "  ".join(f"{s}: {counts[s]}" for s in order if counts[s]))
for phase in data["phases"]:
    pt = [t for t in tasks if t["phase"] == phase["id"]]
    if pt:
        merged = sum(t["status"] == "merged" for t in pt)
        print(f"\n{phase['name']} ({merged}/{len(pt)})")
        for t in pt:
            checks = " ".join(f"{k}:{v}" for k, v in t.get("checks", {}).items())
            print(f"  [{t['status']:<17}] {t['id']:<5} {t['title']}  ({t['owner']}) {checks}")
