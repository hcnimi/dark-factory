"""Session locking to prevent concurrent pipeline runs.

Uses a PID-based lockfile in .dark-factory/<session_id>.lock.
Stale locks (dead PID) are detected and auto-removed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .state import PipelineError


@dataclass
class SessionLock:
    """Represents an acquired session lock."""

    lock_path: Path
    pid: int
    run_id: str


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def acquire_lock(state_dir: Path, session_id: str, run_id: str) -> SessionLock:
    """Acquire an exclusive lock for a pipeline session.

    Raises PipelineError if the session is already locked by a running process.
    Stale locks (dead PID) are automatically removed with a warning.
    """
    import sys

    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / f"{session_id}.lock"

    if lock_path.exists():
        try:
            content = json.loads(lock_path.read_text())
            existing_pid = content.get("pid", 0)
            existing_run_id = content.get("run_id", "unknown")

            if _is_pid_alive(existing_pid):
                raise PipelineError(
                    0,
                    f"Session '{session_id}' is already running "
                    f"(PID {existing_pid}, run_id={existing_run_id}). "
                    f"If this is stale, delete {lock_path}",
                )

            # Stale lock — remove it
            print(
                f"⚠️  Removing stale lock for session '{session_id}' "
                f"(PID {existing_pid} is dead)",
                file=sys.stderr,
            )
            lock_path.unlink(missing_ok=True)

        except (json.JSONDecodeError, KeyError):
            # Corrupted lock file — remove it
            lock_path.unlink(missing_ok=True)

    # Write new lock
    lock_data = {
        "pid": os.getpid(),
        "run_id": run_id,
    }
    lock_path.write_text(json.dumps(lock_data))

    return SessionLock(lock_path=lock_path, pid=os.getpid(), run_id=run_id)


def release_lock(lock: SessionLock) -> None:
    """Release a session lock. Safe to call multiple times."""
    try:
        lock.lock_path.unlink(missing_ok=True)
    except OSError:
        pass
