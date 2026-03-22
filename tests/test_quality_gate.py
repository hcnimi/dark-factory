"""Tests for Phase 1.5: Input Quality Gate."""

from __future__ import annotations

import asyncio

import pytest

from dark_factory.ingest import TicketFields
from dark_factory.pipeline import (
    ReadinessReport,
    _quick_input_check,
    run_phase,
    run_phase_1_5,
)
from dark_factory.state import PipelineState, SourceInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state(tmp_path):
    return PipelineState(
        source=SourceInfo(kind="file", raw="spec.md", id="spec-1"),
        repo_root=str(tmp_path),
    )


@pytest.fixture
def valid_ticket():
    return TicketFields(
        summary="Add input quality gate to Dark Factory pipeline",
        description="Evaluate ticket fields against DoR and INVEST criteria.",
        acceptance_criteria=[
            "Given a ticket with all fields, score >= 80",
            "Given a ticket with missing AC, score == 0",
        ],
    )


@pytest.fixture
def empty_summary_ticket():
    return TicketFields(
        summary="",
        description="some description",
        acceptance_criteria=["criterion 1"],
    )


@pytest.fixture
def no_ac_ticket():
    return TicketFields(
        summary="A valid summary for the ticket",
        description="some description",
        acceptance_criteria=[],
    )


@pytest.fixture
def brief_summary_ticket():
    return TicketFields(
        summary="Short",
        description="desc",
        acceptance_criteria=["criterion"],
    )


# ---------------------------------------------------------------------------
# _quick_input_check
# ---------------------------------------------------------------------------

class TestQuickInputCheck:
    def test_empty_summary(self, empty_summary_ticket):
        issues = _quick_input_check(empty_summary_ticket)
        assert "Summary is empty" in issues

    def test_zero_acceptance_criteria(self, no_ac_ticket):
        issues = _quick_input_check(no_ac_ticket)
        assert "No acceptance criteria" in issues

    def test_brief_summary(self, brief_summary_ticket):
        issues = _quick_input_check(brief_summary_ticket)
        assert "Summary too brief" in issues

    def test_valid_ticket_no_issues(self, valid_ticket):
        issues = _quick_input_check(valid_ticket)
        assert issues == []

    def test_empty_summary_and_no_ac(self):
        """Both issues should be reported."""
        ticket = TicketFields(summary="", description="", acceptance_criteria=[])
        issues = _quick_input_check(ticket)
        assert "Summary is empty" in issues
        assert "No acceptance criteria" in issues


# ---------------------------------------------------------------------------
# ReadinessReport.status
# ---------------------------------------------------------------------------

class TestReadinessReportStatus:
    def test_ready_for_score_80(self):
        assert ReadinessReport(score=80).status == "ready"

    def test_ready_for_score_100(self):
        assert ReadinessReport(score=100).status == "ready"

    def test_gaps_found_for_score_50(self):
        assert ReadinessReport(score=50).status == "gaps_found"

    def test_gaps_found_for_score_79(self):
        assert ReadinessReport(score=79).status == "gaps_found"

    def test_not_ready_for_score_49(self):
        assert ReadinessReport(score=49).status == "not_ready"

    def test_not_ready_for_score_0(self):
        assert ReadinessReport(score=0).status == "not_ready"


# ---------------------------------------------------------------------------
# run_phase_1_5
# ---------------------------------------------------------------------------

class TestRunPhase1_5:
    def test_dry_run_returns_default_report(self, state, valid_ticket):
        report = asyncio.run(
            run_phase_1_5(state, valid_ticket, dry_run=True)
        )
        assert isinstance(report, ReadinessReport)
        assert report.score == 100
        assert report.status == "ready"

    def test_broken_input_short_circuits(self, state, empty_summary_ticket):
        """Obviously broken input returns score=0 without an SDK call."""
        report = asyncio.run(
            run_phase_1_5(state, empty_summary_ticket, dry_run=False)
        )
        assert report.score == 0
        assert report.status == "not_ready"
        assert len(report.gaps) > 0

    def test_no_ac_short_circuits(self, state, no_ac_ticket):
        report = asyncio.run(
            run_phase_1_5(state, no_ac_ticket, dry_run=False)
        )
        assert report.score == 0
        assert "No acceptance criteria" in report.gaps


# ---------------------------------------------------------------------------
# Phase routing: 1 → 1.5 → 2
# ---------------------------------------------------------------------------

class TestPhaseRouting:
    def test_phase_1_advances_to_1_5(self, state):
        async def noop():
            return None

        asyncio.run(run_phase(state, 1, noop))
        assert state.current_phase == 1.5

    def test_phase_1_5_advances_to_2(self, state):
        async def noop():
            return None

        state.current_phase = 1.5
        asyncio.run(run_phase(state, 1.5, noop))
        assert state.current_phase == 2

    def test_phase_1_through_2_sequence(self, state):
        """Full sequence: 0 → 1 → 1.5 → 2."""
        async def noop():
            return None

        asyncio.run(run_phase(state, 0, noop))
        assert state.current_phase == 1

        asyncio.run(run_phase(state, 1, noop))
        assert state.current_phase == 1.5

        asyncio.run(run_phase(state, 1.5, noop))
        assert state.current_phase == 2

        asyncio.run(run_phase(state, 2, noop))
        assert state.current_phase == 3
