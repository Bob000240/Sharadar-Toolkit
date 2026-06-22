import json
from datetime import date, datetime
from pathlib import Path

_RUNS_ROOT = Path(__file__).parent


def get_run_dir(run_date: date | None = None) -> Path:
    d = run_date or date.today()
    path = _RUNS_ROOT / d.isoformat()
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(name: str, data: dict, run_date: date | None = None) -> Path:
    payload = {
        "date": (run_date or date.today()).isoformat(),
        "timestamp": datetime.now().isoformat(),
        **data,
    }
    path = get_run_dir(run_date) / f"{name}.json"
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"[runs] saved {path}")
    return path


def load_json(name: str, run_date: date | None = None) -> dict:
    path = get_run_dir(run_date) / f"{name}.json"
    with open(path) as f:
        return json.load(f)
