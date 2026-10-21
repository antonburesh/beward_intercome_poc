"""JSON maps stored under config/."""

import json
from pathlib import Path


def read_dict(path):
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_dict(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data))
    temporary.replace(path)
