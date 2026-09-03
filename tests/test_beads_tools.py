"""Ladder PR-08: cell-side Beads — runner, scope (T1/T3/T4), tools. Temp boards only.

Needs the bd CLI (1.2.x). One board per module: `bd init` costs ~3s.
"""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from soma.beads import (
    BEADS_TOOL_NAMES,
    BdClaimAction,
    BdCloseAction,
    BdCreateAction,
    BdNoteAction,
    BdReadyAction,
    BdRunner,
    CellBoard,
    _ClaimExec,
    _CloseExec,
    _CreateExec,
    _NoteExec,
    _ReadyExec,
    board_for,
    check_bd,
)

pytestmark = pytest.mark.skipif(shutil.which("bd") is None, reason="bd CLI not installed")


@pytest.fixture(scope="module")
def runner(tmp_path_factory) -> BdRunner:
    r = BdRunner(tmp_path_factory.mktemp("board"))
    r.bootstrap()
    return r


@pytest.fixture
def board(runner) -> CellBoard:
    return CellBoard(runner)  # fresh claims per test, shared board


def seed(runner, title="seeded task") -> str:
    r = runner.create(title, "", 2, discovered_from=None)
    assert r.ok, r.error
    return r.data["id"]


def test_bootstrap_is_idempotent_and_prefixed(runner):
    assert (runner.board_dir / ".beads").is_dir()
    runner.bootstrap()  # no-op second time
    assert runner.id_prefix == "cell-"
    assert runner.ready().ok


def test_runner_roundtrip_create_claim_close(runner):
    bead = seed(runner, "roundtrip")
    assert bead.startswith("cell-")
    assert runner.claim(bead).ok
    closed = runner.close(bead, "done")
    assert closed.ok and closed.data[0]["status"] == "closed"


def test_runner_error_shape_is_actionable(runner):
    r = runner.close("cell-nope", "x")
    assert not r.ok
    assert "no issue found" in (r.error or "")


def test_malformed_json_guard(runner, monkeypatch):
    fake = SimpleNamespace(returncode=0, stdout="not json at all", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    r = runner.ready()
    assert not r.ok
    assert "non-JSON" in r.error and "soma doctor" in r.error


def test_T1_task_scoped_ops_refused_without_a_claim(board):
    create = _CreateExec(board)(BdCreateAction(title="found something"))
    assert create.is_error and "claim one first" in create.content[0].text


def test_T3_close_and_note_only_own_claims(board, runner):
    foreign = seed(runner, "someone else's")
    close = _CloseExec(board)(BdCloseAction(bead_id=foreign))
    assert close.is_error and "not a bead this cell claimed" in close.content[0].text
    note = _NoteExec(board)(BdNoteAction(bead_id=foreign, text="hi"))
    assert note.is_error


def test_T3_ids_above_scope_are_refused(board):
    obs = _ClaimExec(board)(BdClaimAction(bead_id="lambert-soma-bad.1"))
    assert obs.is_error and "never reaches above its scope" in obs.content[0].text


def test_claim_then_note_close_and_journal(board, runner):
    bead = seed(runner, "mine")
    assert not _ClaimExec(board)(BdClaimAction(bead_id=bead)).is_error
    assert board.current == bead
    assert not _NoteExec(board)(BdNoteAction(bead_id=bead, text="progress")).is_error
    assert not _CloseExec(board)(BdCloseAction(bead_id=bead, reason="ok")).is_error
    events = runner.run("list", "--type", "event")
    titles = {e["title"] for e in events.data}
    assert f"claimed {bead}" in titles and f"closed {bead}" in titles


def test_T4_discovery_hangs_off_current_claim(board, runner):
    bead = seed(runner, "parent work")
    _ClaimExec(board)(BdClaimAction(bead_id=bead))
    obs = _CreateExec(board)(BdCreateAction(title="side quest"))
    assert not obs.is_error
    new_id = obs.data["id"]
    shown = runner.run("show", new_id)
    dumped = json.dumps(shown.data)
    assert bead in dumped and "discovered" in dumped


def test_ready_lists_open_tasks_not_epics(board, runner):
    seed(runner, "visible")
    obs = _ReadyExec(board)(BdReadyAction())
    assert not obs.is_error and "visible" in obs.content[0].text


def test_tools_resolve_through_sdk_registry(tmp_path):
    from openhands.sdk import Tool, list_registered_tools
    from openhands.sdk.tool import resolve_tool

    assert set(BEADS_TOOL_NAMES) <= set(list_registered_tools())
    conv_state = SimpleNamespace(persistence_dir=str(tmp_path / "cell-x"))
    tools = resolve_tool(Tool(name="bd_ready"), conv_state)
    assert tools[0].name == "bd_ready"
    obs = tools[0].executor(BdReadyAction())
    assert "idle" in obs.content[0].text


def test_board_for_is_per_bundle(tmp_path):
    a = board_for(tmp_path / "one")
    assert a is board_for(tmp_path / "one")
    assert a is not board_for(tmp_path / "two")


def test_doctor_check_reports_version():
    checks = check_bd()
    assert checks and checks[0][0] is not False
    assert "bd 1." in checks[0][1]
