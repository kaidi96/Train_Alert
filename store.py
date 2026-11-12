"""JSON persistence shared by the UI and the background monitor (same process)."""

import json
import threading
from contextlib import contextmanager
from pathlib import Path

DATA_FILE = Path(__file__).with_name("train_data.json")
MAX_HISTORY_PER_WATCH = 2000
MAX_EVENTS = 200

_lock = threading.RLock()


def _empty():
    return {"watches": [], "alerts": [], "history": {}, "events": []}


def load():
    with _lock:
        if not DATA_FILE.exists():
            return _empty()
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty()
        for key, default in _empty().items():
            data.setdefault(key, default)
        return data


@contextmanager
def transaction():
    """Load, yield a mutable dict, then save atomically."""
    with _lock:
        data = load()
        yield data
        data["events"] = data["events"][-MAX_EVENTS:]
        for wid, rows in data["history"].items():
            data["history"][wid] = rows[-MAX_HISTORY_PER_WATCH:]
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DATA_FILE)
