"""Write one JSON file per task (+ meta/summary.json) for syncing to the progress dashboard.

Usage: python3 scripts/dashboard_export.py <out_dir>
The lead syncs these files to the dashboard's database at each milestone.
"""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1])
data = json.loads((root / "orchestration" / "tasks.json").read_text())
(out / "tasks").mkdir(parents=True, exist_ok=True)
(out / "meta").mkdir(parents=True, exist_ok=True)
for t in data["tasks"]:
    (out / "tasks" / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False))
activity_file = root / "orchestration" / "activity.json"
activity = json.loads(activity_file.read_text()) if activity_file.exists() else []
readiness_file = root / "orchestration" / "readiness.json"
readiness = json.loads(readiness_file.read_text()) if readiness_file.exists() else []
summary = {"project": data["project"], "updated": data["updated"], "phases": data["phases"], "activity": activity[:30], "readiness": readiness}
(out / "meta" / "summary.json").write_text(json.dumps(summary, ensure_ascii=False))
print(f"{len(data['tasks'])} tasks -> {out}")
