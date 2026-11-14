"""Export JSON Schemas for every contract model to contracts/schemas/, so the web app can generate types.

Run via `make contracts`. CI fails if the committed schemas are out of date.
"""

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from pydantic import BaseModel  # noqa: E402

from app.contracts import ai, api  # noqa: E402

out = ROOT / "contracts" / "schemas"
out.mkdir(parents=True, exist_ok=True)
for old in out.glob("*.json"):
    old.unlink()

count = 0
for module in (ai, api):
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseModel) and obj.__module__ == module.__name__ and name not in {"Strict", "Api"}:
            schema = obj.model_json_schema(mode="serialization")
            (out / f"{name}.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
            count += 1
print(f"exported {count} schemas to {out.relative_to(ROOT)}")
