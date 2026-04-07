"""Run state persistence and JSONL event logging."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from .types import RunState


def log_event(
    state: RunState,
    repo_root: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Append a JSONL event to the run's event log."""
    path = state.events_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_id": state.run_id,
        "type": event_type,
        "status": state.status.value,
        "cost_usd": state.cost_usd,
        **data,
    }
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def load_events(events_path: Path) -> list[dict[str, Any]]:
    """Load all events from a JSONL file."""
    if not events_path.exists():
        return []
    events = []
    for line in events_path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip corrupt lines
    return events
