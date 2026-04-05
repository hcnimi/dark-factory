"""Tests for dark_factory.state (event logging)."""

import json
from pathlib import Path

from dark_factory.state import log_event, load_events
from dark_factory.types import (
    RunState,
    RunConfig,
    RunStatus,
    SourceInfo,
    SourceKind,
)


def _make_state(tmp_path):
    source = SourceInfo(SourceKind.INLINE, "test feature", "test-feature")
    state = RunState.create(source=source, config=RunConfig())
    # Ensure .dark-factory dir exists
    state.state_dir(str(tmp_path))
    return state


class TestLogEvent:
    def test_creates_event_file(self, tmp_path):
        state = _make_state(tmp_path)
        log_event(state, str(tmp_path), "test_event", {"key": "value"})

        events_path = state.events_path(str(tmp_path))
        assert events_path.exists()

    def test_event_has_required_fields(self, tmp_path):
        state = _make_state(tmp_path)
        log_event(state, str(tmp_path), "test_event", {"key": "value"})

        events = load_events(state.events_path(str(tmp_path)))
        assert len(events) == 1

        event = events[0]
        assert event["type"] == "test_event"
        assert event["run_id"] == state.run_id
        assert "ts" in event
        assert event["key"] == "value"

    def test_appends_multiple_events(self, tmp_path):
        state = _make_state(tmp_path)
        log_event(state, str(tmp_path), "event_1", {})
        log_event(state, str(tmp_path), "event_2", {})
        log_event(state, str(tmp_path), "event_3", {})

        events = load_events(state.events_path(str(tmp_path)))
        assert len(events) == 3
        assert [e["type"] for e in events] == ["event_1", "event_2", "event_3"]

    def test_includes_status_and_cost(self, tmp_path):
        state = _make_state(tmp_path)
        state.status = RunStatus.IMPLEMENTING
        state.cost_usd = 1.23
        log_event(state, str(tmp_path), "test", {})

        events = load_events(state.events_path(str(tmp_path)))
        assert events[0]["status"] == "implementing"
        assert events[0]["cost_usd"] == 1.23


class TestLoadEvents:
    def test_empty_when_no_file(self, tmp_path):
        events = load_events(tmp_path / "nonexistent.jsonl")
        assert events == []

    def test_loads_valid_jsonl(self, tmp_path):
        path = tmp_path / "events.jsonl"
        lines = [
            json.dumps({"type": "a", "ts": "t1"}),
            json.dumps({"type": "b", "ts": "t2"}),
        ]
        path.write_text("\n".join(lines) + "\n")

        events = load_events(path)
        assert len(events) == 2
        assert events[0]["type"] == "a"
