"""Phase 6: issue creation from tasks.md.

Parses the task list, generates deterministic internal IDs (TASK-1, TASK-2, ...),
and returns CreatedIssue objects.  Zero LLM tokens consumed, no subprocesses.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field


@dataclass
class CreatedIssue:
    """A beads issue created by ``bd create``."""

    id: str
    title: str
    issue_type: str  # "epic" or "task"
    parent_id: str | None = None


@dataclass
class PhaseResult:
    """Outcome of Phase 6."""

    epic_id: str | None = None
    issues: list[CreatedIssue] = field(default_factory=list)


@dataclass
class ParsedTask:
    """A task parsed from tasks.md with dependency metadata."""

    index: int  # 1-based task number
    title: str  # task title (markers stripped)
    dependencies: list[int] = field(default_factory=list)  # 1-based indices this depends on


class CyclicDependencyError(Exception):
    """Raised when task dependencies form a cycle."""

    pass


class InvalidDependencyError(Exception):
    """Raised when a task depends on a non-existent task number."""

    pass


def parse_tasks_md(text: str) -> list[str]:
    """Extract task titles from tasks.md content.

    Recognises numbered lists, bullet lists, and checkbox lists.
    Strips [P] parallel markers but preserves them in the returned title
    so the caller can detect parallelism.
    """
    tasks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped[0].isdigit() and ". " in stripped:
            tasks.append(stripped.split(". ", 1)[1])
        elif line.startswith("- "):
            task = stripped[2:]
            if task.startswith("[ ] ") or task.startswith("[x] "):
                task = task[4:]
            tasks.append(task)
    return tasks


_PARALLEL_RE = re.compile(r"\[P\]\s*")
_DEPENDS_RE = re.compile(r"\[depends:\s*([\d,\s]+)\]\s*")


def parse_tasks_md_with_deps(text: str) -> list[ParsedTask]:
    """Extract tasks with dependency metadata from tasks.md content.

    Markers:
      [P]              - independent (no dependencies)
      [depends: N, ..] - depends on listed 1-based task numbers
      (no marker)      - task 1 is independent; task N>1 depends on N-1
    """
    tasks: list[ParsedTask] = []
    task_index = 0

    for line in text.splitlines():
        stripped = line.strip()
        title: str | None = None

        # Numbered list: "1. Title" or "1. [P] Title"
        if stripped and stripped[0].isdigit() and ". " in stripped:
            title = stripped.split(". ", 1)[1]
        # Bullet / checkbox list (only top-level, not indented sub-bullets)
        elif line.startswith("- "):
            title = stripped[2:]
            if title.startswith("[ ] ") or title.startswith("[x] "):
                title = title[4:]

        if title is None:
            continue

        task_index += 1
        dependencies: list[int] = []

        # Check for [P] marker
        m_par = _PARALLEL_RE.search(title)
        if m_par:
            title = _PARALLEL_RE.sub("", title).strip()
            # [P] → explicitly independent
            dependencies = []
        else:
            # Check for [depends: ...] marker
            m_dep = _DEPENDS_RE.search(title)
            if m_dep:
                title = _DEPENDS_RE.sub("", title).strip()
                dep_nums = [int(d.strip()) for d in m_dep.group(1).split(",") if d.strip()]
                dependencies = dep_nums
            else:
                # No marker: sequential default
                if task_index > 1:
                    dependencies = [task_index - 1]

        tasks.append(ParsedTask(index=task_index, title=title, dependencies=dependencies))

    return tasks


class TaskDAG:
    """Directed acyclic graph for task dependency resolution."""

    def __init__(self):
        self._tasks: dict[int, ParsedTask] = {}
        self._edges: dict[int, set[int]] = {}  # task -> set of tasks it depends on

    def add_task(self, task: ParsedTask) -> None:
        self._tasks[task.index] = task
        self._edges[task.index] = set(task.dependencies)

    def validate(self) -> None:
        """Validate: no cycles, no invalid refs, no self-refs. Raises on error."""
        for idx, deps in self._edges.items():
            for dep in deps:
                if dep == idx:
                    raise CyclicDependencyError(f"Task {idx} depends on itself")
                if dep not in self._tasks:
                    raise InvalidDependencyError(
                        f"Task {idx} depends on non-existent task {dep}"
                    )

        # Cycle detection via DFS with 3-color marking
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {idx: WHITE for idx in self._tasks}

        def dfs(node):
            color[node] = GRAY
            for dep in self._edges[node]:
                if color[dep] == GRAY:
                    raise CyclicDependencyError(f"Cycle detected involving task {dep}")
                if color[dep] == WHITE:
                    dfs(dep)
            color[node] = BLACK

        for node in self._tasks:
            if color[node] == WHITE:
                dfs(node)

    def resolve_waves(self) -> list[list[int]]:
        """Topological sort into waves. Each wave contains tasks whose deps are all in prior waves."""
        self.validate()

        in_degree = {idx: len(deps) for idx, deps in self._edges.items()}
        # Reverse edges: who depends on me?
        dependents: dict[int, set[int]] = {idx: set() for idx in self._tasks}
        for idx, deps in self._edges.items():
            for dep in deps:
                dependents[dep].add(idx)

        waves: list[list[int]] = []
        ready = deque(idx for idx, deg in in_degree.items() if deg == 0)

        while ready:
            wave = sorted(ready)  # deterministic ordering
            waves.append(wave)
            next_ready: deque[int] = deque()
            for idx in wave:
                for dependent in dependents[idx]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_ready.append(dependent)
            ready = next_ready

        return waves

    def map_to_issues(self, task_to_issue: dict[int, str]) -> list[list[str]]:
        """Replace 1-based task numbers with issue IDs in resolved waves."""
        waves = self.resolve_waves()
        return [[task_to_issue[idx] for idx in wave] for wave in waves]


_task_counter = 0


def _next_task_id() -> str:
    """Generate a deterministic internal task ID."""
    global _task_counter
    _task_counter += 1
    return f"TASK-{_task_counter}"


def _reset_task_counter() -> None:
    """Reset the counter (for testing)."""
    global _task_counter
    _task_counter = 0


def create_issues(
    source_id: str,
    summary: str,
    external_ref: str,
    tasks: list[str],
    dry_run: bool = False,
) -> PhaseResult:
    """Create internal issues for the task list.

    Simple (1-2 tasks): creates standalone task issues.
    Multi-part (3+ tasks): creates an epic with child task issues.
    IDs are deterministic (TASK-1, TASK-2, ...).
    """
    result = PhaseResult()

    if not tasks:
        return result

    is_multi = len(tasks) >= 3

    if is_multi:
        epic_id = _next_task_id()
        result.epic_id = epic_id
        result.issues.append(
            CreatedIssue(
                id=epic_id,
                title=f"{source_id}: {summary}",
                issue_type="epic",
            )
        )

        for task_title in tasks:
            task_id = _next_task_id()
            result.issues.append(
                CreatedIssue(
                    id=task_id,
                    title=task_title,
                    issue_type="task",
                    parent_id=epic_id,
                )
            )
    else:
        for task_title in tasks:
            task_id = _next_task_id()
            result.issues.append(
                CreatedIssue(
                    id=task_id,
                    title=f"{source_id}: {task_title}",
                    issue_type="task",
                )
            )

    return result
